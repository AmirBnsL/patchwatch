"""Official patch-notes pages: one-time fetch + markdown extraction (build-time only).

Runtime never scrapes (invariant #9) — these helpers exist so the corpus build
script can freeze prose snapshots into ``fixtures/prose/``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

NOTES_BASE = "https://www.leagueoflegends.com/en-us/news/game-updates/"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)

_DATE_PATTERNS = [
    re.compile(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d{2}"
    ),
    re.compile(r"(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+20\d{2}"),
]


@dataclass(frozen=True)
class ProseSnapshot:
    """Extracted prose for one patch-notes page."""

    url: str
    markdown: str
    published_date: str | None  # e.g. "August 24, 2026" (as displayed)


def candidate_note_urls(ddragon_version: str) -> list[str]:
    """Slug candidates for a ddragon version — notes naming has drifted over time.

    ``16.18.1`` → tries ``26.18``-style and ``16.18``-style slugs, both known forms.
    """
    parts = ddragon_version.split(".")
    major, minor = parts[0], parts[1]
    candidates: list[str] = []
    for notes_version in (f"26.{minor}", f"{major}.{minor}"):
        slug_version = notes_version.replace(".", "-")
        candidates += [
            f"{NOTES_BASE}league-of-legends-patch-{slug_version}-notes/",
            f"{NOTES_BASE}patch-{slug_version}-notes/",
        ]
    return candidates


def fetch_notes_page(url: str, timeout: float = 30.0) -> str:
    """One polite GET of a patch-notes page (single request, browser UA)."""
    response = httpx.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True
    )
    response.raise_for_status()
    return response.text


def extract_markdown(html: str) -> str:
    """Extract headings/paragraphs/list items from a notes page as markdown.

    Build-time best effort: Riot's page structure varies; we keep the main
    article content and drop nav/scripts/JSON blobs.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    # Prefer the widest text container (patch notes render inside deep divs).
    container = max(soup.find_all("div"), key=lambda d: len(d.get_text()), default=soup)

    lines: list[str] = []
    for element in container.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        text = " ".join(element.get_text(separator=" ").split())
        if not text:
            continue
        if element.name == "h1":
            lines.append(f"# {text}")
        elif element.name == "h2":
            lines.append(f"## {text}")
        elif element.name == "h3":
            lines.append(f"### {text}")
        elif element.name == "h4":
            lines.append(f"#### {text}")
        elif element.name == "li":
            lines.append(f"- {text}")
        else:
            lines.append(text)
    return "\n\n".join(lines)


def extract_published_date(html: str) -> str | None:
    """Best-effort patch release date (ISO 'YYYY-MM-DD').

    Prefers the article's ``<time datetime=...>`` element (Riot pages render the
    publish date there); falls back to a display-date regex near the title.
    """
    soup = BeautifulSoup(html, "html.parser")
    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag is not None:
        return str(time_tag["datetime"])[:10]

    title_block = soup.find("h1")
    scope = title_block.find_parent() if title_block else soup
    text = scope.get_text(" ", strip=True) if scope else ""
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            parsed = parse_display_date(match.group(0))
            if parsed:
                return parsed
    return None


def fetch_prose_snapshot(ddragon_version: str) -> ProseSnapshot | None:
    """Try candidate note URLs for a patch; return the first that resolves."""
    for url in candidate_note_urls(ddragon_version):
        try:
            html = fetch_notes_page(url)
        except httpx.HTTPError:
            continue
        markdown = extract_markdown(html)
        if len(markdown) < 1000:  # bot-block / empty shells
            continue
        return ProseSnapshot(
            url=url, markdown=markdown, published_date=extract_published_date(html)
        )
    return None


_MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
    # abbreviated forms (May shared with the full name)
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def parse_display_date(display: str | None) -> str | None:
    """'August 24, 2026' → '2026-08-24' (None-safe)."""
    if not display:
        return None
    match = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s+(20\d{2})", display)
    if not match:
        return None
    month = _MONTHS.get(match.group(1).capitalize())
    if month is None:
        return None
    return f"{match.group(3)}-{month:02d}-{int(match.group(2)):02d}"
