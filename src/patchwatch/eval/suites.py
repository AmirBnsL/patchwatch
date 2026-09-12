"""Eval suites over the frozen corpus: detection P/R + classification accuracy.

Both suites are deterministic (no LLM) in Phase A′: the numeric diff IS the
detector, and direction-table labels are checked against hand-verified labels.
"""

from __future__ import annotations

from dataclasses import dataclass

from patchwatch.diff.numeric import NumericChange, numeric_diff
from patchwatch.eval.labels import PAIR, SCOPE_DIRECTIONS, UNCHANGED_SPOT_CHECKS
from patchwatch.graph.state import UNCERTAIN
from patchwatch.ingest.frozen import DDAGON_SOURCE, FrozenCorpusFetcher, FrozenDigestLoader


@dataclass(frozen=True)
class DetectionReport:
    true_positives: list[str]
    false_positives: list[str]
    false_negatives: list[str]

    @property
    def precision(self) -> float:
        detected = len(self.true_positives) + len(self.false_positives)
        return len(self.true_positives) / detected if detected else 1.0

    @property
    def recall(self) -> float:
        expected = len(self.true_positives) + len(self.false_negatives)
        return len(self.true_positives) / expected if expected else 1.0


@dataclass(frozen=True)
class ClassificationReport:
    correct: list[str]
    wrong: list[tuple[str, str, str]]  # (scope, expected, got)

    @property
    def accuracy(self) -> float:
        total = len(self.correct) + len(self.wrong)
        return len(self.correct) / total if total else 1.0


def aggregate_direction(changes: list[NumericChange]) -> str:
    """Scope-level direction: agreed field directions win, disagreement → uncertain."""
    directions = {change.direction for change in changes if change.field}
    if not directions:
        return UNCERTAIN
    if len(directions) == 1:
        return directions.pop()
    return UNCERTAIN


def run_detection_suite() -> DetectionReport:
    """Scope-level change detection on the frozen patch pair."""
    loader = FrozenDigestLoader()
    old_pair, new_pair = PAIR
    scopes = set(SCOPE_DIRECTIONS) | set(UNCHANGED_SPOT_CHECKS)
    true_positives, false_positives, false_negatives = [], [], []
    for scope in sorted(scopes):
        old_digest = loader.load(DDAGON_SOURCE, scope, old_pair)
        new_digest = loader.load(DDAGON_SOURCE, scope, new_pair)
        detected = (
            old_digest is not None
            and new_digest is not None
            and numeric_diff(old_digest, new_digest, scope) != []
        )
        expected = scope in SCOPE_DIRECTIONS
        if detected and expected:
            true_positives.append(scope)
        elif detected and not expected:
            false_positives.append(scope)
        elif not detected and expected:
            false_negatives.append(scope)
    return DetectionReport(true_positives, false_positives, false_negatives)


def run_classification_suite() -> ClassificationReport:
    """Direction accuracy on the hand-labeled scopes (numeric path only)."""
    loader = FrozenDigestLoader()
    old_pair, new_pair = PAIR
    correct: list[str] = []
    wrong: list[tuple[str, str, str]] = []
    fetcher = FrozenCorpusFetcher(new_pair)
    digests = {doc.external_id: doc.digest for doc in fetcher.fetch(DDAGON_SOURCE)}
    for scope, expected in SCOPE_DIRECTIONS.items():
        old_digest = loader.load(DDAGON_SOURCE, scope, old_pair)
        new_digest = digests.get(scope)
        if old_digest is None or new_digest is None:
            wrong.append((scope, expected, "missing-digest"))
            continue
        changes = numeric_diff(old_digest, new_digest, scope)
        got = aggregate_direction(changes)
        if got == expected:
            correct.append(scope)
        else:
            wrong.append((scope, expected, got))
    return ClassificationReport(correct, wrong)
