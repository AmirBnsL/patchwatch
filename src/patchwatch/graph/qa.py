"""Patch-scoped QA pipeline: retrieve → version_mix_check → generate → guardrail.

Answers use ONLY chunks valid at the queried patch time; every claim must cite
a retrieved chunk ([1]-style references); cross-patch mixing is flagged. The
steps are linear (no loops/branches), so the runner drives them directly —
each step stays a testable pure-ish function.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.engine import Engine

from patchwatch.db.retrieval import MixReport, RetrievedChunk, retrieve, version_mix_report
from patchwatch.ingest.embeddings import EmbeddingProvider
from patchwatch.ingest.llm import LLMClient

_CITATION = re.compile(r"\[(\d+)\]")


@dataclass
class QADeps:
    """Injectable QA dependencies (mockable in tests)."""

    embedder: EmbeddingProvider
    engine: Engine
    llm: LLMClient
    k: int = 5


def build_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    """Deterministic grounded prompt: numbered contexts + citation instruction."""
    context_block = "\n\n".join(
        f"[{index + 1}] (patch {chunk.version}, {chunk.external_id})\n{chunk.content}"
        for index, chunk in enumerate(chunks)
    )
    return (
        "You answer questions about League of Legends patch data.\n"
        "Use ONLY the contexts below. Cite them inline as [1], [2], ... matching "
        "the context numbers. If the contexts do not contain the answer, say you "
        "don't know.\n\n"
        f"Contexts:\n{context_block}\n\nQuestion: {question}\nAnswer (with citations):"
    )


def grounding_guardrail(answer: str, n_chunks: int) -> tuple[list[int], bool]:
    """Deterministic grounding check.

    Returns (cited_refs, held_for_review). Held when the answer cites nothing,
    or cites a reference outside the retrieved window (hallucinated evidence).
    """
    refs = sorted({int(match) for match in _CITATION.findall(answer)})
    valid = [ref for ref in refs if 1 <= ref <= n_chunks]
    held = not refs or refs != valid
    return valid, held


@dataclass(frozen=True)
class QAReport:
    """Outcome of one patch-scoped question."""

    question: str
    answer: str
    citations: list[dict[str, Any]]  # [{ref, chunk_id, version, external_id}]
    held_for_review: bool
    version_mixing_flag: bool
    versions_used: list[str]


class QARunner:
    """Drives the linear QA steps with injected dependencies."""

    def __init__(self, deps: QADeps) -> None:
        self._deps = deps

    def answer(
        self, question: str, at_time: datetime, source_filter: str | None = None
    ) -> QAReport:
        # 1. retrieve — patch-pinned top-k
        [question_vector] = self._deps.embedder.embed([question])
        chunks = retrieve(
            self._deps.engine,
            question_vector,
            at_time=at_time,
            k=self._deps.k,
            source_filter=source_filter,
        )

        # 2. version_mix_check — flag cross-patch leakage
        mix: MixReport = version_mix_report(chunks)

        # 3. generate — grounded, citation-required
        prompt = build_prompt(question, chunks)
        llm_answer = self._deps.llm.complete(prompt)

        # 4. grounding_guardrail — every citation must point at a retrieved chunk
        refs, held = grounding_guardrail(llm_answer, len(chunks))
        citations = [
            {
                "ref": ref,
                "chunk_id": chunks[ref - 1].chunk_id,
                "version": chunks[ref - 1].version,
                "external_id": chunks[ref - 1].external_id,
            }
            for ref in refs
        ]

        return QAReport(
            question=question,
            answer=llm_answer,
            citations=citations,
            held_for_review=held,
            version_mixing_flag=mix.is_mixed,
            versions_used=sorted({chunk.version for chunk in chunks}),
        )
