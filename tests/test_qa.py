"""QA pipeline tests: guardrail/prompt units + full run against real Postgres."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from patchwatch.db.connection import get_engine
from patchwatch.db.repositories import ChunkRecord, DocumentRepository
from patchwatch.graph.qa import QADeps, QARunner, build_prompt, grounding_guardrail
from patchwatch.ingest.embeddings import HashEmbeddings
from patchwatch.ingest.llm import LLMClient

pytestmark = pytest.mark.integration

T_V1 = datetime(2026, 1, 15, tzinfo=UTC)
T_V2 = datetime(2026, 3, 20, tzinfo=UTC)
NOW = datetime(2026, 9, 12, tzinfo=UTC)
EMBEDDER = HashEmbeddings(dim=1536)

V1_CONTENT = "Ahri Q orb of deception magic damage outbound 75 true damage return"


class FakeLLM(LLMClient):
    """Deterministic QA LLM: echoes a grounded answer citing [1]."""

    def __init__(self, template: str = "Q deals 75 damage [1].") -> None:
        self.template = template
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.template


@pytest.fixture
def qa_ext() -> Iterator[str]:
    ext = f"it-{uuid4().hex[:10]}"
    repo = DocumentRepository(get_engine())
    doc_v1 = repo.insert_document_version(
        source="fixture",
        external_id=ext,
        title="t",
        version="26.6",
        content_hash="h1",
        fetched_at=T_V1,
    )
    repo.insert_chunks(
        doc_v1,
        [ChunkRecord(chunk_index=0, content=V1_CONTENT)],
        T_V1,
        EMBEDDER.embed([V1_CONTENT]),
    )
    doc_v2 = repo.insert_document_version(
        source="fixture",
        external_id=ext,
        title="t",
        version="26.7",
        content_hash="h2",
        fetched_at=T_V2,
    )
    repo.insert_chunks(
        doc_v2,
        [ChunkRecord(chunk_index=0, content=V1_CONTENT + " raised 90")],
        T_V2,
        EMBEDDER.embed([V1_CONTENT + " raised 90"]),
    )
    repo.supersede_document(doc_v1, T_V2)
    yield ext
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "DELETE FROM chunks WHERE document_id IN "
                "(SELECT id FROM documents WHERE external_id = :e)"
            ),
            {"e": ext},
        )
        conn.execute(text("DELETE FROM documents WHERE external_id = :e"), {"e": ext})


# --- unit: guardrail + prompt ---


def test_guardrail_accepts_cited_answer() -> None:
    refs, held = grounding_guardrail("Q deals 75 damage [1] and [2].", 2)
    assert refs == [1, 2]
    assert not held


def test_guardrail_holds_uncited_answer() -> None:
    _, held = grounding_guardrail("Q deals 75 damage, trust me.", 2)
    assert held


def test_guardrail_halls_hallucinated_refs() -> None:
    refs, held = grounding_guardrail("Q deals 75 damage [1] [5].", 2)
    assert refs == [1]  # only in-window refs kept
    assert held  # but the answer is held (hallucinated [5])


def test_prompt_numbers_contexts_and_demands_citations() -> None:
    from patchwatch.db.retrieval import RetrievedChunk

    chunks = [
        RetrievedChunk(
            chunk_id="c1",
            document_id="d1",
            external_id="champion/Ahri",
            source="ddragon",
            version="26.6",
            valid_from=T_V1,
            is_current=True,
            content="stats",
            distance=0.1,
        )
    ]
    prompt = build_prompt("what is q damage?", chunks)
    assert "[1] (patch 26.6, champion/Ahri)" in prompt
    assert "Cite them inline" in prompt


# --- integration: full QA run ---


def test_qa_answers_patch_scoped(qa_ext: str) -> None:
    llm = FakeLLM()
    runner = QARunner(QADeps(embedder=EMBEDDER, engine=get_engine(), llm=llm, k=3))

    # Question at v2 time → retrieved context is the 26.7 chunk.
    report = runner.answer("what is ahri q damage?", at_time=NOW, source_filter="fixture")
    assert report.versions_used == ["26.7"]
    assert not report.version_mixing_flag
    assert report.citations and report.citations[0]["version"] == "26.7"
    assert not report.held_for_review
    assert "26.7" in llm.prompts[0]  # context pins the retrieved patch version
    assert "26.6" not in llm.prompts[0]  # past version never leaks into the prompt


def test_qa_guardrail_holds_hallucinating_llm(qa_ext: str) -> None:
    runner = QARunner(
        QADeps(
            embedder=EMBEDDER,
            engine=get_engine(),
            llm=FakeLLM(template="Cite [1] and [7]."),
            k=3,
        )
    )
    report = runner.answer("what is ahri q damage?", at_time=NOW, source_filter="fixture")
    assert report.held_for_review  # [7] not retrieved
    assert [c["ref"] for c in report.citations] == [1]
