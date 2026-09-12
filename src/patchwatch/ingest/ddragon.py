"""Data Dragon HTTP client (Riot's official static-data CDN).

Used by the corpus build script to freeze snapshots; runtime reads the frozen
corpus / database, never the CDN (invariant #9).

Docs notes honored: requests carry ``Accept-Charset: utf-8``; versions are listed
newest-first in ``versions.json``; per-region currency lives in ``realms/{region}.json``.
"""

from __future__ import annotations

from typing import Any

import httpx

BASE_URL = "https://ddragon.leagueoflegends.com"
DEFAULT_TIMEOUT = 30.0


class DDragonError(RuntimeError):
    """Raised when Data Dragon returns an unexpected response."""


class DDragonClient:
    """Thin, typed wrapper over the Data Dragon CDN endpoints we need."""

    def __init__(
        self, timeout: float = DEFAULT_TIMEOUT, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._client = httpx.Client(
            headers={"Accept-Charset": "utf-8"}, timeout=timeout, transport=transport
        )

    def close(self) -> None:
        """Release the underlying HTTP client."""
        self._client.close()

    def _get_json(self, path: str) -> Any:
        response = self._client.get(f"{BASE_URL}{path}")
        if response.status_code != 200:
            raise DDragonError(f"Data Dragon returned {response.status_code} for {path}")
        return response.json()

    def _get_object(self, path: str, context: str) -> dict[str, Any]:
        payload = self._get_json(path)
        if not isinstance(payload, dict):
            raise DDragonError(f"Data Dragon payload for {context} is not an object")
        return payload

    def versions(self) -> list[str]:
        """All patch versions, newest first."""
        versions = self._get_json("/api/versions.json")
        if not isinstance(versions, list) or not versions:
            raise DDragonError("versions.json returned an empty/non-list payload")
        return [str(version) for version in versions]

    def latest_version(self) -> str:
        """The most recent patch version on the CDN."""
        return self.versions()[0]

    def realm(self, region: str = "na") -> dict[str, Any]:
        """Per-region current versions (a CDN version != live in all regions)."""
        return self._get_object(f"/realms/{region}.json", context=f"realm {region!r}")

    def champion_summary(self, version: str, locale: str = "en_US") -> dict[str, Any]:
        """``champion.json`` — all champions, brief data."""
        return self._get_object(
            f"/cdn/{version}/data/{locale}/champion.json", context=f"champion.json {version}"
        )

    def champion_detail(
        self, version: str, champion_id: str, locale: str = "en_US"
    ) -> dict[str, Any]:
        """``champion/{id}.json`` — full data: stats, spells, passive (~15KB each)."""
        return self._get_object(
            f"/cdn/{version}/data/{locale}/champion/{champion_id}.json",
            context=f"champion/{champion_id} {version}",
        )

    def items(self, version: str, locale: str = "en_US") -> dict[str, Any]:
        """``item.json`` — all items with stats, gold costs, descriptions."""
        return self._get_object(
            f"/cdn/{version}/data/{locale}/item.json", context=f"item.json {version}"
        )


def champion_ids(summary: dict[str, Any]) -> list[str]:
    """Champion ids from a ``champion.json`` summary payload, sorted for determinism."""
    data = summary.get("data", {})
    if not isinstance(data, dict):
        raise DDragonError("champion.json payload missing 'data' object")
    return sorted(str(key) for key in data)
