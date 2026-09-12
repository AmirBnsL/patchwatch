"""Live refresh: poll Data Dragon for a new patch and freeze it (the only live path).

Invariant #9: runtime never scrapes — the monitor reads frozen snapshots / the
DB. ``LiveRefresher`` is the single sanctioned touchpoint with the CDN.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from patchwatch.fixtures.manifest import CorpusManifest
from patchwatch.ingest.corpus_freeze import freeze_patch, update_manifest
from patchwatch.ingest.ddragon import DDragonClient


@dataclass
class RefreshResult:
    checked_version: str  # newest version on the CDN at check time
    frozen: bool  # True when a new patch was downloaded
    version: str | None  # the patch that was frozen (None = nothing new)


class LiveRefresher:
    """Freeze the newest CDN patch if it is not in the corpus yet."""

    def __init__(
        self, client: DDragonClient, base: Path, keep: int = 3, locale: str = "en_US"
    ) -> None:
        self._client = client
        self._base = base
        self._keep = keep
        self._locale = locale

    def _known_versions(self) -> list[str]:
        # Uncached read: the refresh path mutates the manifest.
        path = self._base / "manifest.json"
        manifest = CorpusManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
        return manifest.versions

    def refresh(self) -> RefreshResult:
        newest = self._client.latest_version()
        known = self._known_versions()
        if newest in known:
            return RefreshResult(checked_version=newest, frozen=False, version=None)
        print(f"new patch on the CDN: {newest} (corpus has {known}) — freezing")
        size, release_date = freeze_patch(self._client, newest, self._base, self._locale)
        print(f"  frozen {size / 1e6:.1f} MB (released {release_date})")
        update_manifest(newest, None, release_date, self._base, keep=self._keep)
        return RefreshResult(checked_version=newest, frozen=True, version=newest)
