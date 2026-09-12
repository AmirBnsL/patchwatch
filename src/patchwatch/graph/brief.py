"""BriefGenerator implementations: deterministic fake + grounded OpenAI variant."""

from __future__ import annotations

from typing import Any

from patchwatch.graph.state import ImpactBrief, ImpactPoint
from patchwatch.ingest.llm import LLMClient


class TemplateBriefGenerator:
    """Deterministic brief generator — no LLM, template-based, fully grounded.

    Every impact point cites exactly one evidence entry (faithful by
    construction), so evals check the invariant structure, not LLM honesty.
    """

    def generate(
        self,
        *,
        scope: str,
        patch: str,
        change_summary: str,
        evidence: list[str],
        severity: str,
        requires_human: bool,
        pool: Any,
    ) -> ImpactBrief:
        tracked = pool is not None and pool.tracks(scope)
        points = [
            ImpactPoint(
                text=f"{scope} changed in {patch}: {description} [{index + 1}]",
                citation=index + 1,
            )
            for index, description in enumerate(evidence)
        ]
        relevance = "in your pool" if tracked else "not in your pool"
        summary = f"{scope} ({severity} severity, {relevance}): {change_summary}" + (
            " — needs human review" if requires_human else ""
        )
        return ImpactBrief(
            scope=scope,
            patch=patch,
            summary=summary,
            impact_points=points,
            evidence=evidence,
            requires_human=requires_human,
        )


_BRIEF_PROMPT = """You write short impact briefs for a League player about patch changes.

Scope: {scope} (patch {patch})
Severity: {severity}{human}
Player pool: champions={champions}, roles={roles}, watchlist={watchlist}

Change evidence (each line is one change, numbered):
{evidence}

Write a briefing. Format:
SUMMARY: one sentence.
POINTS: one per line, each ending with a citation [n] matching the evidence numbers.
"""


class OpenAIBriefGenerator:
    """LLM brief generator — output parsed for SUMMARY/POINTS with citations."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def generate(
        self,
        *,
        scope: str,
        patch: str,
        change_summary: str,
        evidence: list[str],
        severity: str,
        requires_human: bool,
        pool: Any,
    ) -> ImpactBrief:
        numbered = "\n".join(f"[{index + 1}] {line}" for index, line in enumerate(evidence))
        prompt = _BRIEF_PROMPT.format(
            scope=scope,
            patch=patch,
            severity=severity,
            human=" (needs human review)" if requires_human else "",
            champions=getattr(pool, "champions", []),
            roles=getattr(pool, "roles", []),
            watchlist=getattr(pool, "watchlist", []),
            evidence=numbered,
        )
        text = self._llm.complete(prompt)

        summary = ""
        points: list[ImpactPoint] = []
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("SUMMARY:"):
                summary = line.split(":", 1)[1].strip()
            elif line.startswith("- ") or line.upper().startswith("POINTS:"):
                body = line.split(":", 1)[-1].strip().lstrip("- ").strip()
                refs = [int(ref) for ref in __import__("re").findall(r"\[(\d+)\]", body)]
                if refs:
                    points.append(ImpactPoint(text=body, citation=refs[0]))
        if not summary:
            summary = f"{scope}: {change_summary}"
        if not points:  # fallback: cite every evidence line (faithful)
            points = [
                ImpactPoint(text=f"{description} [{index + 1}]", citation=index + 1)
                for index, description in enumerate(evidence)
            ]
        return ImpactBrief(
            scope=scope,
            patch=patch,
            summary=summary,
            impact_points=points,
            evidence=evidence,
            requires_human=requires_human,
        )
