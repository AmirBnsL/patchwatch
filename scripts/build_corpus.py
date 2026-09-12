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
import time
from datetime import UTC, datetime
from pathlib import Path

from patchwatch.fixtures.manifest import PatchInfo, raw_dir
from patchwatch.ingest.ddragon import DDragonClient, champion_ids
from patchwatch.ingest.prose import fetch_prose_snapshot

FIXTURES = Path(__file__).parent.parent / "src" / "patchwatch" / "fixtures"
REQUEST_DELAY = 0.15  # politeness between CDN requests
RETRIES = 3


def fetch_with_retry(client: DDragonClient, label: str, fn, path: Path) -> int:
    """Fetch ``fn()`` with retries; write JSON to ``path``; return byte size."""
    payload = None
    for attempt in range(1, RETRIES + 1):
        try:
            payload = fn()
            break
        except Exception as exc:  # noqa: BLE001 - build script: report and retry
            if attempt == RETRIES:
                raise RuntimeError(f"failed to fetch {label}: {exc}") from exc
            time.sleep(REQUEST_DELAY * attempt * 4)
    assert payload is not None  # loop guarantees assignment or raise
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


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
        for version in sorted(versions, key=all_versions.index):
            out = raw_dir(version)
            size = 0
            if not prose_only:
                size += fetch_with_retry(
                    client,
                    f"items {version}",
                    lambda v=version: client.items(v, locale),
                    out / "item.json",
                )
                print(f"  [{version}] item.json done")
                size += fetch_with_retry(
                    client,
                    f"champion summary {version}",
                    lambda v=version: client.champion_summary(v, locale),
                    out / "champion.json",
                )
                ids = champion_ids(json.loads((out / "champion.json").read_text(encoding="utf-8")))
                print(f"  [{version}] {len(ids)} champions to fetch")
                for index, champion_id in enumerate(ids, start=1):
                    size += fetch_with_retry(
                        client,
                        f"champion {champion_id} {version}",
                        lambda v=version, c=champion_id: client.champion_detail(v, c, locale),
                        out / "champion" / f"{champion_id}.json",
                    )
                    if index % 50 == 0:
                        print(f"  [{version}] {index}/{len(ids)}")
                    time.sleep(REQUEST_DELAY)
            else:
                size = sum(path.stat().st_size for path in out.rglob("*.json"))

            snapshot = fetch_prose_snapshot(version)
            prose_rel: str | None = None
            if snapshot is None:
                print(f"  [{version}] WARN: no notes page resolved — prose snapshot missing")
            else:
                prose_path = FIXTURES / "prose" / f"{version}.md"
                prose_path.parent.mkdir(parents=True, exist_ok=True)
                header = (
                    f"<!-- source: {snapshot.url} -->\n"
                    f"<!-- fetched: {datetime.now(UTC).isoformat()} -->\n\n"
                )
                prose_path.write_text(header + snapshot.markdown, encoding="utf-8")
                prose_rel = f"prose/{version}.md"
                print(f"  [{version}] prose: {prose_rel} ({snapshot.published_date})")

            patches.append(
                PatchInfo(
                    ddragon_version=version,
                    notes_url=snapshot.url if snapshot else None,
                    released_at=snapshot.published_date if snapshot else None,
                    prose_file=prose_rel,
                )
            )
            total += size

        manifest = {
            "built_at": datetime.now(UTC).isoformat(),
            "locale": locale,
            "patches": [patch.model_dump() for patch in patches],
        }
        (FIXTURES / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
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
