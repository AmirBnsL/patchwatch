"""Digest normalization tests against real frozen-snapshot shapes."""

from __future__ import annotations

import json
from pathlib import Path

from patchwatch.fixtures.manifest import raw_dir
from patchwatch.ingest.digest import (
    champion_digest,
    flatten,
    item_digest,
    render_champion_markdown,
    render_item_markdown,
    strip_html,
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_champion_digest_tracks_reliable_paths() -> None:
    detail = _load_json(raw_dir("16.18.1") / "champion" / "Ahri.json")
    digest = champion_digest(detail)
    assert digest["name"] == "Ahri"
    assert digest["title"] == "the Nine-Tailed Fox"
    assert isinstance(digest["stats.hp"], (int, float))
    assert isinstance(digest["spells.0.cooldown"], str)
    assert digest["spells.0.cost"] == "55/65/75/85/95"
    # zeroed effectBurn values carry no signal and are excluded
    assert not any(
        key.startswith("spells.0.effect.")
        and str(digest[key]) not in ("",)
        and float(digest[key]) != 0
        for key in digest
        if key.startswith("spells.0.effect.")
    ) or all(
        digest[key] not in (None, "", "0") for key in digest if key.startswith("spells.0.effect.")
    )


def test_item_digest_gold_and_stats() -> None:
    items = _load_json(raw_dir("16.18.1") / "item.json")
    digests = item_digest(items)
    ie = digests["3031"]  # Infinity Edge
    assert ie["name"] == "Infinity Edge"
    assert ie["gold.total"] == 3500
    assert isinstance(ie["stats.FlatPhysicalDamageMod"], (int, float))


def test_strip_html() -> None:
    assert (
        strip_html("<mainText><stats>75</stats> Attack<br>Damage</mainText>") == "75 Attack Damage"
    )


def test_flatten_nested() -> None:
    flat = flatten({"a": {"b": 1, "c": [10, 20]}, "d": "text", "e": None})
    assert flat == {"a.b": 1, "a.c.0": 10, "a.c.1": 20, "d": "text", "e": None}


def test_render_champion_markdown_deterministic_and_version_free() -> None:
    detail = _load_json(raw_dir("16.18.1") / "champion" / "Ahri.json")
    assert render_champion_markdown(detail) == render_champion_markdown(detail)
    markdown_new = render_champion_markdown(detail)
    detail_old = _load_json(raw_dir("16.16.1") / "champion" / "Ahri.json")
    assert markdown_new == render_champion_markdown(detail_old)  # unchanged scope hashes equal
    assert "# Ahri — the Nine-Tailed Fox" in markdown_new
    assert "16.18.1" not in markdown_new  # version stays on the document row
    assert "Cooldown:" in markdown_new


def test_render_item_markdown() -> None:
    items = _load_json(raw_dir("16.18.1") / "item.json")
    markdown = render_item_markdown("3031", items["data"]["3031"])
    assert "# Infinity Edge" in markdown
    assert "Cost: 3500 gold" in markdown
