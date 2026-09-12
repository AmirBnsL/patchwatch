"""Monitor graph nodes — pure-ish functions ``(state, deps) -> partial state``.

Each node is unit-testable in isolation with a fake fetcher/repository.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from patchwatch.db.repositories import ChunkRecord, Repository
from patchwatch.diff.numeric import numeric_diff
from patchwatch.fixtures.snapshot import Digest, Fetcher, SnapshotDocument
from patchwatch.graph.state import (
    NEUTRAL,
    ChangeCandidate,
    DigestLoader,
    DocDelta,
    LLMAdjudicator,
    MonitorState,
)
from patchwatch.ingest.chunking import chunk_text
from patchwatch.ingest.embeddings import EmbeddingProvider, cosine_similarity
from patchwatch.ingest.normalize import content_hash, normalize_text

# difflib ratio above which a prose-only change is treated as neutral (fallback
# when no embedder is wired; calibrated on the frozen corpus).
COSMETIC_SIMILARITY_THRESHOLD = 0.96

# Embedding-distance bands for prose changes (cosine similarity).
EMBED_NEUTRAL_HIGH = 0.97  # >= → neutral without adjudication
EMBED_ADJUDICATE_LOW = 0.80  # >= → LLM adjudication; < → uncertain


@dataclass
class GraphDeps:
    """Everything the graph nodes need (injectable for tests)."""

    fetcher: Fetcher
    repo: Repository
    digest_loader: DigestLoader | None = None  # numeric sources only
    embedder: EmbeddingProvider | None = None  # enables vector storage + prose distance
    adjudicator: LLMAdjudicator | None = None  # borderline prose adjudication


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def ingest(state: MonitorState, deps: GraphDeps) -> dict[str, Any]:
    """Fetch current docs, hash-compare against the store, emit deltas."""
    docs = deps.fetcher.fetch(state["source"])
    fetched: list[DocDelta] = []
    deltas: list[DocDelta] = []
    for doc in docs:
        previous = deps.repo.latest(doc.source, doc.external_id)
        changed = previous is None or previous.content_hash != content_hash(doc.content)
        delta = DocDelta(document=doc, previous=previous, changed=changed, digest=doc.digest)
        fetched.append(delta)
        if changed:
            deltas.append(delta)
    return {
        "fetched": fetched,
        "deltas": deltas,
        "log": [f"ingest: fetched {len(docs)} doc(s), {len(deltas)} changed"],
    }


def version_diff(state: MonitorState, deps: GraphDeps) -> dict[str, Any]:
    """Diff changed docs: numeric path (digests) or prose path (chunked text)."""
    candidates: list[ChangeCandidate] = []
    for delta in state["deltas"]:
        if delta.digest is not None and delta.previous is not None:
            candidates.extend(_numeric_candidates(delta, delta.digest, deps))
        else:
            candidates.extend(_prose_candidates(delta, deps))
    return {
        "candidates": candidates,
        "log": [f"version_diff: {len(candidates)} candidate change(s)"],
    }


def _numeric_candidates(delta: DocDelta, digest: Digest, deps: GraphDeps) -> list[ChangeCandidate]:
    """Digest-vs-digest diff against the previous patch version."""
    assert delta.previous is not None  # numeric path requires a previous version
    assert deps.digest_loader is not None
    old_digest = deps.digest_loader.load(
        delta.document.source, delta.document.external_id, delta.previous.version or ""
    )
    if old_digest is None:
        return _prose_candidates(delta, deps)  # no old digest → fall back to text
    scope = delta.document.external_id or ""
    return [
        ChangeCandidate(
            document_id=delta.previous.id,
            chunk_index=0,
            old_text=str(change.old),
            new_text=str(change.new),
            similarity=0.0,
            kind="numeric",
            field=change.field,
            direction=change.direction,
            magnitude=change.magnitude,
        )
        for change in numeric_diff(old_digest, digest, scope)
    ]


def _prose_candidates(delta: DocDelta, deps: GraphDeps) -> list[ChangeCandidate]:
    """Chunk-aligned text diff (fixture/prose-style sources)."""
    old_chunks = deps.repo.chunks_for_document(delta.previous.id) if delta.previous else []
    new_chunks = chunk_text(delta.document.content)
    doc_key = delta.previous.id if delta.previous else ""
    span = max(len(old_chunks), len(new_chunks))
    candidates: list[ChangeCandidate] = []
    for index in range(span):
        old_text = old_chunks[index] if index < len(old_chunks) else ""
        new_text = new_chunks[index] if index < len(new_chunks) else ""
        if normalize_text(old_text) == normalize_text(new_text):
            continue
        similarity = (
            SequenceMatcher(None, normalize_text(old_text), normalize_text(new_text)).ratio()
            if old_text
            else 0.0
        )
        candidates.append(
            ChangeCandidate(
                document_id=doc_key,
                chunk_index=index,
                old_text=old_text,
                new_text=new_text,
                similarity=similarity,
            )
        )
    return candidates


def change_class(state: MonitorState, deps: GraphDeps) -> dict[str, Any]:
    """Assign the final class: numeric direction first, prose similarity second.

    Prose changes use embedding distance (if an embedder is wired) with LLM
    adjudication for the borderline band; difflib similarity is the fallback.
    Prose-only changes never claim a direction — they end 'neutral'/'uncertain'.
    """
    classified: list[ChangeCandidate] = []
    for candidate in state["candidates"]:
        if candidate.kind == "numeric":
            label = candidate.direction or "uncertain"
        elif not candidate.old_text:
            label = "uncertain"  # brand-new content
        elif deps.embedder is not None:
            label = _prose_label_embedded(candidate, deps)
        elif candidate.similarity >= COSMETIC_SIMILARITY_THRESHOLD:
            label = NEUTRAL
        else:
            label = "uncertain"
        classified.append(replace(candidate, change_class=label))
    summary = ", ".join(
        f"{c.kind}[{c.field or c.chunk_index}]={c.change_class}" for c in classified
    )
    return {
        "candidates": classified,
        "log": [f"change_class: {summary or 'none'}"],
    }


def _prose_label_embedded(candidate: ChangeCandidate, deps: GraphDeps) -> str:
    """Embedding-distance classification for a prose change."""
    assert deps.embedder is not None
    [old_vector, new_vector] = deps.embedder.embed([candidate.old_text, candidate.new_text])
    similarity = cosine_similarity(old_vector, new_vector)
    if similarity >= EMBED_NEUTRAL_HIGH:
        return NEUTRAL
    if similarity >= EMBED_ADJUDICATE_LOW and deps.adjudicator is not None:
        return deps.adjudicator.adjudicate(candidate.old_text, candidate.new_text)
    return "uncertain"


def reindex(state: MonitorState, deps: GraphDeps) -> dict[str, Any]:
    """Publish new versions: supersede old chunks, insert new rows (never delete)."""
    for delta in state["deltas"]:
        doc: SnapshotDocument = delta.document
        published_at = _parse_iso(doc.published_at)
        if delta.previous is not None:
            deps.repo.supersede_document(delta.previous.id, published_at)
        new_doc_id = deps.repo.insert_document_version(
            source=doc.source,
            external_id=doc.external_id,
            title=doc.title,
            version=doc.version,
            content_hash=content_hash(doc.content),
            fetched_at=published_at,
        )
        chunks = [
            ChunkRecord(chunk_index=index, content=text)
            for index, text in enumerate(chunk_text(doc.content))
        ]
        embeddings = (
            deps.embedder.embed([chunk.content for chunk in chunks])
            if deps.embedder is not None
            else None
        )
        deps.repo.insert_chunks(new_doc_id, chunks, published_at, embeddings)
    return {
        "reindexed": True,
        "log": [f"reindex: indexed {len(state['deltas'])} document version(s)"],
    }


def new_run_id() -> str:
    """A fresh, checkpoint-unique run id."""
    return uuid.uuid4().hex
