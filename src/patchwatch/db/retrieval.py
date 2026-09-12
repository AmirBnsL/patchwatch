"""Time-aware vector retrieval + version-mixing detection (SPEC §5.2).

Retrieval returns the chunk versions valid at ``at_time`` (the patch-pinned
predicate); ``version_mix_report`` flags queries whose top-k spans two
``valid_from`` windows for the same scope — the RAG-reliability failure mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine

RETRIEVE_SQL = """
SELECT c.id AS chunk_id,
       c.document_id AS document_id,
       d.external_id AS external_id,
       d.version AS version,
       d.source AS source,
       c.valid_from AS valid_from,
       (c.valid_to IS NULL) AS is_current,
       c.content AS content,
       c.embedding <=> CAST(:query_vector AS vector) AS distance
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE (c.valid_to IS NULL OR (c.valid_from <= :at_time AND c.valid_to > :at_time))
{source_clause}
ORDER BY c.embedding <=> CAST(:query_vector AS vector)
LIMIT :k
"""


@dataclass(frozen=True)
class RetrievedChunk:
    """One retrieval hit with its version provenance."""

    chunk_id: str
    document_id: str
    external_id: str
    source: str
    version: str
    valid_from: datetime
    is_current: bool
    content: str
    distance: float


@dataclass(frozen=True)
class MixReport:
    """Result of the version-mixing check over one retrieval batch."""

    mixed_scopes: list[str]  # external_ids spanning >1 valid_from window
    distinct_versions: dict[str, list[str]]  # scope → versions in top-k

    @property
    def is_mixed(self) -> bool:
        return bool(self.mixed_scopes)


def retrieve(
    engine: Engine,
    query_vector: list[float],
    at_time: datetime,
    k: int = 5,
    source_filter: str | None = None,
) -> list[RetrievedChunk]:
    """Top-k chunks valid at ``at_time``, nearest-first (cosine via HNSW)."""
    vector_literal = "[" + ",".join(f"{component:.7f}" for component in query_vector) + "]"
    params: dict[str, object] = {
        "query_vector": vector_literal,
        "at_time": at_time,
        "k": k,
    }
    source_clause = ""
    if source_filter is not None:
        source_clause = "AND d.source = :source_filter"
        params["source_filter"] = source_filter
    with engine.connect() as conn:
        rows = conn.execute(
            text(RETRIEVE_SQL.format(source_clause=source_clause)), params
        ).mappings()
        return [
            RetrievedChunk(
                chunk_id=str(row["chunk_id"]),
                document_id=str(row["document_id"]),
                external_id=str(row["external_id"]),
                source=str(row["source"]),
                version=str(row["version"]),
                valid_from=row["valid_from"],
                is_current=bool(row["is_current"]),
                content=str(row["content"]),
                distance=float(row["distance"]),
            )
            for row in rows
        ]


def version_mix_report(chunks: list[RetrievedChunk]) -> MixReport:
    """Flag scopes whose top-k hits span multiple ``valid_from`` windows."""
    by_scope: dict[str, list[RetrievedChunk]] = {}
    for chunk in chunks:
        by_scope.setdefault(chunk.external_id, []).append(chunk)

    mixed: list[str] = []
    versions: dict[str, list[str]] = {}
    for scope, hits in sorted(by_scope.items()):
        windows = sorted({hit.valid_from for hit in hits})
        versions[scope] = sorted({hit.version for hit in hits})
        if len(windows) > 1:
            mixed.append(scope)
    return MixReport(mixed_scopes=mixed, distinct_versions=versions)
