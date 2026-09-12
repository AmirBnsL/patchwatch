"""Data Dragon client tests — httpx MockTransport, no network."""

from __future__ import annotations

import httpx
import pytest

from patchwatch.ingest.ddragon import DDragonClient, DDragonError, champion_ids

VERSIONS = ["16.18.1", "16.17.1", "16.16.1"]

AHRI_DETAIL = {
    "type": "champion",
    "version": "16.18.1",
    "data": {"Ahri": {"id": "Ahri", "name": "Ahri", "spells": []}},
}

SUMMARY = {"type": "champion", "data": {"Ahri": {"id": "Ahri"}, "Zed": {"id": "Zed"}}}

ITEMS = {"type": "item", "data": {"3031": {"name": "Infinity Edge"}}}


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith("/api/versions.json"):
        return httpx.Response(200, json=VERSIONS)
    if "/realms/" in url:
        return httpx.Response(200, json={"v": "16.18.1", "l": "en_US"})
    if url.endswith("/champion.json"):
        return httpx.Response(200, json=SUMMARY)
    if url.endswith("/champion/Ahri.json"):
        return httpx.Response(200, json=AHRI_DETAIL)
    if url.endswith("/item.json"):
        return httpx.Response(200, json=ITEMS)
    return httpx.Response(404)


@pytest.fixture
def client() -> DDragonClient:
    return DDragonClient(transport=httpx.MockTransport(_handler))


def test_versions_newest_first(client: DDragonClient) -> None:
    assert client.versions() == VERSIONS
    assert client.latest_version() == "16.18.1"


def test_realm(client: DDragonClient) -> None:
    assert client.realm("na")["v"] == "16.18.1"


def test_champion_summary_and_detail(client: DDragonClient) -> None:
    assert "Ahri" in client.champion_summary("16.18.1")["data"]
    detail = client.champion_detail("16.18.1", "Ahri")
    assert detail["data"]["Ahri"]["id"] == "Ahri"


def test_items(client: DDragonClient) -> None:
    assert "3031" in client.items("16.18.1")["data"]


def test_champion_ids_sorted() -> None:
    assert champion_ids(SUMMARY) == ["Ahri", "Zed"]


def test_http_error_raises(client: DDragonClient) -> None:
    with pytest.raises(DDragonError):
        client.champion_detail("16.18.1", "Nobody")


def test_empty_versions_raises() -> None:
    client = DDragonClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    )
    with pytest.raises(DDragonError):
        client.versions()


def test_utf8_header_sent() -> None:
    captured: dict[str, str] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        return httpx.Response(200, json=VERSIONS)

    DDragonClient(transport=httpx.MockTransport(capture)).versions()
    assert captured.get("accept-charset") == "utf-8"
