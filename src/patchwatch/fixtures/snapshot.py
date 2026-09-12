"""Frozen snapshot corpus + planted-change manifest.

Data Dragon JSON + official patch-note prose for 2-3 consecutive patches, with a
planted-edit manifest driving every eval case — deterministic and versioned.

This module is the minimal LoL mini-corpus: one watched scope (``champion/Ahri``)
across two patch snapshots (26.6 → 26.7) with exactly two planted edits:

- **cosmetic** — a typo fix in the overview prose.
- **numeric** (meaningful) — a base-damage change in the balance notes.

The full Data Dragon + prose snapshot fetcher replaces this in Phase A′.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

FIXTURE_SOURCE = "fixture"
EXTERNAL_ID = "champion/Ahri"


@dataclass(frozen=True)
class SnapshotDocument:
    """A single published snapshot of a watched scope (version = patch number)."""

    source: str
    external_id: str
    title: str
    version: str
    content: str
    published_at: str  # ISO-8601; used as valid_from for indexing


@dataclass(frozen=True)
class PlantedEdit:
    """Label for an intentional change between two snapshots (eval ground truth)."""

    version_from: str
    version_to: str
    kind: str  # "cosmetic" | "meaningful"
    scope: str
    description: str


V26_6_PUBLISHED_AT = "2026-03-17T00:00:00Z"
V26_7_PUBLISHED_AT = "2026-03-31T00:00:00Z"

_V26_6_CONTENT = """\
# Ahri — Champion Snapshot (26.6)

## 1. Overview
Ahri is a mobile mage who excelss at picking fights and disengaging with
Spirit Rush. This snapshot summarizes her live balance state for the current
patch. She scales well with ability haste and benefits from early pick
pressure, converting roams into turret damage and vision control for her team.

## 2. Abilities
Passive — Essence Theft: takedowns restore a portion of missing health.
Q — Orb of Deception: magic damage outbound, true damage on the return pass.
W — Fox-Fire: three foxfires that lock onto nearby enemies and deal magic
damage with a short cooldown refresh on takedown.
E — Charm: charms the first enemy hit and briefly marks them, increasing the
damage they take from Ahri's next ability rotation.
R — Spirit Rush: dashes and fires essence bolts with each dash, refreshing on
takedowns and enabling multi-angle engages in river and jungle fights.

## 3. Runes
Electrocute for burst trades in aggressive matchups; the flexibility of
First Strike into farm-heavy lanes remains viable for early gold income.

## 4. Recommended Skill Order
Max Q first, then W, and take a rank of E when the matchup demands it.

## 5. Recommended Items
Ludens Companion into Shadowflame remains the standard damage build, with
Zhonya's Hourglass as the standard defensive third item into dive comps.

## 6. Matchup Notes
Syndra outranges early; respect her all-in after six and hug minions to block
Q trades. Zed is playable with early armor and careful E usage, saving Charm
for his ultimate window. Against control mages, roam timing matters more than
lane priority, since Ahri's pick potential is strongest in the side lanes.

## 7. Balance Notes
Q base damage stands at 75/100/125/150/175 with no changes scheduled.
E charm duration is 1.0/1.2/1.4/1.6/1.8 seconds.

## 8. Patch Tracking
Snapshot generated from live data; superseded by the next patch version.
"""

_V26_7_CONTENT = """\
# Ahri — Champion Snapshot (26.7)

## 1. Overview
Ahri is a mobile mage who excels at picking fights and disengaging with
Spirit Rush. This snapshot summarizes her live balance state for the current
patch. She scales well with ability haste and benefits from early pick
pressure, converting roams into turret damage and vision control for her team.

## 2. Abilities
Passive — Essence Theft: takedowns restore a portion of missing health.
Q — Orb of Deception: magic damage outbound, true damage on the return pass.
W — Fox-Fire: three foxfires that lock onto nearby enemies and deal magic
damage with a short cooldown refresh on takedown.
E — Charm: charms the first enemy hit and briefly marks them, increasing the
damage they take from Ahri's next ability rotation.
R — Spirit Rush: dashes and fires essence bolts with each dash, refreshing on
takedowns and enabling multi-angle engages in river and jungle fights.

## 3. Runes
Electrocute for burst trades in aggressive matchups; the flexibility of
First Strike into farm-heavy lanes remains viable for early gold income.

## 4. Recommended Skill Order
Max Q first, then W, and take a rank of E when the matchup demands it.

## 5. Recommended Items
Ludens Companion into Shadowflame remains the standard damage build, with
Zhonya's Hourglass as the standard defensive third item into dive comps.

## 6. Matchup Notes
Syndra outranges early; respect her all-in after six and hug minions to block
Q trades. Zed is playable with early armor and careful E usage, saving Charm
for his ultimate window. Against control mages, roam timing matters more than
lane priority, since Ahri's pick potential is strongest in the side lanes.

## 7. Balance Notes
Q base damage raised to 90/115/140/165/190 following early-game feedback.
E charm duration is 1.0/1.2/1.4/1.6/1.8 seconds.

## 8. Patch Tracking
Snapshot generated from live data; superseded by the next patch version.
"""


def _v26_6() -> SnapshotDocument:
    return SnapshotDocument(
        source=FIXTURE_SOURCE,
        external_id=EXTERNAL_ID,
        title="Ahri — Champion Snapshot",
        version="26.6",
        content=_V26_6_CONTENT,
        published_at=V26_6_PUBLISHED_AT,
    )


def _v26_7() -> SnapshotDocument:
    return SnapshotDocument(
        source=FIXTURE_SOURCE,
        external_id=EXTERNAL_ID,
        title="Ahri — Champion Snapshot",
        version="26.7",
        content=_V26_7_CONTENT,
        published_at=V26_7_PUBLISHED_AT,
    )


def load_corpus() -> list[SnapshotDocument]:
    """Return every published snapshot in the corpus (26.6, 26.7)."""
    return [_v26_6(), _v26_7()]


def load_version(version: str) -> SnapshotDocument:
    """Return a single corpus snapshot by patch number (raises ValueError if unknown)."""
    for doc in load_corpus():
        if doc.version == version:
            return doc
    raise ValueError(f"unknown fixture snapshot: {version!r}")


PLANTED_EDITS: list[PlantedEdit] = [
    PlantedEdit(
        version_from="26.6",
        version_to="26.7",
        kind="cosmetic",
        scope="Section 1 — Overview",
        description="Typo fix: 'excelss' → 'excels'.",
    ),
    PlantedEdit(
        version_from="26.6",
        version_to="26.7",
        kind="meaningful",
        scope="Section 7 — Balance Notes",
        description="Q base damage 75/100/125/150/175 → 90/115/140/165/190.",
    ),
]


class Fetcher(Protocol):
    """Contract for a document source — the ``ingest`` node depends on this."""

    def fetch(self, source: str) -> list[SnapshotDocument]: ...


class SnapshotFetcher:
    """Fetcher for the fixture source.

    ``versions=None`` returns the whole published corpus; pass a subset to
    simulate a point in time (e.g. ``{"26.6"}`` then ``{"26.6", "26.7"}``) so the
    monitor sees a new patch arrive across runs.
    """

    def __init__(self, versions: set[str] | None = None) -> None:
        self._versions = versions

    def fetch(self, source: str) -> list[SnapshotDocument]:
        if source != FIXTURE_SOURCE:
            raise ValueError(f"unsupported source: {source!r}")
        docs = load_corpus()
        if self._versions is not None:
            docs = [doc for doc in docs if doc.version in self._versions]
        return docs
