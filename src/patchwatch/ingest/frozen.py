"""Frozen-corpus ingest: reads committed Data Dragon snapshots (no network).

``FrozenCorpusFetcher`` implements the graph's ``Fetcher`` contract for a single
patch version; ``FrozenDigestLoader`` supplies previous-version digests for the
numeric diff path.
"""

from __future__ import annotations

import json
from typing import Any

from patchwatch.fixtures.manifest import load_manifest, raw_dir
from patchwatch.fixtures.snapshot import Digest, SnapshotDocument
from patchwatch.ingest.digest import (
    champion_digest,
    item_digest,
    render_champion_markdown,
    render_item_markdown,
)
from patchwatch.ingest.normalize import content_hash

DDAGON_SOURCE = "ddragon"


def _load_json(path: Any) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object at {path}")
    return payload


class FrozenCorpusFetcher:
    """Fetcher over the frozen corpus for one patch version.

    Yields one ``SnapshotDocument`` per scope (every champion + every item),
    content = deterministic markdown render, digest = flat numeric substrate.
    """

    def __init__(self, version: str, locale: str = "en_US") -> None:
        self.version = version
        self._locale = locale
        manifest = load_manifest()
        patch = manifest.patch(version)
        if patch.released_at is None:
            raise ValueError(f"patch {version!r} has no release date in the manifest")
        self._published_at = patch.released_at

    def fetch(self, source: str) -> list[SnapshotDocument]:
        if source != DDAGON_SOURCE:
            raise ValueError(f"unsupported source: {source!r}")
        base = raw_dir(self.version)

        docs: list[SnapshotDocument] = []
        for champion_id in sorted(_load_json(base / "champion.json")["data"]):
            detail = _load_json(base / "champion" / f"{champion_id}.json")
            docs.append(
                SnapshotDocument(
                    source=DDAGON_SOURCE,
                    external_id=f"champion/{champion_id}",
                    title=f"{detail['data'][champion_id]['name']} (champion)",
                    version=self.version,
                    content=render_champion_markdown(detail, self.version),
                    published_at=self._published_at,
                    digest=champion_digest(detail),
                )
            )

        items_payload = _load_json(base / "item.json")
        for item_id, digest in sorted(item_digest(items_payload).items()):
            item = items_payload["data"][item_id]
            docs.append(
                SnapshotDocument(
                    source=DDAGON_SOURCE,
                    external_id=f"item/{item_id}",
                    title=f"{item.get('name', item_id)} (item)",
                    version=self.version,
                    content=render_item_markdown(item_id, item, self.version),
                    published_at=self._published_at,
                    digest=digest,
                )
            )
        return docs


class FrozenDigestLoader:
    """DigestLoader over the frozen corpus (previous-version digests)."""

    def load(self, source: str, external_id: str, version: str) -> Digest | None:
        if source != DDAGON_SOURCE:
            return None
        base = raw_dir(version)
        kind, _, key = external_id.partition("/")
        try:
            if kind == "champion":
                return champion_digest(_load_json(base / "champion" / f"{key}.json"))
            if kind == "item":
                return item_digest(_load_json(base / "item.json")).get(key)
        except FileNotFoundError:
            return None
        return None


def hash_frozen_scope(external_id: str, version: str, locale: str = "en_US") -> str:
    """Content hash of a frozen scope's rendered markdown (eval/test helper)."""
    fetcher = FrozenCorpusFetcher(version, locale)
    doc = next(d for d in fetcher.fetch(DDAGON_SOURCE) if d.external_id == external_id)
    return content_hash(doc.content)
