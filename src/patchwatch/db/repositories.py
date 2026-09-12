"""Document / chunk repositories — versioning, never overwrite (invariant #1)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class StoredDocument:
    """A row in ``documents``."""

    id: str
    source: str
    external_id: str | None
    title: str | None
    version: str | None
    content_hash: str


@dataclass(frozen=True)
class ChunkRecord:
    """A chunk to insert for a document version."""

    chunk_index: int
    content: str


class Repository(Protocol):
    """Minimal contract the graph nodes depend on (mockable in unit tests)."""

    def latest(self, source: str, external_id: str) -> StoredDocument | None: ...

    def chunks_for_document(self, document_id: str) -> list[str]: ...

    def insert_document_version(
        self,
        *,
        source: str,
        external_id: str,
        title: str,
        version: str,
        content_hash: str,
        fetched_at: datetime,
    ) -> str: ...

    def insert_chunks(
        self,
        document_id: str,
        chunks: list[ChunkRecord],
        valid_from: datetime,
        embeddings: list[list[float]] | None = None,
    ) -> None: ...

    def supersede_document(self, document_id: str, valid_to: datetime) -> None: ...

    def insert_run(self, run_id: str, started_at: datetime, trace_id: str) -> None: ...

    def finish_run(
        self,
        *,
        run_id: str,
        finished_at: datetime,
        status: str,
        token_cost_cents: float,
        latency_ms: int,
    ) -> None: ...

    def insert_change(
        self,
        *,
        run_id: str,
        document_id: str | None,
        old_version: str | None,
        new_version: str,
        diff_preview: str,
        change_class: str,
        severity: str,
        contradiction: bool,
        status: str,
    ) -> str: ...

    def insert_briefing(
        self,
        *,
        run_id: str,
        change_id: str | None,
        summary: str,
        impact_points: list[dict[str, Any]],
        grounded_in: list[str],
        requires_human: bool,
    ) -> str: ...


class RunStateRepository:
    """Run-state methods (runs / detected_changes / briefings) mixed into DocumentRepository."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def insert_run(self, run_id: str, started_at: datetime, trace_id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO runs (id, started_at, status, trace_id) "
                    "VALUES (:id, :started_at, 'running', :trace_id)"
                ),
                {"id": run_id, "started_at": started_at, "trace_id": trace_id},
            )

    def finish_run(
        self,
        *,
        run_id: str,
        finished_at: datetime,
        status: str,
        token_cost_cents: float,
        latency_ms: int,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE runs SET finished_at = :finished_at, status = :status, "
                    "token_cost_cents = :cost, latency_ms = :latency WHERE id = :id"
                ),
                {
                    "id": run_id,
                    "finished_at": finished_at,
                    "status": status,
                    "cost": token_cost_cents,
                    "latency": latency_ms,
                },
            )

    def insert_change(
        self,
        *,
        run_id: str,
        document_id: str | None,
        old_version: str | None,
        new_version: str,
        diff_preview: str,
        change_class: str,
        severity: str,
        contradiction: bool,
        status: str,
    ) -> str:
        change_id = str(uuid4())
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO detected_changes "
                    "(id, run_id, document_id, old_version, new_version, diff_preview, "
                    " change_class, severity, contradiction, status) "
                    "VALUES (:id, :run_id, :document_id, :old_version, :new_version, "
                    " :diff_preview, :change_class, :severity, :contradiction, :status)"
                ),
                {
                    "id": change_id,
                    "run_id": run_id,
                    "document_id": document_id,
                    "old_version": old_version,
                    "new_version": new_version,
                    "diff_preview": diff_preview,
                    "change_class": change_class,
                    "severity": severity,
                    "contradiction": contradiction,
                    "status": status,
                },
            )
        return change_id

    def insert_briefing(
        self,
        *,
        run_id: str,
        change_id: str | None,
        summary: str,
        impact_points: list[dict[str, Any]],
        grounded_in: list[str],
        requires_human: bool,
    ) -> str:
        briefing_id = str(uuid4())
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO briefings "
                    "(id, run_id, change_id, summary, impact_points, grounded_in, requires_human) "
                    "VALUES (:id, :run_id, :change_id, :summary, "
                    " CAST(:impact_points AS jsonb), CAST(:grounded_in AS jsonb), :requires_human)"
                ),
                {
                    "id": briefing_id,
                    "run_id": run_id,
                    "change_id": change_id,
                    "summary": summary,
                    "impact_points": json.dumps(impact_points),
                    "grounded_in": json.dumps(grounded_in),
                    "requires_human": requires_human,
                },
            )
        return briefing_id


class DocumentRepository(RunStateRepository):
    """Postgres-backed implementation of :class:`Repository`."""

    def latest(self, source: str, external_id: str) -> StoredDocument | None:
        with self._engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT id, source, external_id, title, version, content_hash "
                        "FROM documents "
                        "WHERE source = :source AND external_id = :external_id "
                        "ORDER BY fetched_at DESC, id LIMIT 1"
                    ),
                    {"source": source, "external_id": external_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return StoredDocument(**row)

    def chunks_for_document(self, document_id: str) -> list[str]:
        """Current chunk contents for a document, in chunk order (Phase A: text only)."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT content FROM chunks "
                    "WHERE document_id = :document_id AND valid_to IS NULL "
                    "ORDER BY chunk_index"
                ),
                {"document_id": document_id},
            ).scalars()
        return list(rows)

    def insert_document_version(
        self,
        *,
        source: str,
        external_id: str,
        title: str,
        version: str,
        content_hash: str,
        fetched_at: datetime,
    ) -> str:
        """Insert a document version; idempotent — returns the existing id if present."""
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO documents "
                    "(source, external_id, title, version, content_hash, fetched_at) "
                    "VALUES (:source, :external_id, :title, :version, :content_hash, :fetched_at) "
                    "ON CONFLICT (source, external_id, version) DO NOTHING "
                    "RETURNING id"
                ),
                {
                    "source": source,
                    "external_id": external_id,
                    "title": title,
                    "version": version,
                    "content_hash": content_hash,
                    "fetched_at": fetched_at,
                },
            ).first()
            if row is not None:
                return str(row[0])
            existing = conn.execute(
                text(
                    "SELECT id FROM documents "
                    "WHERE source = :source AND external_id = :external_id AND version = :version"
                ),
                {"source": source, "external_id": external_id, "version": version},
            ).one()
            return str(existing[0])

    def insert_chunks(
        self,
        document_id: str,
        chunks: list[ChunkRecord],
        valid_from: datetime,
        embeddings: list[list[float]] | None = None,
    ) -> None:
        """Insert chunk rows; ``embeddings[i]`` pairs with ``chunks[i]`` (None = skip)."""
        if not chunks:
            return
        if embeddings is not None and len(embeddings) != len(chunks):
            raise ValueError("embeddings must pair 1:1 with chunks")
        # embedding intentionally NULL when no provider is wired (Phase A behavior).
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO chunks "
                    "(document_id, chunk_index, content, embedding, valid_from, source_hash) "
                    "VALUES (:document_id, :chunk_index, :content, "
                    "CAST(:embedding AS vector), :valid_from, :source_hash) "
                    "ON CONFLICT (document_id, chunk_index, valid_from) DO NOTHING"
                ),
                [
                    {
                        "document_id": document_id,
                        "chunk_index": chunk.chunk_index,
                        "content": chunk.content,
                        "embedding": _to_vector_literal(embeddings[index]) if embeddings else None,
                        "valid_from": valid_from,
                        "source_hash": _hash(chunk.content),
                    }
                    for index, chunk in enumerate(chunks)
                ],
            )

    def supersede_document(self, document_id: str, valid_to: datetime) -> None:
        """Close the current chunks of a document (``valid_to``); never deletes."""
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE chunks SET valid_to = :valid_to "
                    "WHERE document_id = :document_id AND valid_to IS NULL"
                ),
                {"document_id": document_id, "valid_to": valid_to},
            )


def _hash(content: str) -> str:
    from patchwatch.ingest.normalize import content_hash

    return content_hash(content)


def _to_vector_literal(vector: list[float] | None) -> str | None:
    """pgvector text literal: '[0.1,0.2,...]' (CAST handles it in SQL)."""
    if vector is None:
        return None
    return "[" + ",".join(f"{component:.7f}" for component in vector) + "]"
