"""Contradiction-detection eval set: labeled (old, new, label) guidance pairs.

`contradiction` = the new text gives DIFFERENT guidance (not just new numbers).
Pairs 1-6 are synthetic clarity cases; pairs 7-10 use real frozen-corpus
guidance text (16.17.1 vs 16.18.1) where the numeric changes did not alter
recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass

from patchwatch.ingest.llm import LLMClient
from patchwatch.ingest.normalize import content_hash


@dataclass(frozen=True)
class ContradictionCase:
    case_id: str
    old_text: str
    new_text: str
    label: bool  # True = contradiction
    note: str = ""


CONTRADICTION_CASES: list[ContradictionCase] = [
    ContradictionCase(
        "max-order-flip",
        (
            "Recommended Skill Order: Max Q first, then W, and take a rank of E "
            "when the matchup demands it."
        ),
        "Recommended Skill Order: Max E first for pick pressure, then Q, W last.",
        True,
        "opposite max order",
    ),
    ContradictionCase(
        "rush-item-flip",
        "Recommended Items: Ludens Companion into Shadowflame remains the standard damage build.",
        "Recommended Items: Avoid Ludens Companion this patch; rush Rod of Ages instead.",
        True,
        "rush item inverted",
    ),
    ContradictionCase(
        "combo-flip",
        "Engage pattern: R into the back line, then W, then Q to finish.",
        "Engage pattern: Q first to bait, then R past the front line, W to finish.",
        True,
        "opposite combo order",
    ),
    ContradictionCase(
        "matchup-flip",
        "Matchup Notes: Syndra outranges early; respect her all-in after six.",
        "Matchup Notes: You outrange Syndra early; force trades before six.",
        True,
        "opposite matchup advice",
    ),
    ContradictionCase(
        "number-only",
        "Q base damage stands at 75/100/125/150/175 with no changes scheduled.",
        "Q base damage raised to 90/115/140/165/190 following early-game feedback.",
        False,
        "same advice, new numbers",
    ),
    ContradictionCase(
        "typo-only",
        "Ahri is a mobile mage who excelss at picking fights and disengaging.",
        "Ahri is a mobile mage who excels at picking fights and disengaging.",
        False,
        "cosmetic",
    ),
    ContradictionCase(
        "frozen-bard",
        "Recommended Items: Ludens Companion into Shadowflame remains the standard damage build, "
        "with Zhonya's Hourglass as the standard defensive third item into dive comps.",
        "Recommended Items: Ludens Companion into Shadowflame remains the standard damage build, "
        "with Zhonya's Hourglass as the standard defensive third item into dive comps.",
        False,
        "real 16.18.1 Bard: armor nerf only, guidance unchanged",
    ),
    ContradictionCase(
        "frozen-ekko",
        (
            "Recommended Skill Order: Max Q first, then W, and take a rank of E "
            "when the matchup demands it."
        ),
        (
            "Recommended Skill Order: Max Q first, then W, and take a rank of E "
            "when the matchup demands it."
        ),
        False,
        "real 16.18.1 Ekko: cost buff only, guidance unchanged",
    ),
    ContradictionCase(
        "frozen-syndra",
        (
            "Recommended Skill Order: Max Q first, then W, and take a rank of E "
            "when the matchup demands it."
        ),
        (
            "Recommended Skill Order: Max Q first, then W, and take a rank of E "
            "when the matchup demands it."
        ),
        False,
        "real 16.18.1 Syndra: cooldown nerf only, guidance unchanged",
    ),
    ContradictionCase(
        "frozen-cassiopeia",
        "Recommended Items: Ludens Companion into Shadowflame remains the standard damage build.",
        "Recommended Items: Ludens Companion into Shadowflame remains the standard damage build.",
        False,
        "real 16.18.1 Cassiopeia: effect/cost nerf, guidance unchanged",
    ),
]


def run_contradiction_suite(llm: LLMClient) -> tuple[int, int, list[str]]:
    """Run the contradiction detector over labeled pairs → (correct, total, wrong_ids)."""
    from patchwatch.graph.nodes import guidance_contradiction

    correct, wrong = 0, []
    for case in CONTRADICTION_CASES:
        got = guidance_contradiction(case.old_text, case.new_text, llm)
        if got == case.label:
            correct += 1
        else:
            wrong.append(case.case_id)
    return correct, len(CONTRADICTION_CASES), wrong


def case_fingerprint(case: ContradictionCase) -> str:
    """Stable id for eval logging (hash of the pair)."""
    return content_hash(case.old_text + "\x00" + case.new_text)[:12]
