"""Time-aware retrieval + version-mixing integration tests (real Postgres)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from patchwatch.db.connection import get_engine
from patchwatch.db.repositories import ChunkRecord, DocumentRepository
from patchwatch.db.retrieval import retrieve, version_mix_report
from patchwatch.ingest.embeddings import HashEmbeddings

pytestmark = pytest.mark.integration

T_V1 = datetime(2026, 1, 15, tzinfo=UTC)
T_V2 = datetime(2026, 3, 20, tzinfo=UTC)
AT_V1 = datetime(2026, 2, 1, tzinfo=UTC)  # inside v1's validity window
NOW = datetime(2026, 9, 12, tzinfo=UTC)  # v2 current

EMBEDDER = HashEmbeddings(dim=1536)


@pytest.fixture
def scope_ext() -> Iterator[str]:
    """Two versions of one doc with distinct fake embeddings; cleans up after."""
    ext = f"it-{uuid4().hex[:10]}"
    repo = DocumentRepository(get_engine())
    doc_v1 = repo.insert_document_version(
        source="fixture",
        external_id=ext,
        title="t",
        version="v1",
        content_hash="h1",
        fetched_at=T_V1,
    )
    repo.insert_chunks(
        doc_v1,
        [ChunkRecord(chunk_index=0, content="ahri q orb of deception magic damage")],
        T_V1,
        EMBEDDER.embed(["ahri q orb of deception magic damage"]),
    )
    doc_v2 = repo.insert_document_version(
        source="fixture",
        external_id=ext,
        title="t",
        version="v2",
        content_hash="h2",
        fetched_at=T_V2,
    )
    repo.insert_chunks(
        doc_v2,
        [ChunkRecord(chunk_index=0, content="ahri q orb of deception magic damage raised")],
        T_V2,
        EMBEDDER.embed(["ahri q orb of deception magic damage raised"]),
    )
    repo.supersede_document(doc_v1, T_V2)  # v1 closed when v2 published
    yield ext
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "DELETE FROM chunks WHERE document_id IN "
                "(SELECT id FROM documents WHERE external_id = :e)"
            ),
            {"e": ext},
        )
        conn.execute(text("DELETE FROM documents WHERE external_id = :e"), {"e": ext})


def _query_vector() -> list[float]:
    return EMBEDDER.embed(["ahri q orb of deception magic damage"])[0]


def test_time_aware_retrieval_returns_window_correct_version(scope_ext: str) -> None:
    # Query inside v1's validity window → v1 chunk.
    hits_v1 = retrieve(get_engine(), _query_vector(), at_time=AT_V1, k=1, source_filter="fixture")
    assert hits_v1[0].version == "v1"
    assert not hits_v1[0].is_current
    # Query now → v2 chunk (current).
    hits_now = retrieve(get_engine(), _query_vector(), at_time=NOW, k=1, source_filter="fixture")
    assert hits_now[0].version == "v2"
    assert hits_now[0].is_current


def test_version_mix_flag_single_version_not_mixed(scope_ext: str) -> None:
    hits = retrieve(get_engine(), _query_vector(), at_time=NOW, k=1, source_filter="fixture")
    report = version_mix_report(hits)
    assert not report.is_mixed


def test_version_mix_report_flags_spanning_windows() -> None:
    """Unit test: the flag fires when top-k spans two windows for one scope."""
    from patchwatch.db.retrieval import RetrievedChunk

    def hit(version: str, valid_from: datetime, content: str) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=f"c-{version}",
            document_id="d1",
            external_id="champion/Ahri",
            source="ddragon",
            version=version,
            valid_from=valid_from,
            is_current=valid_from == T_V2,
            content=content,
            distance=0.1,
        )

    mixed_hits = [
        hit("16.17.1", T_V1, "old window chunk"),
        hit("16.18.1", T_V2, "new window chunk"),
    ]
    report = version_mix_report(mixed_hits)
    assert report.is_mixed
    assert report.mixed_scopes == ["champion/Ahri"]
    assert sorted(report.distinct_versions["champion/Ahri"]) == ["16.17.1", "16.18.1"]

    clean_hits = [hit("16.18.1", T_V2, "new window chunk")]
    assert not version_mix_report(clean_hits).is_mixed


def test_version_mix_flag_single_version_not_mixed_db(scope_ext: str) -> None:
    """DB sanity: correct time-aware retrieval cannot mix windows."""
    hits = retrieve(get_engine(), _query_vector(), at_time=NOW, k=5, source_filter="fixture")
    report = version_mix_report(hits)
    assert not report.is_mixed
