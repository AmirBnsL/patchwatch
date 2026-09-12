"""End-to-end monitor runs against compose Postgres — the Phase A acceptance path.

Simulates the lifecycle: v1 published -> indexed; v2 published -> detected,
classified, re-indexed (versioning preserved); re-run -> no-op.

Run with: docker compose up -d && uv run pytest -m integration
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import text

from patchwatch.db.connection import dispose_engine, get_engine
from patchwatch.db.repositories import DocumentRepository
from patchwatch.fixtures.snapshot import FIXTURE_SOURCE, SnapshotFetcher, load_version
from patchwatch.graph.graph import run_monitor
from patchwatch.graph.nodes import GraphDeps
from patchwatch.ingest.chunking import chunk_text

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def repo() -> DocumentRepository:
    dispose_engine()
    db = DocumentRepository(get_engine())
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - exercised when DB is down
        pytest.skip(f"Postgres not reachable: {exc}")
    return db


@pytest.fixture(autouse=True)
def _clean_slate() -> None:
    ext = load_version("26.6").external_id

    def _delete() -> None:
        with get_engine().begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM chunks WHERE document_id IN "
                    "(SELECT id FROM documents WHERE external_id = :ext)"
                ),
                {"ext": ext},
            )
            conn.execute(text("DELETE FROM documents WHERE external_id = :ext"), {"ext": ext})

    _delete()  # clean slate before
    yield
    _delete()  # and leave no trace after


def _doc_id(external_id: str, version: str) -> str:
    with get_engine().connect() as conn:
        return conn.execute(
            text("SELECT id FROM documents WHERE external_id = :e AND version = :v"),
            {"e": external_id, "v": version},
        ).scalar_one()


def _chunk_times(external_id: str, version: str) -> list[tuple[int, datetime | None]]:
    doc_id = _doc_id(external_id, version)
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT chunk_index, valid_to FROM chunks "
                "WHERE document_id = :id ORDER BY chunk_index"
            ),
            {"id": doc_id},
        ).all()
    return [(row[0], row[1]) for row in rows]


def test_monitor_lifecycle(repo: DocumentRepository) -> None:
    v1, v2 = load_version("26.6"), load_version("26.7")
    ext = v1.external_id

    # Run 1: only v1 published -> bootstrap index (new doc).
    first = run_monitor(GraphDeps(fetcher=SnapshotFetcher({"26.6"}), repo=repo), FIXTURE_SOURCE)
    assert first["reindexed"] is True
    assert first["candidates"]  # new-content candidates, all meaningful
    assert all(c.change_class == "meaningful" for c in first["candidates"])
    assert all(valid_to is None for _, valid_to in _chunk_times(ext, "26.6"))

    # Run 2: v2 now published -> delta, diff, classify, re-index.
    second = run_monitor(GraphDeps(fetcher=SnapshotFetcher({"26.7"}), repo=repo), FIXTURE_SOURCE)
    assert second["reindexed"] is True
    classes = [c.change_class for c in second["candidates"]]
    assert "meaningful" in classes and "cosmetic" in classes

    # Versioning preserved: v1 closed at v2's publish time, v2 current, nothing deleted.
    v1_valid_to = datetime.fromisoformat(v2.published_at.replace("Z", "+00:00"))
    assert all(valid_to == v1_valid_to for _, valid_to in _chunk_times(ext, "26.6"))
    assert all(valid_to is None for _, valid_to in _chunk_times(ext, "26.7"))
    total_chunks = len(chunk_text(v1.content)) + len(chunk_text(v2.content))
    with get_engine().connect() as conn:
        stored_chunks = conn.execute(
            text(
                "SELECT count(*) FROM chunks WHERE document_id IN "
                "(SELECT id FROM documents WHERE external_id = :ext)"
            ),
            {"ext": ext},
        ).scalar_one()
    assert stored_chunks == total_chunks  # never delete or overwrite

    # Run 3: re-fetch v2 -> no change -> no-op.
    third = run_monitor(GraphDeps(fetcher=SnapshotFetcher({"26.7"}), repo=repo), FIXTURE_SOURCE)
    assert third["reindexed"] is False
    assert third["deltas"] == []
