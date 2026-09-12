"""B2 semantic-layer tests: embed-on-reindex + prose-aware classification."""

from __future__ import annotations

from typing import Any

from patchwatch.fixtures.snapshot import load_version
from patchwatch.graph.nodes import GraphDeps, change_class, reindex
from patchwatch.graph.state import ChangeCandidate, DocDelta, MonitorState
from patchwatch.ingest.embeddings import HashEmbeddings
from tests.fakes import FakeAdjudicator, FakeFetcher, FakeRepository


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


# --- reindex embeddings ---


def test_reindex_embeds_chunks_when_provider_wired() -> None:
    doc = load_version("26.6")
    repo = FakeRepository()
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=repo, embedder=HashEmbeddings(dim=64))
    delta = DocDelta(document=doc, previous=None, changed=True)
    reindex(_state(deltas=[delta]), deps)
    document_id, chunks, valid_from, embeddings = repo.chunk_inserts[0]
    assert embeddings is not None
    assert len(embeddings) == len(chunks)
    assert all(len(vector) == 64 for vector in embeddings)


def test_reindex_without_embedder_stores_null_embeddings() -> None:
    doc = load_version("26.6")
    repo = FakeRepository()
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=repo)
    delta = DocDelta(document=doc, previous=None, changed=True)
    reindex(_state(deltas=[delta]), deps)
    assert repo.chunk_inserts[0][3] is None


# --- prose-aware classification ---


def test_prose_high_similarity_neutral_without_llm() -> None:
    # Bag-of-words: punctuation/case-only drift → identical token bag → cos 1.0.
    candidate = ChangeCandidate(
        document_id="d1",
        chunk_index=0,
        old_text="Ahri is a mobile mage who excels at picking fights, and disengaging",
        new_text="ahri is a mobile mage who excels at picking fights and disengaging",
        similarity=0.9,
    )
    deps = GraphDeps(
        fetcher=FakeFetcher([]), repo=FakeRepository(), embedder=HashEmbeddings(dim=128)
    )
    out = change_class(_state(candidates=[candidate]), deps)
    assert out["candidates"][0].change_class == "neutral"


def test_prose_low_similarity_uncertain() -> None:
    candidate = ChangeCandidate(
        document_id="d1",
        chunk_index=0,
        old_text="Q base damage stands at 75 with no changes scheduled this patch",
        new_text="Tahm Kench competitive ruling and tournament eligibility update",
        similarity=0.3,
    )
    deps = GraphDeps(
        fetcher=FakeFetcher([]), repo=FakeRepository(), embedder=HashEmbeddings(dim=128)
    )
    out = change_class(_state(candidates=[candidate]), deps)
    assert out["candidates"][0].change_class == "uncertain"


def test_prose_borderline_uses_adjudicator() -> None:
    # Construct a borderline pair: shared topic, some token drift (cos ~0.95).
    old_text = "ahri q orb of deception magic damage true damage return pass cooldown"
    new_text = "ahri q orb of deception magic damage true damage return pass cooldown rank"
    candidate = ChangeCandidate(
        document_id="d1",
        chunk_index=0,
        old_text=old_text,
        new_text=new_text,
        similarity=0.9,
    )
    adjudicator = FakeAdjudicator(verdict="neutral")
    deps = GraphDeps(
        fetcher=FakeFetcher([]),
        repo=FakeRepository(),
        embedder=HashEmbeddings(dim=2048),
        adjudicator=adjudicator,
    )
    out = change_class(_state(candidates=[candidate]), deps)
    assert out["candidates"][0].change_class == "neutral"
    assert adjudicator.calls == [(old_text, new_text)]


def test_prose_difflib_fallback_without_embedder() -> None:
    candidate = ChangeCandidate(
        document_id="d1",
        chunk_index=0,
        old_text="Ahri is a mobile mage who excelss at picking fights",
        new_text="Ahri is a mobile mage who excels at picking fights",
        similarity=0.98,
    )
    deps = GraphDeps(fetcher=FakeFetcher([]), repo=FakeRepository())
    out = change_class(_state(candidates=[candidate]), deps)
    assert out["candidates"][0].change_class == "neutral"


def test_numeric_direction_still_wins_with_embedder_wired() -> None:
    candidate = ChangeCandidate(
        document_id="d1",
        chunk_index=0,
        old_text="34",
        new_text="32",
        similarity=0.0,
        kind="numeric",
        field="stats.armor",
        direction="nerf",
    )
    deps = GraphDeps(
        fetcher=FakeFetcher([]), repo=FakeRepository(), embedder=HashEmbeddings(dim=64)
    )
    out = change_class(_state(candidates=[candidate]), deps)
    assert out["candidates"][0].change_class == "nerf"
