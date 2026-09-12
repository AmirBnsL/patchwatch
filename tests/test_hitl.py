"""HITL interrupt + checkpoint/resume tests (the SPEC §11 requirement).

Drives the REAL pipeline: ingest → diff → classify → brief → gate. Rework-level
candidates are produced via digest-backed documents (5 fields, +100% each), so
the interrupt fires for exactly the reason production would.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import Command

from patchwatch.fixtures.pool import DEFAULT_POOL
from patchwatch.fixtures.snapshot import Digest, SnapshotDocument, load_version
from patchwatch.graph.brief import TemplateBriefGenerator
from patchwatch.graph.graph import build_graph
from patchwatch.graph.nodes import GraphDeps
from tests.fakes import FakeDigestLoader, FakeFetcher, FakeRepository, stored


def _digest_doc(version: str, digest: Digest) -> SnapshotDocument:
    """A ddragon-style snapshot doc with a numeric digest (content hash differs per version)."""
    return SnapshotDocument(
        source="ddragon",
        external_id="champion/Ahri",
        title="Ahri (champion)",
        version=version,
        content=f"# Ahri — champion snapshot {version}",  # content differs → hash delta
        published_at="2026-03-31T00:00:00Z",
        digest=digest,
    )


def _state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": "run-1",
        "source": "ddragon",
        "patch_from": "26.6",
        "patch_to": "26.7",
        "fetched": [],
        "deltas": [],
        "candidates": [],
        "contradictions": [],
        "briefs": [],
        "approval": "",
        "reindexed": False,
        "log": [],
    }
    base.update(overrides)
    return base


def _graph():
    repo = FakeRepository(latest_by={("ddragon", "champion/Ahri"): stored(load_version("26.6"))})
    deps = GraphDeps(
        fetcher=FakeFetcher([]),
        repo=repo,
        digest_loader=FakeDigestLoader(),
        brief_generator=TemplateBriefGenerator(),
        pool=DEFAULT_POOL,
    )
    return build_graph(deps), repo


def _old_digest() -> Digest:
    return {f"stats.field{i}": 100 for i in range(5)}


def _run(state: dict[str, Any], thread: str):
    graph, _ = _graph()
    return graph.invoke(state, {"configurable": {"thread_id": thread}})


def test_hitl_auto_approves_below_threshold() -> None:
    """Single small nerf → brief below threshold → gate auto-approves → reindex."""
    v1 = load_version("26.6")
    repo = FakeRepository(latest_by={("ddragon", "champion/Ahri"): stored(v1)})
    deps = GraphDeps(
        fetcher=FakeFetcher([_digest_doc("26.7", {"stats.armor": 34})], expected_source="ddragon"),
        repo=repo,
        digest_loader=FakeDigestLoader({("champion/Ahri", "26.6"): {"stats.armor": 36}}),
        brief_generator=TemplateBriefGenerator(),
        pool=DEFAULT_POOL,
    )
    result = build_graph(deps).invoke(_state(), {"configurable": {"thread_id": "auto"}})
    assert result["approval"] == "auto-approved"
    assert result["reindexed"] is True
    assert result["briefs"] and not result["briefs"][0].requires_human


def test_hitl_interrupts_on_rework_and_resume_approves() -> None:
    graph, repo = _graph()
    config = {"configurable": {"thread_id": "hitl-approve"}}
    rework_digest = {f"stats.field{i}": 200 for i in range(5)}  # 5 × +100% = rework

    def deps_factory():
        return GraphDeps(
            fetcher=FakeFetcher([_digest_doc("26.7", rework_digest)], expected_source="ddragon"),
            repo=repo,
            digest_loader=FakeDigestLoader({("champion/Ahri", "26.6"): _old_digest()}),
            brief_generator=TemplateBriefGenerator(),
            pool=DEFAULT_POOL,
        )

    graph = build_graph(deps_factory())
    interrupted = graph.invoke(_state(), config)
    assert interrupted["reindexed"] is False
    interrupts = interrupted.get("__interrupt__")
    assert interrupts, "expected a real graph interrupt"
    assert interrupts[0].value["question"] == "Approve rework-level briefs?"

    # Resume from the checkpoint → approval flows → reindex runs.
    final = graph.invoke(Command(resume="approved"), config)
    assert final["approval"] == "approved"
    assert final["reindexed"] is True
    assert repo.inserts, "approved run re-indexed"


def test_hitl_rejected_stops_before_reindex() -> None:
    repo = FakeRepository(latest_by={("ddragon", "champion/Ahri"): stored(load_version("26.6"))})
    rework_digest = {f"stats.field{i}": 200 for i in range(5)}
    deps = GraphDeps(
        fetcher=FakeFetcher([_digest_doc("26.7", rework_digest)], expected_source="ddragon"),
        repo=repo,
        digest_loader=FakeDigestLoader({("champion/Ahri", "26.6"): _old_digest()}),
        brief_generator=TemplateBriefGenerator(),
        pool=DEFAULT_POOL,
    )
    graph = build_graph(deps)
    config = {"configurable": {"thread_id": "hitl-reject"}}

    graph.invoke(_state(), config)  # interrupt + checkpoint
    inserts_before = len(repo.inserts)

    final = graph.invoke(Command(resume="rejected"), config)
    assert final["approval"] == "rejected"
    assert final["reindexed"] is False
    assert len(repo.inserts) == inserts_before  # nothing indexed


def test_hitl_unrecognized_resume_rejects() -> None:
    repo = FakeRepository(latest_by={("ddragon", "champion/Ahri"): stored(load_version("26.6"))})
    rework_digest = {f"stats.field{i}": 200 for i in range(5)}
    deps = GraphDeps(
        fetcher=FakeFetcher([_digest_doc("26.7", rework_digest)], expected_source="ddragon"),
        repo=repo,
        digest_loader=FakeDigestLoader({("champion/Ahri", "26.6"): _old_digest()}),
        brief_generator=TemplateBriefGenerator(),
        pool=DEFAULT_POOL,
    )
    graph = build_graph(deps)
    config = {"configurable": {"thread_id": "hitl-garbage"}}
    graph.invoke(_state(), config)
    final = graph.invoke(Command(resume="banana"), config)
    assert final["approval"] == "rejected"
    assert final["reindexed"] is False
