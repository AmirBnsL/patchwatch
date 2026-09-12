"""``MonitorState`` and its payload contracts (interface-first invariant #5).

Nodes take/return partial state as plain functions; the graph wires them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict

from patchwatch.db.repositories import StoredDocument
from patchwatch.fixtures.snapshot import Digest, SnapshotDocument  # noqa: F401 (re-export)

# Change vocabulary (SPEC §6.1): numeric direction first, prose similarity second.
BUFF = "buff"
NERF = "nerf"
NEUTRAL = "neutral"
UNCERTAIN = "uncertain"
CLASSES = (BUFF, NERF, NEUTRAL, UNCERTAIN)
# Classes that warrant re-indexing (anything that could matter).
ACTIONABLE = (BUFF, NERF, UNCERTAIN)


@dataclass
class DocDelta:
    """A fetched document and whether it changed vs the stored latest."""

    document: SnapshotDocument
    previous: StoredDocument | None = None
    changed: bool = False
    digest: Digest | None = None  # numeric substrate for ddragon-style sources


@dataclass
class ChangeCandidate:
    """One detected change between an old and new version."""

    document_id: str  # stored doc being superseded ("" for brand-new docs)
    chunk_index: int
    old_text: str
    new_text: str
    similarity: float
    kind: str = "prose"  # "numeric" | "prose"
    field: str | None = None  # numeric: dotted digest path
    direction: str | None = None  # numeric: buff | nerf | uncertain
    magnitude: float | None = None  # numeric: relative change
    change_class: str = ""  # buff | nerf | neutral | uncertain (set by change_class)


class DigestLoader(Protocol):
    """Loads the flat digest for a scope at a specific version (mockable)."""

    def load(self, source: str, external_id: str, version: str) -> Digest | None: ...


class LLMAdjudicator(Protocol):
    """Adjudicates borderline prose changes (mockable; real impl = LLM, Phase B)."""

    def adjudicate(self, old_text: str, new_text: str) -> str:
        """Return 'neutral' or 'uncertain' for a borderline prose change."""
        ...


class MonitorState(TypedDict):
    """State carried through the monitor graph."""

    run_id: str
    source: str
    patch_from: str | None
    patch_to: str | None
    fetched: list[DocDelta]
    deltas: list[DocDelta]
    candidates: list[ChangeCandidate]
    reindexed: bool
    log: list[str]
