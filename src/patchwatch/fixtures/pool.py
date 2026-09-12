"""Personal player pool — the org-context of the impact briefing."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlayerPool:
    """The scopes this player cares about (drives relevance + briefing)."""

    champions: list[str] = field(default_factory=list)  # e.g. ["Ahri", "Syndra"]
    roles: list[str] = field(default_factory=list)  # e.g. ["mid", "support"]
    watchlist: list[str] = field(default_factory=list)  # item ids / terms of interest

    def tracks(self, external_id: str) -> bool:
        """Does the pool track this scope? ('champion/Ahri' / 'item/3031')"""
        kind, _, key = external_id.partition("/")
        if kind == "champion":
            return key in self.champions
        if kind == "item":
            return key in self.watchlist or external_id in self.watchlist
        return False


# The demo pool: mid-focused, includes champions with real 16.18.1 changes.
DEFAULT_POOL = PlayerPool(
    champions=["Ahri", "Syndra", "Cassiopeia", "Nautilus", "Bard", "Ekko"],
    roles=["mid", "support"],
    watchlist=["item/3031", "item/3153"],  # Infinity Edge, Blade of the Ruined King
)
