"""Contradiction-node + suite tests (FakeLLM, deterministic)."""

from __future__ import annotations

from typing import Any

from patchwatch.eval.contradiction import run_contradiction_suite
from patchwatch.fixtures.snapshot import load_version
from patchwatch.graph.nodes import GraphDeps, contradict_detect
from patchwatch.graph.state import ChangeCandidate, DocDelta, MonitorState
from tests.fakes import FakeFetcher, FakeRepository, stored


class ScriptedLLM:
    """Returns canned answers by keyword."""

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else "consistent"


def _state(**overrides: Any) -> MonitorState:
    base: MonitorState = {
        "run_id": "run-1",
        "source": "fixture",
        "patch_from": None,
        "patch_to": None,
        "fetched": [],
        "deltas": [],
        "candidates": [],
        "contradictions": [],
        "briefs": [],
        "reindexed": False,
        "log": [],
    }
    base.update(overrides)
    return base


def test_contradiction_skipped_without_llm() -> None:
    v1, v2 = load_version("26.6"), load_version("26.7")
    repo = FakeRepository(latest_by={("fixture", v1.external_id): stored(v1)})
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=repo)  # no llm wired
    delta = DocDelta(document=v2, previous=stored(v1), changed=True)
    out = contradict_detect(_state(deltas=[delta]), deps)
    assert out["contradictions"] == []
    assert "skipped" in out["log"][0]


def test_contradiction_only_actionable_scopes() -> None:
    v1, v2 = load_version("26.6"), load_version("26.7")
    repo = FakeRepository(
        latest_by={("fixture", v1.external_id): stored(v1)},
        chunks_by_doc={"stored-26.6": ["guidance chunk"]},
    )
    llm = ScriptedLLM(["consistent"])
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=repo, llm=llm)
    delta = DocDelta(document=v2, previous=stored(v1), changed=True)
    # One actionable candidate (points at stored-26.6) + one neutral (different doc).
    candidates = [
        ChangeCandidate(
            document_id="stored-26.6",
            chunk_index=0,
            old_text="a",
            new_text="b",
            similarity=0.5,
            change_class="buff",
        ),
        ChangeCandidate(
            document_id="stored-other",
            chunk_index=0,
            old_text="a",
            new_text="b",
            similarity=0.5,
            change_class="neutral",
        ),
    ]
    out = contradict_detect(_state(deltas=[delta], candidates=candidates), deps)
    assert len(out["contradictions"]) == 1  # neutral scope never queried
    assert llm.prompts and "Version A" in llm.prompts[0]


def test_contradiction_verdict_parsing() -> None:
    v1, v2 = load_version("26.6"), load_version("26.7")
    repo = FakeRepository(
        latest_by={("fixture", v1.external_id): stored(v1)},
        chunks_by_doc={"stored-26.6": ["Max Q first guidance"]},
    )
    deps = GraphDeps(
        fetcher=FakeFetcher([]),
        repo=repo,
        llm=ScriptedLLM(['Contradiction."']),  # noisy LLM output
    )
    delta = DocDelta(document=v2, previous=stored(v1), changed=True)
    candidates = [
        ChangeCandidate(
            document_id="stored-26.6",
            chunk_index=0,
            old_text="a",
            new_text="b",
            similarity=0.5,
            change_class="nerf",
        )
    ]
    out = contradict_detect(_state(deltas=[delta], candidates=candidates), deps)
    assert out["contradictions"][0].contradiction is True  # parsed despite quotes/period


def test_contradiction_suite_counts_and_reports_wrong_ids() -> None:
    # A constant "contradiction" LLM matches the 4 True-label cases, misses the 6 False.
    constant_llm = ScriptedLLM(["contradiction"] * 20)
    correct, total, wrong = run_contradiction_suite(constant_llm)
    assert total == 10
    assert correct == 4
    assert set(wrong) == {
        "number-only",
        "typo-only",
        "frozen-bard",
        "frozen-ekko",
        "frozen-syndra",
        "frozen-cassiopeia",
    }


def test_contradiction_suite_perfect_llm_scores_full() -> None:
    from patchwatch.eval.contradiction import CONTRADICTION_CASES

    perfect_llm = ScriptedLLM(
        ["contradiction" if case.label else "consistent" for case in CONTRADICTION_CASES] * 2
    )
    correct, total, wrong = run_contradiction_suite(perfect_llm)
    assert (correct, total, wrong) == (10, 10, [])
