"""LLM client protocol + OpenAI implementation (pinned model, mockable)."""

from __future__ import annotations

from typing import Protocol

from openai import OpenAI

from patchwatch.config import get_settings


class LLMClient(Protocol):
    """Contract: one completion per prompt (mockable in tests)."""

    def complete(self, prompt: str) -> str: ...


class OpenAIChat:
    """Pinned-model chat completion via the OpenAI API."""

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.llm_model
        self.client = OpenAI(api_key=api_key or settings.openai_api_key)

    def complete(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,  # deterministic-ish for eval reproducibility
        )
        content = response.choices[0].message.content
        return content or ""


_ADJUDICATE_PROMPT = """Two versions of a game-document passage differ. Decide whether
the change alters gameplay guidance meaningfully, or is cosmetic (typo, formatting,
wording).

Version A:
{old}

Version B:
{new}

Answer with exactly one word: "neutral" (cosmetic/no guidance change) or "uncertain"
(guidance meaningfully changed)."""


class OpenAIAdjudicator:
    """LLM-backed adjudication for borderline prose changes (calibrated in evals)."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def adjudicate(self, old_text: str, new_text: str) -> str:
        answer = self._llm.complete(_ADJUDICATE_PROMPT.format(old=old_text, new=new_text))
        word = answer.strip().lower().strip('."')
        return word if word in ("neutral", "uncertain") else "uncertain"  # fail safe
