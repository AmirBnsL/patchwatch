"""DocumentRepository integration tests against compose Postgres.

Run with: docker compose up -d && uv run pytest -m integration
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from patchwatch.config import get_settings
from patchwatch.db.repositories import ChunkRecord, DocumentRepository
from patchwatch.ingest.normalize import content_hash

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine() -> Engine:
    db = create_engine(get_settings().database_url)
    try:
        with db.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - exercised when DB is down
        pytest.skip(f"Postgres not reachable: {exc}")
    return db


@pytest.fixture
def repo(engine: Engine) -> DocumentRepository:
    return DocumentRepository(engine)


@pytest.fixture(autouse=True)
def _cleanup(engine: Engine) -> None:
    yield
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM chunks WHERE document_id IN "
                "(SELECT id FROM documents WHERE external_id LIKE 'it-%')"
            )
        )
        conn.execute(text("DELETE FROM documents WHERE external_id LIKE 'it-%'"))


def _ext_id() -> str:
    return f"it-{uuid.uuid4().hex[:12]}"


def test_insert_latest_chunks_and_supersede(engine: Engine, repo: DocumentRepository) -> None:
    ext = _ext_id()
    published = datetime(2026, 1, 15, tzinfo=UTC)
    doc_id = repo.insert_document_version(
        source="fixture",
        external_id=ext,
        title="Policy",
        version="v1",
        content_hash=content_hash("hello world"),
        fetched_at=published,
    )
    repo.insert_chunks(
        doc_id,
        [
            ChunkRecord(chunk_index=0, content="first chunk"),
            ChunkRecord(chunk_index=1, content="second chunk"),
        ],
        published,
    )

    latest = repo.latest("fixture", ext)
    assert latest is not None and latest.version == "v1"
    assert repo.chunks_for_document(doc_id) == ["first chunk", "second chunk"]

    superseded_at = datetime(2026, 3, 20, tzinfo=UTC)
    repo.supersede_document(doc_id, superseded_at)

    assert repo.chunks_for_document(doc_id) == []  # no longer current
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM chunks WHERE document_id = :id"), {"id": doc_id}
        ).scalar_one()
        valid_to = conn.execute(
            text("SELECT valid_to FROM chunks WHERE document_id = :id AND chunk_index = 0"),
            {"id": doc_id},
        ).scalar_one()
    assert count == 2  # never deleted — only closed
    assert valid_to == superseded_at


def test_latest_returns_newest_fetched_version(repo: DocumentRepository) -> None:
    ext = _ext_id()
    t1 = datetime(2026, 1, 15, tzinfo=UTC)
    t2 = datetime(2026, 3, 20, tzinfo=UTC)
    repo.insert_document_version(
        source="fixture", external_id=ext, title="t", version="v1", content_hash="a", fetched_at=t1
    )
    repo.insert_document_version(
        source="fixture", external_id=ext, title="t", version="v2", content_hash="b", fetched_at=t2
    )
    assert repo.latest("fixture", ext) is not None
    assert repo.latest("fixture", ext).version == "v2"  # type: ignore[union-attr]
