"""Prose fetcher/extraction tests — fixed HTML, no network."""

from __future__ import annotations

from patchwatch.ingest.prose import (
    candidate_note_urls,
    extract_markdown,
    extract_published_date,
    parse_display_date,
)

SAMPLE_HTML = """\
<html><head><title>Patch 26.7 Notes</title></head>
<body>
<script>window.__data = {"big": "blob"};</script>
<nav><a href="/">Home</a></nav>
<div class="content">
  <h1>Patch 26.7 Notes</h1>
  <p>Welcome to patch 26.7!</p>
  <h2>Champions</h2>
  <p>Ahri changes below.</p>
  <ul><li>Q base damage increased.</li><li>E cooldown adjusted.</li></h2>
  <h3>Context</h3>
  <p>We wanted Ahri stronger for all players. August 24, 2026</p>
</div>
<footer>copyright</footer>
</body></html>
"""


def test_candidate_note_urls_cover_known_slugs() -> None:
    urls = candidate_note_urls("16.18.1")
    assert (
        "https://www.leagueoflegends.com/en-us/news/game-updates/league-of-legends-patch-26-18-notes/"
        in urls
    )
    assert "https://www.leagueoflegends.com/en-us/news/game-updates/patch-16-18-notes/" in urls


def test_extract_markdown_structure() -> None:
    markdown = extract_markdown(SAMPLE_HTML)
    assert "# Patch 26.7 Notes" in markdown
    assert "## Champions" in markdown
    assert "### Context" in markdown
    assert "- Q base damage increased." in markdown
    assert "__data" not in markdown  # script blob dropped
    assert "Home" not in markdown  # nav dropped
    assert "copyright" not in markdown  # footer dropped


def test_extract_published_date() -> None:
    sample = (
        '<html><body><h1>Patch</h1><time datetime="2026-09-09T18:00:00.000Z">x</time></body></html>'
    )
    assert extract_published_date(sample) == "2026-09-09"
    assert extract_published_date(SAMPLE_HTML) == "2026-08-24"  # fallback path
    assert extract_published_date("<html><body>no date</body></html>") is None


def test_parse_display_date() -> None:
    assert parse_display_date("August 24, 2026") == "2026-08-24"
    assert parse_display_date("Mar 17, 2026") == "2026-03-17"
    assert parse_display_date(None) is None
    assert parse_display_date("whenever") is None
