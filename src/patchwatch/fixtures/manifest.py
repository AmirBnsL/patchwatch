"""Frozen-corpus manifest — which patches are frozen and where their prose lives."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class PatchInfo(BaseModel):
    """One frozen patch snapshot."""

    ddragon_version: str
    notes_url: str | None = None
    released_at: str | None = None  # ISO date, from the notes page
    prose_file: str | None = None  # relative to fixtures/


class CorpusManifest(BaseModel):
    """Manifest of the frozen snapshot corpus."""

    built_at: str
    locale: str = "en_US"
    patches: list[PatchInfo]

    @property
    def versions(self) -> list[str]:
        """Frozen ddragon versions, oldest → newest."""
        return [patch.ddragon_version for patch in self.patches]

    def patch(self, version: str) -> PatchInfo:
        for info in self.patches:
            if info.ddragon_version == version:
                return info
        raise KeyError(f"patch {version!r} not in corpus")


FIXTURES_DIR = Path(__file__).parent


def raw_dir(version: str) -> Path:
    """Directory holding raw Data Dragon JSON for one patch."""
    return FIXTURES_DIR / "ddragon" / version


def prose_path(version: str) -> Path:
    """Path of the frozen prose markdown for one patch."""
    return FIXTURES_DIR / "prose" / f"{version}.md"


@lru_cache
def load_manifest() -> CorpusManifest:
    """Load (and cache) the frozen-corpus manifest."""
    manifest_path = FIXTURES_DIR / "manifest.json"
    data: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    return CorpusManifest.model_validate(data)
