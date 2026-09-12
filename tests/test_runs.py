"""Run-persistence integration tests: runs / detected_changes / briefings rows."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from patchwatch.db.connection import get_engine
from patchwatch.db.repositories import DocumentRepository
from patchwatch.fixtures.snapshot import load_version
from patchwatch.graph.graph import run_monitor
from patchwatch.graph.nodes import GraphDeps
from patchwatch.observability.runs import RunRecorder
from tests.fakes import FakeDigestLoader, FakeFetcher, FakeStateRepository, stored

pytestmark = pytest.mark.integration


def test_monitor_run_persists_state_rows() -> None:
    v1 = load_version("26.6")
    repo = FakeStateRepository(latest_by={("ddragon", "champion/Ahri"): stored(v1)})
    recorder = RunRecorder(repo)

    from tests.test_hitl import _digest_doc

    result = run_monitor(
        GraphDeps(
            fetcher=FakeFetcher(
                [_digest_doc("26.7", {"stats.armor": 34})], expected_source="ddragon"
            ),
            repo=repo,
            digest_loader=FakeDigestLoader({("champion/Ahri", "26.6"): {"stats.armor": 36}}),
            brief_generator=_generator(),
            pool=_pool(),
        ),
        source="ddragon",
        recorder=recorder,
    )

    assert result["reindexed"] is True
    # run row started + finished with latency + trace
    assert len(repo.runs) == 1
    run_id, _started, recorded_trace = repo.runs[0]
    assert recorded_trace  # trace id recorded
    assert repo.finished and repo.finished[0]["run_id"] == run_id
    assert repo.finished[0]["status"] == "succeeded"
    assert repo.finished[0]["latency_ms"] >= 0
    # one detected_changes row for the actionable scope
    assert len(repo.changes) == 1
    change = repo.changes[0]
    assert change["new_version"] == "26.7"
    assert change["change_class"] == "nerf"
    assert change["severity"] in ("low", "medium", "high", "critical")
    # briefing row persisted
    assert len(repo.briefings) == 1
    assert repo.briefings[0]["run_id"] == run_id


def test_real_postgres_persists_run_rows() -> None:
    """End-to-end against real Postgres: runs/detected_changes/briefings rows exist."""
    from patchwatch.fixtures.pool import DEFAULT_POOL
    from patchwatch.graph.brief import TemplateBriefGenerator

    repo = DocumentRepository(get_engine())
    recorder = RunRecorder(repo)

    from tests.test_hitl import _digest_doc

    # Clean slate for the test scope (earlier runs may have left versions).
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "DELETE FROM chunks WHERE document_id IN "
                "(SELECT id FROM documents WHERE external_id = 'champion/Ahri')"
            )
        )
        conn.execute(text("DELETE FROM documents WHERE external_id = 'champion/Ahri'"))

    result = run_monitor(
        GraphDeps(
            fetcher=FakeFetcher(
                [_digest_doc("26.7", {"stats.armor": 34})], expected_source="ddragon"
            ),
            repo=repo,
            digest_loader=FakeDigestLoader({("champion/Ahri", "26.6"): {"stats.armor": 36}}),
            brief_generator=TemplateBriefGenerator(),
            pool=DEFAULT_POOL,
        ),
        source="ddragon",
        recorder=recorder,
    )

    run_id = result["run_id"]
    with get_engine().connect() as conn:
        run_row = conn.execute(
            text("SELECT status, latency_ms, trace_id FROM runs WHERE id = :id"),
            {"id": run_id},
        ).one()
        change_count = conn.execute(
            text("SELECT count(*) FROM detected_changes WHERE run_id = :id"), {"id": run_id}
        ).scalar_one()
        briefing_count = conn.execute(
            text("SELECT count(*) FROM briefings WHERE run_id = :id"), {"id": run_id}
        ).scalar_one()

    assert run_row.status == "succeeded"
    assert run_row.latency_ms >= 0
    assert run_row.trace_id
    assert change_count == 1
    assert briefing_count == 1

    # cleanup
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM briefings WHERE run_id = :id"), {"id": run_id})
        conn.execute(text("DELETE FROM detected_changes WHERE run_id = :id"), {"id": run_id})
        conn.execute(text("DELETE FROM runs WHERE id = :id"), {"id": run_id})


def _generator():
    from patchwatch.graph.brief import TemplateBriefGenerator

    return TemplateBriefGenerator()


def _pool():
    from patchwatch.fixtures.pool import DEFAULT_POOL

    return DEFAULT_POOL
