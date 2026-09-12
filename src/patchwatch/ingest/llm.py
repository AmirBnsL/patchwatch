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
