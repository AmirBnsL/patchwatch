"""Build the frozen LoL snapshot corpus (run once per corpus refresh).

Fetches the 3 newest Data Dragon patches (raw JSON: item + champion summary +
every champion detail file) and the matching official patch-notes pages
(extracted to markdown), writing everything under src/patchwatch/fixtures/ plus
a manifest. Committed to the repo as the load-bearing frozen corpus.

Usage:
    uv run scripts/build_corpus.py            # 3 newest patches
    uv run scripts/build_corpus.py --versions 16.17.1,16.18.1
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from patchwatch.fixtures.manifest import CorpusManifest, PatchInfo, write_manifest
from patchwatch.ingest.corpus_freeze import freeze_patch
from patchwatch.ingest.ddragon import DDragonClient

FIXTURES = Path(__file__).parent.parent / "src" / "patchwatch" / "fixtures"


def build(versions: list[str] | None, locale: str, prose_only: bool = False) -> None:
    client = DDragonClient()
    try:
        all_versions = client.versions()
        if versions is None:
            versions = all_versions[:3]
        unknown = [v for v in versions if v not in all_versions]
        if unknown:
            raise SystemExit(f"versions not on the CDN: {unknown}")
        print(f"building corpus for {versions} (locale={locale}, prose_only={prose_only})")

        patches: list[PatchInfo] = []
        total = 0
        selected = [v for v in all_versions if v in versions]  # CDN order: newest first
        for version in reversed(selected):  # write manifest oldest -> newest
            out = FIXTURES / "ddragon" / version
            size = 0
            if not prose_only:
                size, _ = freeze_patch(client, version, FIXTURES, locale)
            else:
                size = sum(path.stat().st_size for path in out.rglob("*.json"))
            print(f"  [{version}] raw JSON: {size / 1e6:.1f} MB")

            try:
                existing = CorpusManifest.model_validate(
                    json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
                )
                prior = next((p for p in existing.patches if p.ddragon_version == version), None)
            except FileNotFoundError:
                prior = None
            patches.append(
                prior
                or PatchInfo(
                    ddragon_version=version,
                    notes_url=None,
                    released_at=None,
                    prose_file=f"prose/{version}.md",
                )
            )
            total += size

        write_manifest(
            CorpusManifest(built_at=datetime.now(UTC).isoformat(), locale=locale, patches=patches),
            FIXTURES,
        )
        print(f"corpus built: {total / 1e6:.1f} MB raw JSON across {len(patches)} patches")
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--versions", help="Comma-separated ddragon versions (default: 3 newest)")
    parser.add_argument("--locale", default="en_US")
    parser.add_argument(
        "--prose-only", action="store_true", help="Re-fetch prose + manifest only (skip raw JSON)"
    )
    args = parser.parse_args()
    versions = [v.strip() for v in args.versions.split(",")] if args.versions else None
    build(versions, args.locale, prose_only=args.prose_only)


if __name__ == "__main__":
    sys.exit(main())
