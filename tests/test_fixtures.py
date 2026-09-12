"""Fixture snapshot corpus — structure, planted edits, fetcher."""

from patchwatch.fixtures.snapshot import (
    EXTERNAL_ID,
    FIXTURE_SOURCE,
    PLANTED_EDITS,
    SnapshotFetcher,
    load_corpus,
    load_version,
)


def test_corpus_versions_and_identity() -> None:
    docs = load_corpus()
    assert [doc.version for doc in docs] == ["26.6", "26.7"]
    assert all(doc.source == FIXTURE_SOURCE and doc.external_id == EXTERNAL_ID for doc in docs)


def test_planted_edits_cover_both_kinds() -> None:
    assert {edit.kind for edit in PLANTED_EDITS} == {"cosmetic", "meaningful"}


def test_26_7_contains_planted_typo_fix() -> None:
    v266 = load_version("26.6").content
    v267 = load_version("26.7").content
    assert "excelss" in v266
    assert "excels" in v267
    assert "excelss" not in v267


def test_26_7_contains_planted_stat_change() -> None:
    v266 = load_version("26.6").content
    v267 = load_version("26.7").content
    assert "75/100/125/150/175" in v266
    assert "90/115/140/165/190" in v267


def test_fetcher_subset_and_all() -> None:
    assert [doc.version for doc in SnapshotFetcher({"26.6"}).fetch(FIXTURE_SOURCE)] == ["26.6"]
    assert [doc.version for doc in SnapshotFetcher().fetch(FIXTURE_SOURCE)] == ["26.6", "26.7"]


def test_fetcher_rejects_unknown_source() -> None:
    try:
        SnapshotFetcher().fetch("nope")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown source")
