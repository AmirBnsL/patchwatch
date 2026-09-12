"""Deterministic digests of Data Dragon payloads — the numeric-diff substrate.

Known data-quality caveat (documented by Riot's ecosystem): spell ``effectBurn``
values are often zeroed/stale. The digest therefore tracks the reliable numeric
paths (base stats, cooldown/cost/range burns, item gold/stats) and treats spell
damage numbers as prose-layer signal.

Digests are *flat*: dotted field path → scalar. That makes the diff generic and
the direction rules path-based.
"""

from __future__ import annotations

import re
from typing import Any

Strip = str  # alias for readability in signatures

_TAG = re.compile(r"<[^>]+>")
_RANKS = re.compile(r"^\s*-?\d+(\.\d+)?(\s*/\s*-?\d+(\.\d+)?)*\s*$")


def strip_html(text: str) -> str:
    """Remove HTML tags and normalize whitespace (item descriptions are HTML)."""
    return " ".join(_TAG.sub(" ", text).split()).strip()


def _scalar(value: Any) -> str | float | int | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return None  # non-scalar: handled structurally elsewhere


def flatten(
    payload: dict[str, Any], prefix: str = ""
) -> dict[str, str | float | int | bool | None]:
    """Flatten nested dicts/lists into ``dotted.path`` → scalar."""
    flat: dict[str, str | float | int | bool | None] = {}
    for key, value in payload.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(flatten(value, path))
        elif isinstance(value, list):
            for index, element in enumerate(value):
                element_path = f"{path}.{index}"
                if isinstance(element, dict):
                    flat.update(flatten(element, element_path))
                elif (scalar := _scalar(element)) is not None or element is None:
                    flat[element_path] = scalar
        else:
            flat[path] = _scalar(value)
    return flat


def _is_ranked(value: Any) -> bool:
    return isinstance(value, str) and bool(_RANKS.match(value)) and "/" in value


def _numeric(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def champion_digest(detail: dict[str, Any]) -> dict[str, str | float | int | bool | None]:
    """Flat digest for one champion detail payload (``champion/{id}.json``)."""
    entry = next(iter(detail["data"].values()))
    digest: dict[str, str | float | int | bool | None] = {
        "name": entry.get("name"),
        "title": entry.get("title"),
        "partype": entry.get("partype"),
        "tags": ",".join(entry.get("tags", [])),
    }
    for stat, value in entry.get("stats", {}).items():
        digest[f"stats.{stat}"] = _scalar(value)
    for index, spell in enumerate(entry.get("spells", [])):
        prefix = f"spells.{index}"
        digest[f"{prefix}.name"] = spell.get("name")
        digest[f"{prefix}.cooldown"] = spell.get("cooldownBurn")
        digest[f"{prefix}.cost"] = spell.get("costBurn")
        digest[f"{prefix}.range"] = spell.get("rangeBurn")
        for effect_index, effect in enumerate(spell.get("effectBurn", []) or []):
            if effect in (None, "", "0"):
                continue  # zeroed/stale values carry no signal
            digest[f"{prefix}.effect.{effect_index}"] = effect
    passive = entry.get("passive", {})
    digest["passive.name"] = passive.get("name")
    return digest


def item_digest(
    items_payload: dict[str, Any],
) -> dict[str, dict[str, str | float | int | bool | None]]:
    """Per-item flat digests from an ``item.json`` payload: ``item_id → digest``."""
    digests: dict[str, dict[str, str | float | int | bool | None]] = {}
    for item_id, item in items_payload.get("data", {}).items():
        if not isinstance(item, dict):
            continue
        digest: dict[str, str | float | int | bool | None] = {
            "name": item.get("name"),
            "plaintext": item.get("plaintext"),
        }
        for gold_key, gold_value in item.get("gold", {}).items():
            digest[f"gold.{gold_key}"] = _scalar(gold_value)
        for stat, value in item.get("stats", {}).items():
            digest[f"stats.{stat}"] = _scalar(value)
        digests[str(item_id)] = digest
    return digests


def render_champion_markdown(detail: dict[str, Any], version: str) -> str:
    """Deterministic markdown rendering of a champion — the chunk text for indexing."""
    entry = next(iter(detail["data"].values()))
    lines = [f"# {entry['name']} — {entry['title']} ({version})", ""]
    if entry.get("partype"):
        lines += [f"Resource: {entry['partype']}", ""]
    lines += ["## Stats", ""]
    for stat in sorted(entry.get("stats", {})):
        lines.append(f"- {stat}: {entry['stats'][stat]}")
    lines += ["", "## Abilities", ""]
    passive = entry.get("passive", {})
    lines.append(f"### Passive — {passive.get('name', '')}")
    lines.append(strip_html(passive.get("description", "")))
    lines.append("")
    for spell in entry.get("spells", []):
        lines.append(f"### {spell.get('id')} — {spell.get('name')}")
        lines.append(strip_html(spell.get("description", "")))
        lines.append(
            f"Cooldown: {spell.get('cooldownBurn', 'N/A')} | "
            f"Cost: {spell.get('costBurn', 'N/A')} | Range: {spell.get('rangeBurn', 'N/A')}"
        )
        lines.append("")
    lines.append(f"Tags: {', '.join(entry.get('tags', []))}")
    return "\n".join(lines)


def render_item_markdown(item_id: str, item: dict[str, Any], version: str) -> str:
    """Deterministic markdown rendering of one item — the chunk text for indexing."""
    gold = item.get("gold", {})
    lines = [
        f"# {item.get('name', item_id)} ({version})",
        "",
        f"Item id: {item_id}",
        f"Cost: {gold.get('total', 'N/A')} gold (base {gold.get('base', 'N/A')}, "
        f"sell {gold.get('sell', 'N/A')})",
    ]
    if item.get("plaintext"):
        lines += ["", item["plaintext"]]
    stats = item.get("stats", {})
    if stats:
        lines += ["", "## Stats", ""]
        for stat in sorted(stats):
            lines.append(f"- {stat}: {stats[stat]}")
    description = strip_html(item.get("description", ""))
    if description:
        lines += ["", description]
    return "\n".join(lines)
