"""``MonitorState`` and its payload contracts (interface-first invariant #5).

Nodes take/return partial state as plain functions; the graph wires them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from patchwatch.db.repositories import StoredDocument
from patchwatch.fixtures.snapshot import SnapshotDocument


@dataclass
class DocDelta:
    """A fetched document and whether it changed vs the stored latest."""

    document: SnapshotDocument
    previous: StoredDocument | None = None
    changed: bool = False


@dataclass
class ChangeCandidate:
    """A chunk-level change between an old and new version."""

    document_id: str  # stored doc being superseded ("" for brand-new docs)
    chunk_index: int
    old_text: str
    new_text: str
    similarity: float
    change_class: str = ""  # "meaningful" | "cosmetic" (set by change_class node)


class MonitorState(TypedDict):
    """State carried through the monitor graph."""

    run_id: str
    source: str
    fetched: list[DocDelta]
    deltas: list[DocDelta]
    candidates: list[ChangeCandidate]
    reindexed: bool
    log: list[str]
