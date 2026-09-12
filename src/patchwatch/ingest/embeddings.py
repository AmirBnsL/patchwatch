"""Embedding providers — pinned model, offline fake for tests.

``EmbeddingProvider`` is the graph-facing contract; ``OpenAIEmbeddings`` is the
production implementation (pinned in Settings), ``HashEmbeddings`` a deterministic
bag-of-words fake that is similarity-meaningful without network/API keys.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

from openai import OpenAI

from patchwatch.config import get_settings


class EmbeddingProvider(Protocol):
    """Contract: one vector per text, in input order."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddings:
    """Pinned-model embeddings via the OpenAI API (batched)."""

    BATCH = 2048

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.embedding_model
        self.client = OpenAI(api_key=api_key or settings.openai_api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH):
            batch = texts[start : start + self.BATCH]
            response = self.client.embeddings.create(input=batch, model=self.model)
            vectors.extend([item.embedding for item in response.data])
        return vectors


class HashEmbeddings:
    """Deterministic hashed bag-of-words embeddings (tests / offline integration).

    Similar texts share tokens → similar vectors; no network, fully reproducible.
    """

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or get_settings().embedding_dim
        self._token = re.compile(r"[a-z0-9']+")

    def _index(self, token: str) -> int:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % self.dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in self._token.findall(text.lower()):
            vector[self._index(token)] += 1.0
        norm = math.sqrt(sum(component**2 for component in vector))
        if norm > 0:
            vector = [component / norm for component in vector]
        return vector


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
