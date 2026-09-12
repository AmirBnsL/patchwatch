"""Eval gate: current suite metrics vs committed baselines (CI exit code = verdict)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from patchwatch.eval.gate import SuiteDelta, regression_gate
from patchwatch.eval.suites import run_classification_suite, run_detection_suite

BASELINES = Path(__file__).parent.parent / "eval_baselines.json"


def current_metrics() -> dict[str, float]:
    detection = run_detection_suite()
    classification = run_classification_suite()
    return {
        "detection_precision": detection.precision,
        "detection_recall": detection.recall,
        "classification_accuracy": classification.accuracy,
    }


def check(baselines_path: Path) -> bool:
    data = json.loads(baselines_path.read_text(encoding="utf-8"))
    baselines: dict[str, float] = data["baselines"]
    metrics = current_metrics()

    suites = [
        SuiteDelta(suite=name, metric=name, baseline=baselines[name], current=metrics[name], n=10)
        for name in baselines
        if name in metrics
    ]
    decision = regression_gate(suites)  # no paired scores → delta-sign fallback

    print(f"{'suite':<28}{'baseline':>10}{'current':>10}{'verdict':>12}")
    for delta in suites:
        verdict = "REGRESSED" if decision.verdicts[delta.suite] else "ok"
        print(f"{delta.suite:<28}{delta.baseline:>10.4f}{delta.current:>10.4f}{verdict:>12}")

    if decision.fired:
        print("EVAL GATE: FAILED — regression detected (Holm-corrected)")
        return False
    print("EVAL GATE: PASSED")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baselines", default=str(BASELINES))
    args = parser.parse_args()
    return 0 if check(Path(args.baselines)) else 1


if __name__ == "__main__":
    sys.exit(main())
