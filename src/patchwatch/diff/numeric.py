"""Numeric-first diff between digest versions (deterministic — no LLM).

Compares two flat digests and classifies each change as ``buff``/``nerf``/
``uncertain`` from a small path-based direction table: paths where an increase
means the player gets stronger (damage/stats) vs weaker (cooldowns/costs).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

# Paths where an INCREASE is a nerf (cooldowns/costs get worse for the player).
NERF_WHEN_INCREASED = re.compile(r"cooldown|cost|gold", re.IGNORECASE)
# Paths where an INCREASE is a buff (stats/effect values get better).
BUFF_WHEN_INCREASED = re.compile(
    r"effect|armor|spellblock|damage|hp|hpregen|mana|mp|attackspeed|crit|movespeed|"
    r"range|lifesteal|pen|regeneration",
    re.IGNORECASE,
)

DIRECTIONS = ("buff", "nerf", "uncertain")


@dataclass(frozen=True)
class NumericChange:
    """One scalar/rank change between two digest versions."""

    scope: str  # e.g. "champion/Ahri"
    field: str  # dotted digest path, e.g. "stats.armor"
    old: str | float | int | bool | None
    new: str | float | int | bool | None
    direction: str  # buff | nerf | uncertain
    magnitude: float | None = None  # relative change (|new-old|/|old|), single values


def parse_ranks(value: str | float | int | bool | None) -> list[float] | None:
    """Parse '70/105/140' → [70.0, 105.0, 140.0]; single numbers → [n]; else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or not re.fullmatch(r"-?\d+(\.\d+)?( */ *-?\d+(\.\d+)?)*", cleaned):
            return None
        return [float(part) for part in re.split(r"\s*/\s*", cleaned)]
    return None


def _direction(field: str, old_ranks: list[float], new_ranks: list[float]) -> str:
    if len(old_ranks) != len(new_ranks):
        return "uncertain"  # rank count changed (e.g. rework) — not a simple delta
    ups = all(new > old for old, new in zip(old_ranks, new_ranks, strict=True))
    downs = all(new < old for old, new in zip(old_ranks, new_ranks, strict=True))
    if not ups and not downs:
        return "uncertain"  # mixed per-rank shifts
    increased = ups
    if NERF_WHEN_INCREASED.search(field):
        return "nerf" if increased else "buff"
    if BUFF_WHEN_INCREASED.search(field):
        return "buff" if increased else "nerf"
    return "uncertain"


def numeric_diff(
    old: dict[str, str | float | int | bool | None],
    new: dict[str, str | float | int | bool | None],
    scope: str,
) -> list[NumericChange]:
    """Diff two flat digests: added/removed/changed numeric fields → changes.

    Non-numeric scalar changes are reported with direction ``uncertain`` and no
    magnitude (they are prose-layer signal).
    """
    changes: list[NumericChange] = []
    for field in sorted(set(old) | set(new)):
        old_value = old.get(field)
        new_value = new.get(field)
        if field not in old:
            changes.append(NumericChange(scope, field, None, new_value, "uncertain"))
            continue
        if field not in new:
            changes.append(NumericChange(scope, field, old_value, None, "uncertain"))
            continue
        if old_value == new_value:
            continue

        old_ranks, new_ranks = parse_ranks(old_value), parse_ranks(new_value)
        if old_ranks is None or new_ranks is None:
            # Non-comparable (text): keep as uncertain signal only if genuinely scalar.
            changes.append(NumericChange(scope, field, old_value, new_value, "uncertain"))
            continue

        direction = _direction(field, old_ranks, new_ranks)
        magnitude: float | None = None
        if len(old_ranks) == 1 and old_ranks[0] != 0:
            magnitude = abs(new_ranks[0] - old_ranks[0]) / abs(old_ranks[0])
        changes.append(NumericChange(scope, field, old_value, new_value, direction, magnitude))
    return changes


def changed_scopes(
    old_digests: dict[str, dict[str, str | float | int | bool | None]],
    new_digests: dict[str, dict[str, str | float | int | bool | None]],
) -> list[str]:
    """Scopes whose digest changed at all (cheap pre-filter using hash-free compare)."""
    return sorted(
        scope
        for scope in set(old_digests) | set(new_digests)
        if old_digests.get(scope) != new_digests.get(scope)
    )


def similarity_hint(old_text: str, new_text: str) -> float:
    """Prose similarity for text-layer candidates (kept beside the numeric engine)."""
    return SequenceMatcher(None, old_text, new_text).ratio()
