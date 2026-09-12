"""Graph-level tests — full run + conditional routing (fake repo, no DB)."""

from __future__ import annotations

from dataclasses import dataclass, field

from patchwatch.db.repositories import StoredDocument
from patchwatch.fixtures.snapshot import FIXTURE_SOURCE, load_version
from patchwatch.graph.graph import run_monitor
from patchwatch.graph.nodes import GraphDeps
from patchwatch.ingest.chunking import chunk_text
from tests.fakes import FakeFetcher, FakeRepository, stored


@dataclass
class SpyRepository(FakeRepository):
    """Fake repo that also records which nodes reached it (routing probe)."""

    queried_latest: int = 0
    queried_chunks: int = field(default=0)

    def latest(self, source: str, external_id: str) -> StoredDocument | None:  # type: ignore[override]
        self.queried_latest += 1
        return super().latest(source, external_id)

    def chunks_for_document(self, document_id: str) -> list[str]:  # type: ignore[override]
        self.queried_chunks += 1
        return super().chunks_for_document(document_id)


def test_full_run_indexes_v2_and_classifies_planted_edits() -> None:
    v1, v2 = load_version("26.6"), load_version("26.7")
    repo = SpyRepository(
        latest_by={(FIXTURE_SOURCE, v1.external_id): stored(v1)},
        chunks_by_doc={"stored-26.6": chunk_text(v1.content)},
    )
    deps = GraphDeps(fetcher=FakeFetcher([v1, v2]), repo=repo)

    result = run_monitor(deps, source=FIXTURE_SOURCE)

    assert result["reindexed"] is True
    # v1 unchanged (no delta), v2 changed and indexed.
    assert [d.document.version for d in result["deltas"]] == ["26.7"]
    assert repo.superseded  # v1 chunks were closed
    assert any(insert.get("version") == "26.7" for insert in repo.inserts)

    # Planted edits split across chunks: typo -> neutral, stat change -> uncertain.
    classes = [c.change_class for c in result["candidates"]]
    assert "uncertain" in classes and "neutral" in classes
    uncertain = [c for c in result["candidates"] if c.change_class == "uncertain"]
    neutral = [c for c in result["candidates"] if c.change_class == "neutral"]
    assert any("90/115/140/165/190" in c.new_text for c in uncertain)
    assert any("excels" in c.new_text for c in neutral)


def test_no_delta_run_ends_without_reindex() -> None:
    v1 = load_version("26.6")
    repo = SpyRepository(
        latest_by={(FIXTURE_SOURCE, v1.external_id): stored(v1)},
        chunks_by_doc={"stored-26.6": chunk_text(v1.content)},
    )
    deps = GraphDeps(fetcher=FakeFetcher([v1]), repo=repo)

    result = run_monitor(deps, source=FIXTURE_SOURCE)

    assert result["reindexed"] is False
    assert result["deltas"] == []
    assert result["candidates"] == []
    assert repo.queried_chunks == 0  # version_diff never reached
    assert not repo.superseded
    assert repo.inserts == []
