"""Private Wikipedia retrieval behind Brief 2's single scraping tool."""

from __future__ import annotations

import html
import logging
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any

import requests

from ..config import settings

logger = logging.getLogger(__name__)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_USEFUL_SECTION_CUES = (
    "plot",
    "premise",
    "synopsis",
    "story",
    "production",
    "development",
    "filming",
    "release",
    "reception",
    "cast",
)


def _plain_text(value: Any) -> str:
    return " ".join(_HTML_TAG_PATTERN.sub(" ", html.unescape(str(value or ""))).split())


def _title_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _plain_text(value)).casefold()
    return "".join(character for character in text if character.isalnum())


def _matches_movie(page_title: str, requested_title: str) -> bool:
    page_text = _plain_text(page_title).casefold()
    requested_text = _plain_text(requested_title).casefold()
    return bool(requested_text) and (
        _title_key(page_title) == _title_key(requested_title)
        or page_text.startswith(f"{requested_text} (")
    )


class _WikipediaSectionParser(HTMLParser):
    """Extract paragraph text under MediaWiki level-two and level-three headings."""

    def __init__(self) -> None:
        super().__init__()
        self.sections: dict[str, list[str]] = {"introduction": []}
        self._current_section = "introduction"
        self._heading_tag: str | None = None
        self._heading_parts: list[str] = []
        self._paragraph_parts: list[str] | None = None

    def handle_starttag(self, tag: str, _: list[tuple[str, str | None]]) -> None:
        if tag in {"h2", "h3"}:
            self._heading_tag = tag
            self._heading_parts = []
        elif tag == "p":
            self._paragraph_parts = []

    def handle_data(self, data: str) -> None:
        if self._heading_tag:
            self._heading_parts.append(data)
        elif self._paragraph_parts is not None:
            self._paragraph_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._heading_tag:
            heading = _plain_text("".join(self._heading_parts))
            normalized_heading = re.sub(r"[^a-z0-9]+", "_", heading.casefold()).strip("_")
            if normalized_heading:
                self._current_section = normalized_heading
                self.sections.setdefault(normalized_heading, [])
            self._heading_tag = None
            self._heading_parts = []
        elif tag == "p" and self._paragraph_parts is not None:
            paragraph = _plain_text("".join(self._paragraph_parts))
            if paragraph:
                self.sections.setdefault(self._current_section, []).append(paragraph)
            self._paragraph_parts = None


def _useful_sections(markup: Any) -> dict[str, str]:
    parser = _WikipediaSectionParser()
    try:
        parser.feed(str(markup or ""))
        parser.close()
    except (TypeError, ValueError):
        return {}
    sections: dict[str, str] = {}
    for heading, paragraphs in parser.sections.items():
        if heading == "introduction" or any(cue in heading for cue in _USEFUL_SECTION_CUES):
            content = _plain_text(" ".join(paragraphs))
            if content:
                sections[heading] = content[:1400]
    return sections


def _get(params: dict[str, Any], timeout: float) -> dict[str, Any] | None:
    try:
        response = requests.get(
            settings.wikipedia_api_url,
            params=params,
            headers={"User-Agent": "HorRAGor/1.0 (educational movie research)"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning("Wikipedia synopsis request failed: %s", exc)
        return None
    return payload if isinstance(payload, dict) else None


def _find_movie_page(movie_title: str, timeout: float) -> dict[str, Any] | None:
    payload = _get(
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": f"{movie_title} film",
            "gsrlimit": 5,
            "prop": "extracts|info",
            "exintro": 1,
            "explaintext": 1,
            "exchars": 800,
            "inprop": "url",
            "format": "json",
            "formatversion": 2,
        },
        timeout,
    )
    pages = payload.get("query", {}).get("pages", []) if payload else []
    if not isinstance(pages, list):
        return None
    return next(
        (
            page
            for page in pages
            if isinstance(page, dict)
            and _matches_movie(str(page.get("title", "")), movie_title)
        ),
        None,
    )


def scrape_detailed_synopsis(
    movie_title: str,
    timeout: float | None = None,
) -> list[dict[str, Any]]:
    """Fetch one detailed Wikipedia synopsis for a specifically named movie."""
    title = " ".join(str(movie_title or "").split())
    if not title:
        return []
    request_timeout = settings.scraper_timeout_seconds if timeout is None else max(1.0, timeout)
    candidate = _find_movie_page(title, request_timeout)
    if candidate is None:
        return []

    page_title = _plain_text(candidate.get("title"))
    payload = _get(
        {
            "action": "parse",
            "page": page_title,
            "prop": "text|sections",
            "format": "json",
            "formatversion": 2,
        },
        request_timeout,
    )
    page = payload.get("parse") if payload else None
    if not isinstance(page, dict):
        return []
    markup = page.get("text", "")
    if isinstance(markup, dict):
        markup = markup.get("*", "")
    sections = _useful_sections(markup)
    introduction = sections.get("introduction") or _plain_text(candidate.get("extract"))
    synopsis = (
        sections.get("plot")
        or sections.get("plot_summary")
        or sections.get("synopsis")
        or introduction
    )
    if not synopsis:
        return []
    return [
        {
            "source": "wikipedia",
            "title": _plain_text(page.get("title")) or page_title,
            "snippet": synopsis[:5000],
            "wikipedia_sections": sections,
            "url": str(candidate.get("fullurl") or ""),
            "detail_level": "detailed",
        }
    ]