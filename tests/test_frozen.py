"""Frozen-corpus fetcher/loader tests — disk only, no network."""

from __future__ import annotations

import pytest

from patchwatch.diff.numeric import numeric_diff
from patchwatch.fixtures.manifest import load_manifest
from patchwatch.ingest.frozen import DDAGON_SOURCE, FrozenCorpusFetcher, FrozenDigestLoader


def test_fetcher_covers_all_scopes() -> None:
    docs = FrozenCorpusFetcher("16.18.1").fetch(DDAGON_SOURCE)
    external_ids = {doc.external_id for doc in docs}
    assert "champion/Ahri" in external_ids
    assert "item/3031" in external_ids
    assert len([d for d in docs if d.external_id.startswith("champion/")]) == 173
    assert all(doc.source == DDAGON_SOURCE for doc in docs)


def test_fetcher_uses_manifest_release_date() -> None:
    manifest = load_manifest()
    docs = FrozenCorpusFetcher("16.18.1").fetch(DDAGON_SOURCE)
    assert all(doc.published_at == manifest.patch("16.18.1").released_at for doc in docs)


def test_fetcher_content_is_rendered_markdown_with_digest() -> None:
    doc = next(
        d
        for d in FrozenCorpusFetcher("16.18.1").fetch(DDAGON_SOURCE)
        if d.external_id == "champion/Ahri"
    )
    assert doc.content.startswith("# Ahri — the Nine-Tailed Fox (16.18.1)")
    assert doc.digest is not None and doc.digest["name"] == "Ahri"


def test_fetcher_rejects_unknown_source() -> None:
    with pytest.raises(ValueError):
        FrozenCorpusFetcher("16.18.1").fetch("nope")


def test_digest_loader_round_trip() -> None:
    loader = FrozenDigestLoader()
    digest = loader.load(DDAGON_SOURCE, "champion/Ahri", "16.18.1")
    assert digest is not None and digest["name"] == "Ahri"
    assert loader.load(DDAGON_SOURCE, "item/3031", "16.18.1") is not None
    assert loader.load(DDAGON_SOURCE, "champion/Ahri", "9.9.9") is None  # not frozen
    assert loader.load("fixture", "champion/Ahri", "16.18.1") is None  # wrong source


def test_real_frozen_patches_produce_numeric_changes() -> None:
    """The frozen 16.17.1 -> 16.18.1 pair: Bard armor 34->32 is a real nerf."""
    loader = FrozenDigestLoader()
    old = loader.load(DDAGON_SOURCE, "champion/Bard", "16.17.1")
    new = loader.load(DDAGON_SOURCE, "champion/Bard", "16.18.1")
    assert old is not None and new is not None
    changes = numeric_diff(old, new, "champion/Bard")
    armor = next(c for c in changes if c.field == "stats.armor")
    assert armor.old == 34 and armor.new == 32
    assert armor.direction == "nerf"


def test_frozen_scopes_changed_between_patches() -> None:
    """Multiple scopes changed across the frozen window (sanity for eval design)."""
    fetcher_old = FrozenCorpusFetcher("16.17.1")
    fetcher_new = FrozenCorpusFetcher("16.18.1")
    old = {doc.external_id: doc.digest for doc in fetcher_old.fetch(DDAGON_SOURCE)}
    new = {doc.external_id: doc.digest for doc in fetcher_new.fetch(DDAGON_SOURCE)}
    changed = [scope for scope in old if old[scope] != new.get(scope)]
    assert len(changed) >= 5
