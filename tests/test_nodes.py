"""Node unit tests — fake fetcher/repository, no DB."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from patchwatch.fixtures.snapshot import FIXTURE_SOURCE, load_version
from patchwatch.graph.nodes import GraphDeps, change_class, ingest, reindex, version_diff
from patchwatch.graph.state import ChangeCandidate, DocDelta, MonitorState
from patchwatch.ingest.chunking import chunk_text
from patchwatch.ingest.normalize import content_hash
from tests.fakes import FakeDigestLoader, FakeFetcher, FakeRepository, stored


def _state(**overrides: Any) -> MonitorState:
    base: MonitorState = {
        "run_id": "run-1",
        "source": FIXTURE_SOURCE,
        "patch_from": None,
        "patch_to": None,
        "fetched": [],
        "deltas": [],
        "candidates": [],
        "contradictions": [],
        "reindexed": False,
        "log": [],
    }
    base.update(overrides)
    return base


# --- ingest ---


def test_ingest_new_doc_is_delta() -> None:
    v1 = load_version("26.6")
    deps = GraphDeps(fetcher=FakeFetcher([v1]), repo=FakeRepository())
    out = ingest(_state(), deps)
    assert len(out["deltas"]) == 1
    assert out["deltas"][0].document.version == "26.6"
    assert out["deltas"][0].previous is None


def test_ingest_unchanged_doc_is_not_delta() -> None:
    v2 = load_version("26.7")
    repo = FakeRepository(latest_by={(FIXTURE_SOURCE, v2.external_id): stored(v2)})
    deps = GraphDeps(fetcher=FakeFetcher([v2]), repo=repo)
    out = ingest(_state(), deps)
    assert out["deltas"] == []


def test_ingest_changed_hash_is_delta() -> None:
    v1, v2 = load_version("26.6"), load_version("26.7")
    repo = FakeRepository(latest_by={(FIXTURE_SOURCE, v1.external_id): stored(v1)})
    deps = GraphDeps(fetcher=FakeFetcher([v2]), repo=repo)
    out = ingest(_state(), deps)
    assert len(out["deltas"]) == 1
    assert out["deltas"][0].previous is not None
    assert out["deltas"][0].previous.version == "26.6"


# --- version_diff ---


def test_version_diff_emits_candidates_for_changed_chunks() -> None:
    v1, v2 = load_version("26.6"), load_version("26.7")
    repo = FakeRepository(
        latest_by={(FIXTURE_SOURCE, v1.external_id): stored(v1)},
        chunks_by_doc={"stored-26.6": chunk_text(v1.content)},
    )
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=repo)
    delta = DocDelta(document=v2, previous=stored(v1), changed=True)
    out = version_diff(_state(deltas=[delta]), deps)
    assert len(out["candidates"]) >= 1
    assert all(c.document_id == "stored-26.6" for c in out["candidates"])


def test_version_diff_new_doc_candidates_have_empty_old_text() -> None:
    v1 = load_version("26.6")
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=FakeRepository())
    delta = DocDelta(document=v1, previous=None, changed=True)
    out = version_diff(_state(deltas=[delta]), deps)
    assert len(out["candidates"]) >= 1
    assert all(c.old_text == "" for c in out["candidates"])


def test_version_diff_unchanged_delta_no_candidates() -> None:
    v1 = load_version("26.6")
    repo = FakeRepository(
        latest_by={(FIXTURE_SOURCE, v1.external_id): stored(v1)},
        chunks_by_doc={"stored-26.6": chunk_text(v1.content)},
    )
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=repo)
    delta = DocDelta(document=v1, previous=stored(v1), changed=False)
    out = version_diff(_state(deltas=[delta]), deps)
    assert out["candidates"] == []


def test_version_diff_numeric_path_uses_digest_loader() -> None:
    v266, v267 = load_version("26.6"), load_version("26.7")
    old_digest = {"stats.armor": 21.0, "spells.0.cooldown": "7"}
    new_digest = {"stats.armor": 18.0, "spells.0.cooldown": "7"}
    repo = FakeRepository(latest_by={(FIXTURE_SOURCE, v267.external_id): stored(v266)})
    deps = GraphDeps(
        fetcher=FakeFetcher([]),
        repo=repo,
        digest_loader=FakeDigestLoader({(v267.external_id, "26.6"): old_digest}),
    )
    delta = DocDelta(document=v267, previous=stored(v266), changed=True, digest=new_digest)
    out = version_diff(_state(deltas=[delta]), deps)
    assert len(out["candidates"]) == 1
    candidate = out["candidates"][0]
    assert candidate.kind == "numeric"
    assert candidate.field == "stats.armor"
    assert candidate.direction == "nerf"
    assert candidate.change_class == ""  # set later by change_class node


def test_version_diff_numeric_without_old_digest_falls_back_to_prose() -> None:
    v2 = load_version("26.7")
    repo = FakeRepository(latest_by={(FIXTURE_SOURCE, v2.external_id): stored(v2)})
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=repo, digest_loader=FakeDigestLoader())
    delta = DocDelta(document=v2, previous=stored(v2), changed=True, digest={"stats.hp": 590})
    out = version_diff(_state(deltas=[delta]), deps)
    assert all(candidate.kind == "prose" for candidate in out["candidates"])
    assert len(out["candidates"]) >= 1


# --- change_class ---


def test_change_class_typo_is_neutral() -> None:
    candidate = ChangeCandidate(
        document_id="d1",
        chunk_index=0,
        old_text="Ahri is a mobile mage who excelss at picking fights",
        new_text="Ahri is a mobile mage who excels at picking fights",
        similarity=0.98,
    )
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=FakeRepository())
    out = change_class(_state(candidates=[candidate]), deps)
    assert out["candidates"][0].change_class == "neutral"


def test_change_class_numeric_direction_is_final_label() -> None:
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=FakeRepository())
    for direction, expected in (("buff", "buff"), ("nerf", "nerf"), ("uncertain", "uncertain")):
        candidate = ChangeCandidate(
            document_id="d1",
            chunk_index=0,
            old_text="75",
            new_text="90",
            similarity=0.0,
            kind="numeric",
            field="stats.armor",
            direction=direction,
        )
        out = change_class(_state(candidates=[candidate]), deps)
        assert out["candidates"][0].change_class == expected


def test_change_class_prose_rewrite_is_uncertain() -> None:
    candidate = ChangeCandidate(
        document_id="d1",
        chunk_index=0,
        old_text="Q base damage stands at 75/100/125/150/175 with no changes scheduled.",
        new_text=("Q base damage raised to 90/115/140/165/190 following early-game feedback."),
        similarity=0.8,
    )
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=FakeRepository())
    out = change_class(_state(candidates=[candidate]), deps)
    assert out["candidates"][0].change_class == "uncertain"


def test_change_class_new_content_is_uncertain() -> None:
    candidate = ChangeCandidate(
        document_id="",
        chunk_index=0,
        old_text="",
        new_text="brand new content",
        similarity=0.0,
    )
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=FakeRepository())
    out = change_class(_state(candidates=[candidate]), deps)
    assert out["candidates"][0].change_class == "uncertain"


# --- reindex ---


def test_reindex_supersedes_previous_and_inserts_new_version() -> None:
    v1, v2 = load_version("26.6"), load_version("26.7")
    repo = FakeRepository(
        latest_by={(FIXTURE_SOURCE, v1.external_id): stored(v1)},
        chunks_by_doc={"stored-26.6": chunk_text(v1.content)},
    )
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=repo)
    delta = DocDelta(document=v2, previous=stored(v1), changed=True)
    out = reindex(_state(deltas=[delta]), deps)

    assert out["reindexed"] is True
    expected_to = datetime.fromisoformat(v2.published_at.replace("Z", "+00:00"))
    assert repo.superseded == [("stored-26.6", expected_to)]
    assert len(repo.inserts) == 1
    assert repo.inserts[0]["version"] == "26.7"
    assert repo.inserts[0]["content_hash"] == content_hash(v2.content)
    assert len(repo.chunk_inserts) == 1
    assert repo.chunk_inserts[0][0] == "doc-1"


def test_reindex_new_doc_skips_supersede() -> None:
    v1 = load_version("26.6")
    repo = FakeRepository()
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=repo)
    delta = DocDelta(document=v1, previous=None, changed=True)
    out = reindex(_state(deltas=[delta]), deps)
    assert out["reindexed"] is True
    assert repo.superseded == []
    assert len(repo.inserts) == 1
