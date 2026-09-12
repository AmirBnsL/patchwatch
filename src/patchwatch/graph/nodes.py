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
from patchwatch.fixtures.snapshot import Fetcher
from patchwatch.graph.state import ChangeCandidate, DocDelta, MonitorState
from patchwatch.ingest.chunking import chunk_text
from patchwatch.ingest.normalize import content_hash, normalize_text

# difflib ratio above which a changed chunk is treated as cosmetic (Phase A
# heuristic; replaced by embedding distance + LLM adjudication in Phase B).
# Calibrated on the fixture: the planted rewrite scores < 0.96, the typo ~0.98.
COSMETIC_SIMILARITY_THRESHOLD = 0.96


@dataclass
class GraphDeps:
    """Everything the graph nodes need (injectable for tests)."""

    fetcher: Fetcher
    repo: Repository


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
        delta = DocDelta(document=doc, previous=previous, changed=changed)
        fetched.append(delta)
        if changed:
            deltas.append(delta)
    return {
        "fetched": fetched,
        "deltas": deltas,
        "log": [f"ingest: fetched {len(docs)} doc(s), {len(deltas)} changed"],
    }


def version_diff(state: MonitorState, deps: GraphDeps) -> dict[str, Any]:
    """Chunk-level diff of changed docs against their stored chunks."""
    candidates: list[ChangeCandidate] = []
    for delta in state["deltas"]:
        old_chunks = deps.repo.chunks_for_document(delta.previous.id) if delta.previous else []
        new_chunks = chunk_text(delta.document.content)
        doc_key = delta.previous.id if delta.previous else ""
        span = max(len(old_chunks), len(new_chunks))
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
    return {
        "candidates": candidates,
        "log": [f"version_diff: {len(candidates)} candidate chunk(s)"],
    }


def change_class(state: MonitorState, deps: GraphDeps) -> dict[str, Any]:
    """Classify each candidate meaningful/cosmetic (Phase A similarity heuristic)."""
    classified: list[ChangeCandidate] = []
    for candidate in state["candidates"]:
        if not candidate.old_text:
            change_kind = "meaningful"  # brand-new content must be indexed
        else:
            change_kind = (
                "cosmetic"
                if candidate.similarity >= COSMETIC_SIMILARITY_THRESHOLD
                else "meaningful"
            )
        classified.append(replace(candidate, change_class=change_kind))
    summary = ", ".join(f"chunk[{c.chunk_index}]={c.change_class}" for c in classified)
    return {
        "candidates": classified,
        "log": [f"change_class: {summary or 'none'}"],
    }


def reindex(state: MonitorState, deps: GraphDeps) -> dict[str, Any]:
    """Publish new versions: supersede old chunks, insert new rows (never delete)."""
    for delta in state["deltas"]:
        doc = delta.document
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
        deps.repo.insert_chunks(new_doc_id, chunks, published_at)
    return {
        "reindexed": True,
        "log": [f"reindex: indexed {len(state['deltas'])} document version(s)"],
    }


def new_run_id() -> str:
    """A fresh, checkpoint-unique run id."""
    return uuid.uuid4().hex
