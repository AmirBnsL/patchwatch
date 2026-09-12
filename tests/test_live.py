"""LiveRefresher tests — MockTransport + tmp corpus dir, no real network."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from patchwatch.fixtures.manifest import CorpusManifest, PatchInfo, write_manifest
from patchwatch.ingest.ddragon import DDragonClient
from patchwatch.ingest.live import LiveRefresher

NEWEST = "16.19.1"
KNOWN = ["16.18.1", "16.17.1", "16.16.1"]

AHCRI = {"data": {"Ahri": {"id": "Ahri", "name": "Ahri", "spells": [], "stats": {}}}}


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith("/api/versions.json"):
        return httpx.Response(200, json=[NEWEST, *KNOWN])
    if "/realms/" in url:
        return httpx.Response(200, json={"v": NEWEST})
    if url.endswith("/champion.json"):
        return httpx.Response(200, json=AHCRI)
    if url.endswith("/champion/Ahri.json"):
        return httpx.Response(200, json=AHCRI)
    if url.endswith("/item.json"):
        return httpx.Response(200, json={"data": {}})
    if "game-updates" in url:
        return httpx.Response(404)
    return httpx.Response(404)


def _corpus_dir(tmp_path: Path, with_manifest: bool = True) -> Path:
    base = tmp_path / "fixtures"
    (base / "ddragon" / "16.18.1").mkdir(parents=True, exist_ok=True)
    if with_manifest:
        write_manifest(
            CorpusManifest(
                built_at="2026-09-12T00:00:00Z",
                locale="en_US",
                patches=[PatchInfo(ddragon_version=v) for v in reversed(KNOWN)],
            ),
            base,
        )
    return base


def test_refresh_noop_when_newest_already_frozen(tmp_path: Path) -> None:
    base = _corpus_dir(tmp_path)
    refresher = LiveRefresher(DDragonClient(transport=httpx.MockTransport(_handler)), base)
    # CDN newest is 16.19.1; freeze it once → second refresh is a no-op.
    first = refresher.refresh()
    assert first.frozen is True and first.version == NEWEST
    second = LiveRefresher(DDragonClient(transport=httpx.MockTransport(_handler)), base).refresh()
    assert second.frozen is False and second.version is None


def test_refresh_freezes_new_patch_and_updates_manifest(tmp_path: Path) -> None:
    base = _corpus_dir(tmp_path)
    refresher = LiveRefresher(DDragonClient(transport=httpx.MockTransport(_handler)), base, keep=3)
    result = refresher.refresh()
    assert result.frozen and result.version == NEWEST
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    versions = [patch["ddragon_version"] for patch in manifest["patches"]]
    assert versions == ["16.17.1", "16.18.1", NEWEST]  # oldest-first, keep=3
    assert (base / "ddragon" / NEWEST / "champion" / "Ahri.json").exists()
    assert (base / "ddragon" / NEWEST / "item.json").exists()


def test_refresh_keeps_only_newest_n(tmp_path: Path) -> None:
    base = _corpus_dir(tmp_path)
    refresher = LiveRefresher(DDragonClient(transport=httpx.MockTransport(_handler)), base, keep=2)
    refresher.refresh()
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    versions = [patch["ddragon_version"] for patch in manifest["patches"]]
    assert versions == ["16.18.1", NEWEST]
