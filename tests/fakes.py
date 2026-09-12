"""Shared test doubles: in-memory repository + fetcher (no DB)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from patchwatch.db.repositories import ChunkRecord, StoredDocument
from patchwatch.fixtures.snapshot import FIXTURE_SOURCE, SnapshotDocument
from patchwatch.ingest.normalize import content_hash


@dataclass
class FakeRepository:
    """In-memory :class:`Repository` recording every call for assertions."""

    latest_by: dict[tuple[str, str], StoredDocument] = field(default_factory=dict)
    chunks_by_doc: dict[str, list[str]] = field(default_factory=dict)
    inserts: list[dict[str, Any]] = field(default_factory=list)
    chunk_inserts: list[tuple[str, list[tuple[int, str]], datetime, list[list[float]] | None]] = (
        field(default_factory=list)
    )
    superseded: list[tuple[str, datetime]] = field(default_factory=list)
    _next_id: int = 0

    def latest(self, source: str, external_id: str) -> StoredDocument | None:
        return self.latest_by.get((source, external_id))

    def chunks_for_document(self, document_id: str) -> list[str]:
        return self.chunks_by_doc.get(document_id, [])

    def insert_document_version(self, **kwargs: Any) -> str:
        self.inserts.append(kwargs)
        self._next_id += 1
        return f"doc-{self._next_id}"

    def insert_chunks(
        self,
        document_id: str,
        chunks: list[ChunkRecord],
        valid_from: datetime,
        embeddings: list[list[float]] | None = None,
    ) -> None:
        self.chunk_inserts.append(
            (document_id, [(c.chunk_index, c.content) for c in chunks], valid_from, embeddings)
        )

    def supersede_document(self, document_id: str, valid_to: datetime) -> None:
        self.superseded.append((document_id, valid_to))


@dataclass
class FakeFetcher:
    """Fetcher returning a fixed set of documents."""

    docs: list[SnapshotDocument]

    def fetch(self, source: str) -> list[SnapshotDocument]:
        if source != FIXTURE_SOURCE:
            raise ValueError(f"unsupported source: {source!r}")
        return self.docs


def stored(doc: SnapshotDocument) -> StoredDocument:
    """Build a stored-document row for a fixture version."""
    return StoredDocument(
        id=f"stored-{doc.version}",
        source=doc.source,
        external_id=doc.external_id,
        title=doc.title,
        version=doc.version,
        content_hash=content_hash(doc.content),
    )


class FakeDigestLoader:
    """In-memory digest loader returning canned digests per (external_id, version)."""

    def __init__(self, digests: dict[tuple[str, str], dict] | None = None) -> None:
        self.digests = digests or {}

    def load(self, source: str, external_id: str, version: str) -> dict | None:
        return self.digests.get((external_id, version))


class FakeAdjudicator:
    """Canned LLM adjudicator: routes by keyword for tests."""

    def __init__(self, verdict: str = "uncertain") -> None:
        self.verdict = verdict
        self.calls: list[tuple[str, str]] = []

    def adjudicate(self, old_text: str, new_text: str) -> str:
        self.calls.append((old_text, new_text))
        return self.verdict
