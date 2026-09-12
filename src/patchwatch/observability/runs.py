"""Run persistence + cost/latency recording (runs / detected_changes / briefings)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from patchwatch.db.repositories import Repository
from patchwatch.graph.state import ChangeCandidate, DocDelta


@dataclass
class RunTimer:
    """Latency + cost capture for one monitor run."""

    started: float = 0.0

    def start(self) -> None:
        self.started = time.perf_counter()

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)


class RunRecorder:
    """Persists run/change/briefing rows — the observability DB surface."""

    def __init__(self, repo: Repository) -> None:
        # Repository protocol covers docs/chunks; run state uses the same engine
        # via the concrete DocumentRepository API (see methods below).
        self._repo = repo

    def start_run(self, run_id: str, trace_id: str) -> None:
        self._repo.insert_run(run_id, datetime.now(UTC), trace_id)

    def record_results(
        self,
        run_id: str,
        state: dict[str, Any],
        latency_ms: int,
        token_cost_cents: float = 0.0,
        status: str | None = None,
    ) -> None:
        """Persist detected changes + briefings, then close the run row."""
        if status is None:
            status = _final_status(state)
        for brief in state.get("briefs", []):
            self._repo.insert_briefing(
                run_id=run_id,
                change_id=None,
                summary=brief.summary,
                impact_points=[
                    {"text": p.text, "citation": p.citation} for p in brief.impact_points
                ],
                grounded_in=brief.grounded_in,
                requires_human=brief.requires_human,
            )
        for info in _changes_by_scope(state).values():
            self._repo.insert_change(
                run_id=run_id,
                document_id=info["document_id"],
                old_version=info["old_version"],
                new_version=info["new_version"],
                diff_preview=info["diff_preview"],
                change_class=info["change_class"],
                severity=info["severity"],
                contradiction=info["contradiction"],
                status="pending" if info["requires_human"] else "auto",
            )
        self._repo.finish_run(
            run_id=run_id,
            finished_at=datetime.now(UTC),
            status=status,
            token_cost_cents=token_cost_cents,
            latency_ms=latency_ms,
        )


def _final_status(state: dict[str, Any]) -> str:
    if state.get("reindexed"):
        return "succeeded"
    if state.get("approval") == "rejected":
        return "rejected"
    return "completed"


def _changes_by_scope(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Group candidates by scope → one detected_changes row per scope."""
    from patchwatch.graph.nodes import requires_human_for, severity_for

    deltas_by_key: dict[str, DocDelta] = {
        (delta.previous.id if delta.previous else ""): delta for delta in state.get("deltas", [])
    }
    grouped: dict[str, list[ChangeCandidate]] = {}
    for candidate in state.get("candidates", []):
        grouped.setdefault(candidate.document_id, []).append(candidate)

    rows: dict[str, dict[str, Any]] = {}
    for doc_key, candidates in grouped.items():
        delta = deltas_by_key.get(doc_key)
        actionable = [c for c in candidates if c.change_class != "neutral"]
        if not delta or not actionable:
            continue
        severity = severity_for(actionable)
        rows[doc_key] = {
            "document_id": delta.previous.id if delta.previous else None,
            "old_version": delta.previous.version if delta.previous else None,
            "new_version": delta.document.version,
            "diff_preview": "; ".join(
                f"{c.field or f'chunk[{c.chunk_index}]'}: {c.old_text} -> {c.new_text}"
                for c in actionable[:5]
            ),
            "change_class": actionable[0].change_class,
            "severity": severity,
            "contradiction": any(
                verdict.contradiction
                for verdict in state.get("contradictions", [])
                if verdict.scope == (delta.document.external_id or "")
            ),
            "requires_human": requires_human_for(actionable, severity),
        }
    return rows


def new_trace_id() -> str:
    return uuid4().hex
