"""Hand-labeled ground truth for the frozen 16.17.1 → 16.18.1 patch pair.

Verified by hand against the frozen prose notes (16.18.1.md): "targeted nerfs on
overperforming pro supports like Nautilus and Bard, as well as some taps to
Seraphine bot and Zeri. A round of buffs is in order for Viego, Zaahen, Master
Yi, Ekko, and Kassadin. Finally, Cassiopeia has slithered her way into an
adjustment to help reduce her pro skew."

Scope-level direction = the aggregated intent of the patch for that champion.
"""

from __future__ import annotations

PAIR = ("16.17.1", "16.18.1")

# scope → expected direction (nerf | buff | uncertain)
SCOPE_DIRECTIONS: dict[str, str] = {
    "champion/Bard": "nerf",  # armor 34→32, armor/level 5→4.7
    "champion/Nautilus": "nerf",  # attack damage 61→58
    "champion/Syndra": "nerf",  # W cooldown 12→13
    "champion/Cassiopeia": "nerf",  # Q effect 75→65, W cost 40→45 ("adjustment")
    "champion/Ekko": "buff",  # Q cost 50→40
    "champion/MasterYi": "buff",  # armor/level 4.5→5
    "champion/Seraphine": "uncertain",  # rank-count change (11/10.5/…→11)
}

# Spot checks: scopes the pipeline must NOT report as changed (false positives).
UNCHANGED_SPOT_CHECKS: list[str] = [
    "champion/Ahri",
    "champion/Zed",
    "item/3031",  # Infinity Edge — untouched this patch
    "item/3153",  # Blade of the Ruined King
]
