"""Corpus freezing as a library — shared by the build script and the live refresher."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from patchwatch.fixtures.manifest import CorpusManifest, PatchInfo, write_manifest
from patchwatch.ingest.ddragon import DDragonClient, champion_ids
from patchwatch.ingest.prose import fetch_prose_snapshot

REQUEST_DELAY = 0.15  # politeness between CDN requests
RETRIES = 3


def fetch_with_retry(client: DDragonClient, label: str, fn: Callable[[], Any], path: Path) -> int:
    """Fetch ``fn()`` with retries; write JSON to ``path``; return byte size."""
    payload = None
    for attempt in range(1, RETRIES + 1):
        try:
            payload = fn()
            break
        except Exception as exc:  # noqa: BLE001 - build tool: report and retry
            if attempt == RETRIES:
                raise RuntimeError(f"failed to fetch {label}: {exc}") from exc
            time.sleep(REQUEST_DELAY * attempt * 4)
    assert payload is not None  # loop guarantees assignment or raise
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def freeze_patch(
    client: DDragonClient, version: str, base: Path, locale: str = "en_US"
) -> tuple[int, str | None]:
    """Freeze one patch's raw JSON + prose into ``base``; returns (bytes, release_date)."""
    out = base / "ddragon" / version
    size = fetch_with_retry(
        client, f"items {version}", lambda: client.items(version, locale), out / "item.json"
    )
    size += fetch_with_retry(
        client,
        f"champion summary {version}",
        lambda: client.champion_summary(version, locale),
        out / "champion.json",
    )
    ids = champion_ids(json.loads((out / "champion.json").read_text(encoding="utf-8")))

    for index, champion_id in enumerate(ids, start=1):

        def detail_fn(champion_id: str = champion_id) -> dict[str, Any]:
            return client.champion_detail(version, champion_id, locale)

        size += fetch_with_retry(
            client,
            f"champion {champion_id} {version}",
            detail_fn,
            out / "champion" / f"{champion_id}.json",
        )
        if index % 50 == 0:
            print(f"  [{version}] {index}/{len(ids)}")
        time.sleep(REQUEST_DELAY)

    snapshot = fetch_prose_snapshot(version)
    release_date: str | None = None
    prose_rel: str | None = None
    if snapshot is None:
        print(f"  [{version}] WARN: no notes page resolved — prose snapshot missing")
    else:
        prose_path = base / "prose" / f"{version}.md"
        prose_path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"<!-- source: {snapshot.url} -->\n"
            f"<!-- fetched: {datetime.now(UTC).isoformat()} -->\n\n"
        )
        prose_path.write_text(header + snapshot.markdown, encoding="utf-8")
        prose_rel = f"prose/{version}.md"
        release_date = snapshot.published_date
        print(f"  [{version}] prose: {prose_rel} ({snapshot.published_date})")
    return size, release_date


def update_manifest(
    version: str, notes_url: str | None, released_at: str | None, base: Path, keep: int = 3
) -> CorpusManifest:
    """Append a frozen patch (oldest-first), keeping the newest ``keep`` patches."""
    try:
        existing = (base / "manifest.json").read_text(encoding="utf-8")
        manifest = CorpusManifest.model_validate(json.loads(existing))
    except FileNotFoundError:
        manifest = CorpusManifest(
            built_at=datetime.now(UTC).isoformat(), locale="en_US", patches=[]
        )
    patches = [patch for patch in manifest.patches if patch.ddragon_version != version]
    patches.append(PatchInfo(ddragon_version=version, notes_url=notes_url, released_at=released_at))
    updated = CorpusManifest(
        built_at=manifest.built_at,
        locale=manifest.locale,
        patches=patches[-keep:],  # manifest is oldest-first; keep newest N
    )
    write_manifest(updated, base)
    return updated


def total_frozen_bytes(base: Path, versions: list[str]) -> int:
    return sum(
        path.stat().st_size
        for version in versions
        for path in (base / "ddragon" / version).rglob("*.json")
    )
