"""Gate machinery + eval suite tests (deterministic, frozen corpus)."""

from __future__ import annotations

import pytest

from patchwatch.eval.gate import (
    SuiteDelta,
    holm_correct,
    monte_carlo_null_calibration,
    monte_carlo_power,
    paired_bootstrap_pvalue,
    regression_gate,
)
from patchwatch.eval.suites import run_classification_suite, run_detection_suite


def test_paired_bootstrap_detects_real_regression() -> None:
    baseline = [0.9] * 50
    degraded = [0.75] * 50
    pvalue = paired_bootstrap_pvalue(baseline, degraded)
    assert pvalue < 0.05


def test_paired_bootstrap_null_is_noise() -> None:
    scores = [0.8, 0.9, 0.7, 0.85, 0.95]
    assert paired_bootstrap_pvalue(scores, scores) == 1.0  # identical → never regression


def test_holm_correction_ordering() -> None:
    adjusted = holm_correct({"a": 0.01, "b": 0.04, "c": 0.9})
    assert adjusted["a"] <= adjusted["b"] <= adjusted["c"] <= 1.0
    assert adjusted["a"] >= 0.01  # never shrinks a p-value
    assert adjusted["c"] == pytest.approx(0.9)  # last rank: multiplier 1


def test_gate_fires_on_planted_regression() -> None:
    suites = [SuiteDelta("classification", "accuracy", 0.85, 0.70, 50)]
    decision = regression_gate(
        suites,
        scores_by_suite={"classification": ([0.85] * 50, [0.70] * 50)},
    )
    assert decision.fired
    assert decision.verdicts["classification"] is True


def test_gate_quiet_on_unchanged_metrics() -> None:
    suites = [SuiteDelta("classification", "accuracy", 0.85, 0.85, 50)]
    decision = regression_gate(
        suites,
        scores_by_suite={"classification": ([0.85] * 50, [0.85] * 50)},
    )
    assert not decision.fired


def test_monte_carlo_null_calibration() -> None:
    rate = monte_carlo_null_calibration(iterations=100)
    assert rate <= 0.15  # false-positive rate near alpha


def test_monte_carlo_power_on_real_effect() -> None:
    rate = monte_carlo_power(effect=0.1, iterations=100)
    assert rate >= 0.95  # a real 10-point regression is caught


def test_detection_suite_on_frozen_corpus() -> None:
    report = run_detection_suite()
    assert report.precision >= 0.9
    assert report.recall >= 0.9
    assert not report.false_positives


def test_classification_suite_on_frozen_corpus() -> None:
    report = run_classification_suite()
    assert report.accuracy >= 0.85
    assert not report.wrong  # all 7 hand-labeled directions must match
