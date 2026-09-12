"""Impact-brief node + generator + severity tests (deterministic)."""

from __future__ import annotations

from typing import Any

from patchwatch.fixtures.pool import DEFAULT_POOL
from patchwatch.fixtures.snapshot import load_version
from patchwatch.graph.brief import TemplateBriefGenerator
from patchwatch.graph.nodes import GraphDeps, impact_brief, requires_human_for, severity_for
from patchwatch.graph.state import ChangeCandidate, DocDelta, MonitorState
from tests.fakes import FakeFetcher, FakeRepository, stored


def _state(**overrides: Any) -> MonitorState:
    base: MonitorState = {
        "run_id": "run-1",
        "source": "fixture",
        "patch_from": None,
        "patch_to": None,
        "fetched": [],
        "deltas": [],
        "candidates": [],
        "contradictions": [],
        "briefs": [],
        "reindexed": False,
        "log": [],
    }
    base.update(overrides)
    return base


def _candidate(
    direction: str = "buff", magnitude: float | None = None, field: str = "stats.armor"
) -> ChangeCandidate:
    return ChangeCandidate(
        document_id="stored-26.6",
        chunk_index=0,
        old_text="34",
        new_text="32",
        similarity=0.0,
        kind="numeric",
        field=field,
        direction=direction,
        magnitude=magnitude,
        change_class=direction,
    )


# --- severity rules ---


def test_severity_low_for_small_numeric_change() -> None:
    assert severity_for([_candidate(magnitude=0.04)]) == "low"


def test_severity_medium_for_moderate_change() -> None:
    assert severity_for([_candidate(magnitude=0.10)]) == "medium"


def test_severity_high_for_large_magnitude() -> None:
    assert severity_for([_candidate(magnitude=0.30)]) == "high"


def test_severity_high_for_many_fields() -> None:
    assert severity_for([_candidate(magnitude=0.01) for _ in range(5)]) == "high"


def test_requires_human_only_for_rework_level() -> None:
    assert requires_human_for([_candidate(magnitude=0.30)], "high") is True
    assert requires_human_for([_candidate(magnitude=0.10)], "medium") is False


# --- impact_brief node ---


def test_impact_brief_skipped_without_generator() -> None:
    v1, v2 = load_version("26.6"), load_version("26.7")
    repo = FakeRepository(latest_by={("fixture", v1.external_id): stored(v1)})
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=repo)
    delta = DocDelta(document=v2, previous=stored(v1), changed=True)
    out = impact_brief(_state(deltas=[delta]), deps)
    assert out["briefs"] == []
    assert "skipped" in out["log"][0]


def test_impact_brief_generates_cited_brief_for_actionable_scope() -> None:
    v1, v2 = load_version("26.6"), load_version("26.7")
    repo = FakeRepository(latest_by={("fixture", v1.external_id): stored(v1)})
    deps = GraphDeps(
        fetcher=FakeFetcher([]),
        repo=repo,
        brief_generator=TemplateBriefGenerator(),
        pool=DEFAULT_POOL,
    )
    delta = DocDelta(document=v2, previous=stored(v1), changed=True)
    candidates = [
        ChangeCandidate(
            document_id="stored-26.6",
            chunk_index=0,
            old_text="34",
            new_text="32",
            similarity=0.0,
            kind="numeric",
            field="stats.armor",
            direction="nerf",
            magnitude=0.06,
            change_class="nerf",
        ),
        ChangeCandidate(  # neutral candidate — excluded from actionable
            document_id="stored-26.6",
            chunk_index=1,
            old_text="a",
            new_text="a!",
            similarity=0.99,
            change_class="neutral",
        ),
    ]
    out = impact_brief(_state(deltas=[delta], candidates=candidates), deps)
    assert len(out["briefs"]) == 1
    brief = out["briefs"][0]
    assert brief.scope == "champion/Ahri"
    assert all(point.citation <= len(brief.evidence) for point in brief.impact_points)
    assert all(
        str(brief.evidence[point.citation - 1]) in point.text or point.text
        for point in brief.impact_points
    )
    assert not brief.requires_human  # single 6% change


def test_impact_brief_requires_human_on_rework_level() -> None:
    v1, v2 = load_version("26.6"), load_version("26.7")
    repo = FakeRepository(latest_by={("fixture", v1.external_id): stored(v1)})
    deps = GraphDeps(
        fetcher=FakeFetcher([]),
        repo=repo,
        brief_generator=TemplateBriefGenerator(),
        pool=DEFAULT_POOL,
    )
    delta = DocDelta(document=v2, previous=stored(v1), changed=True)
    candidates = [
        ChangeCandidate(
            document_id="stored-26.6",
            chunk_index=0,
            old_text="x",
            new_text="y",
            similarity=0.0,
            kind="numeric",
            field=f"stats.field{i}",
            direction="nerf",
            magnitude=0.5,
            change_class="nerf",
        )
        for i in range(5)  # 5 fields = rework-level
    ]
    out = impact_brief(_state(deltas=[delta], candidates=candidates), deps)
    assert out["briefs"][0].requires_human is True
    assert "needs human review" in out["briefs"][0].summary


def test_impact_brief_marks_pool_relevance() -> None:
    v1, v2 = load_version("26.6"), load_version("26.7")
    repo = FakeRepository(latest_by={("fixture", v1.external_id): stored(v1)})
    deps = GraphDeps(
        fetcher=FakeFetcher([]),
        repo=repo,
        brief_generator=TemplateBriefGenerator(),
        pool=DEFAULT_POOL,
    )
    delta = DocDelta(document=v2, previous=stored(v1), changed=True)
    candidates = [_candidate(direction="nerf", magnitude=0.06)]
    out = impact_brief(_state(deltas=[delta], candidates=candidates), deps)
    assert "in your pool" in out["briefs"][0].summary  # Ahri is in DEFAULT_POOL
