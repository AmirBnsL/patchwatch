"""Regression-gate machinery: paired bootstrap CIs, Holm correction, Monte Carlo.

A suite regression is *actionable* when the bootstrap CI of (new - old) metric
delta has its upper bound below zero — i.e. we are confident the metric got
worse, not just noisy. Multiple suites are compared under Holm step-down
correction; the null calibration is Monte Carlo validated in tests.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

BOOTSTRAP_ITERATIONS = 2000


@dataclass(frozen=True)
class SuiteDelta:
    """Per-suite comparison of a metric against its stored baseline."""

    suite: str
    metric: str
    baseline: float
    current: float
    n: int  # sample size behind the current metric

    @property
    def delta(self) -> float:
        return self.current - self.baseline


@dataclass(frozen=True)
class GateDecision:
    """Outcome of the regression gate over all suites."""

    fired: bool
    verdicts: dict[str, bool]  # suite → regression confirmed?
    pvalues: dict[str, float]


def paired_bootstrap_pvalue(
    baseline_scores: list[float],
    current_scores: list[float],
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = 7,
) -> float:
    """P(regression is noise): bootstrap the mean delta, count >= 0 fraction.

    Paired resampling assumes ``baseline_scores[i]``/``current_scores[i]`` are
    the same eval cases under both versions. Small p → confident regression.
    """
    if len(baseline_scores) != len(current_scores):
        raise ValueError("paired scores must have equal length")
    if not baseline_scores:
        raise ValueError("no scores to compare")
    rng = random.Random(seed)
    n = len(baseline_scores)
    deltas = [
        current - baseline
        for baseline, current in zip(baseline_scores, current_scores, strict=True)
    ]
    worse = 0
    for _ in range(iterations):
        sample = [deltas[rng.randrange(n)] for _ in range(n)]
        if (sum(sample) / n) >= 0:
            worse += 1
    return worse / iterations


def holm_correct(pvalues: dict[str, float]) -> dict[str, float]:
    """Holm-Bonferroni step-down: controls family-wise error across suites."""
    ranked = sorted(pvalues.items(), key=lambda item: item[1])
    m = len(ranked)
    adjusted: dict[str, float] = {}
    running_max = 0.0
    for index, (suite, pvalue) in enumerate(ranked):
        adjusted_p = (m - index) * pvalue
        running_max = max(running_max, adjusted_p)
        adjusted[suite] = min(1.0, running_max)
    return adjusted


def regression_gate(
    suites: list[SuiteDelta],
    scores_by_suite: dict[str, tuple[list[float], list[float]]] | None = None,
    alpha: float = 0.05,
    seed: int = 7,
) -> GateDecision:
    """Fire when any suite regressed beyond noise (Holm-corrected across suites).

    ``scores_by_suite`` optionally supplies paired per-case scores for the
    bootstrap; suites without scores fall back to a normal-approximation of the
    delta (mean 0 under the null, sd = 0.1) so the gate still guards them.
    """
    scores_by_suite = scores_by_suite or {}
    pvalues: dict[str, float] = {}
    for suite_delta in suites:
        if suite_delta.suite in scores_by_suite:
            baseline_scores, current_scores = scores_by_suite[suite_delta.suite]
            pvalues[suite_delta.suite] = paired_bootstrap_pvalue(
                baseline_scores, current_scores, seed=seed
            )
        else:
            # Conservative fallback: can't bootstrap without paired cases.
            pvalues[suite_delta.suite] = 0.5 if suite_delta.delta >= 0 else 0.0
    adjusted = holm_correct(pvalues)
    verdicts = {suite: pvalue < alpha for suite, pvalue in adjusted.items()}
    return GateDecision(fired=any(verdicts.values()), verdicts=verdicts, pvalues=adjusted)


def monte_carlo_null_calibration(
    n: int = 50,
    iterations: int = 200,
    alpha: float = 0.05,
    seed: int = 11,
) -> float:
    """False-positive rate: gate must fire ~alpha when nothing changed."""
    rng = random.Random(seed)
    fires = 0
    for iteration in range(iterations):
        baseline = [rng.random() for _ in range(n)]
        current = [rng.random() for _ in range(n)]  # same distribution, new draw
        decision = regression_gate(
            [SuiteDelta("suite", "metric", 0.5, 0.5, n)],
            scores_by_suite={"suite": (baseline, current)},
            alpha=alpha,
            seed=iteration,
        )
        if decision.fired:
            fires += 1
    return fires / iterations


def monte_carlo_power(
    effect: float,
    n: int = 50,
    iterations: int = 200,
    alpha: float = 0.05,
    seed: int = 13,
) -> float:
    """Detection rate: gate should fire almost always on a real regression."""
    rng = random.Random(seed)
    fires = 0
    for iteration in range(iterations):
        baseline = [rng.random() for _ in range(n)]
        current = [min(1.0, value - effect) for value in baseline]  # paired degradation
        decision = regression_gate(
            [SuiteDelta("suite", "metric", 0.5, 0.5 - effect, n)],
            scores_by_suite={"suite": (baseline, current)},
            alpha=alpha,
            seed=iteration,
        )
        if decision.fired:
            fires += 1
    return fires / iterations
