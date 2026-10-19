"""Small, bounded web-retrieval tools used by the scraper graph node."""

from __future__ import annotations

import html
import logging
import re
from typing import Any

import requests

from ..config import settings
from .brief2_scraper import scrape_detailed_synopsis

logger = logging.getLogger(__name__)

_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def _plain_text(value: Any) -> str:
    text = _HTML_TAG_PATTERN.sub(" ", html.unescape(str(value or "")))
    return " ".join(text.split())


def search_web(
    query: str,
    limit: int | None = None,
    timeout: float | None = None,
) -> list[dict[str, str]]:
    """Search Wikipedia once and return bounded prompt-safe evidence."""
    normalized_query = " ".join(str(query or "").split())
    if not normalized_query:
        return []

    result_limit = settings.scraper_limit if limit is None else max(1, min(limit, 5))
    request_timeout = (
        settings.scraper_timeout_seconds if timeout is None else max(1.0, timeout)
    )
    params: dict[str, str | int] = {
        "action": "query",
        "generator": "search",
        "gsrsearch": normalized_query,
        "gsrlimit": result_limit,
        "prop": "extracts|info",
        "exintro": 1,
        "explaintext": 1,
        "exchars": 1200,
        "inprop": "url",
        "format": "json",
        "formatversion": 2,
    }
    headers = {"User-Agent": "HorRAGor/0.1 (local research tool)"}

    try:
        response = requests.get(
            settings.wikipedia_api_url,
            params=params,
            headers=headers,
            timeout=request_timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning("Wikipedia lookup failed: %s", exc)
        return []

    query_payload = payload.get("query") if isinstance(payload, dict) else None
    pages = query_payload.get("pages") if isinstance(query_payload, dict) else None
    if not isinstance(pages, list):
        return []

    results: list[dict[str, str]] = []
    for page in pages[:result_limit]:
        if not isinstance(page, dict):
            continue
        title = _plain_text(page.get("title"))
        extract = _plain_text(page.get("extract"))
        if not title or not extract:
            continue
        results.append(
            {
                "source": "wikipedia",
                "title": title,
                "snippet": extract[:1200],
                "url": str(page.get("fullurl") or ""),
                "page_id": str(page.get("pageid") or ""),
            }
        )
    return results


def search_horror_topic(
    subject: str,
    movie_name: str = "",
    timeout: float | None = None,
) -> list[dict[str, str]]:
    """Search public evidence for a bounded horror-movie subject."""
    normalized_subject = " ".join(str(subject or "").split())
    if not normalized_subject:
        return []
    normalized_movie = " ".join(str(movie_name or "").split())
    query = (
        f"{normalized_movie} {normalized_subject}"
        if normalized_movie
        else f"horror movies about {normalized_subject}"
    )
    return search_web(query, timeout=timeout)


def scrape_web(
    query: str,
    limit: int | None = None,
    timeout: float | None = None,
) -> list[dict[str, str]]:
    """Compatibility alias for callers that describe retrieval as scraping."""
    return search_web(query, limit=limit, timeout=timeout)


__all__ = [
    "scrape_detailed_synopsis",
    "scrape_web",
    "search_horror_topic",
    "search_web",
]
