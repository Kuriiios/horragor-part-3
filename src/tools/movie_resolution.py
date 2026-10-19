"""Deterministic resolution of explicit movie-title references."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

_TITLE_REFERENCE_CUES = {
    "about",
    "actors",
    "age",
    "called",
    "cast",
    "director",
    "directed",
    "film",
    "for",
    "from",
    "genre",
    "in",
    "like",
    "movie",
    "named",
    "of",
    "on",
    "plot",
    "rating",
    "regarding",
    "release",
    "runtime",
    "similar",
    "starring",
    "survive",
    "survival",
    "synopsis",
    "title",
    "to",
    "versus",
    "vs",
}
_QUESTION_LEADING_WORDS = {
    "give",
    "how",
    "list",
    "show",
    "tell",
    "what",
    "when",
    "where",
    "who",
    "why",
}
_FOLLOW_UP_PATTERNS = (
    re.compile(r"\b(it|this|that|they|them)\b", re.IGNORECASE),
    re.compile(r"\bthis\s+(?:movie|film|title|one)\b", re.IGNORECASE),
    re.compile(r"\bthat\s+(?:movie|film|title|one)\b", re.IGNORECASE),
    re.compile(r"\bthe\s+(?:same|other|first|second|third|last|next)\s+one\b", re.IGNORECASE),
)
_BROAD_RECOMMENDATION_PATTERN = re.compile(
    r"\b(?:recommend|recommand|suggest|want\s+to\s+see|looking\s+for)\b",
     re.IGNORECASE,
)
_TOPIC_REQUEST_PATTERN = re.compile(
    r"\b(?:about|with|featuring|containing|contain|contains|involving|"
    r"centered\s+on|dealing\s+with|sur|avec|qui\s+contient)\b",
     re.IGNORECASE,
)


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(text.casefold().split())


def _find_exact_movie(store: Any, question: str) -> dict[str, str] | None:
    try:
        hits = store.search(question, limit=20)
    except (AttributeError, TypeError, ValueError):
        return None

    normalized_question = _normalize(question)
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        movie = hit.get("movie")
        if not isinstance(movie, dict):
            continue
        title = str(movie.get("title", "")).strip()
        if not title or float(hit.get("score", 0.0) or 0.0) < 0.999:
            continue
        if _is_title_reference(normalized_question, title):
            return movie
    return None


def _history_questions(history: Sequence[Mapping[str, Any]] | None) -> list[str]:
    if not history:
        return []
    return [
        " ".join(str(message.get("content", "")).split())
        for message in history
        if str(message.get("role", "")).casefold() == "user"
        and str(message.get("content", "")).strip()
    ]


def _is_follow_up_question(question: str) -> bool:
    """Use history only for anaphoric wording, never as a general fallback."""
    return any(pattern.search(question) for pattern in _FOLLOW_UP_PATTERNS)


def _is_broad_topic_request(question: str) -> bool:
    """Keep recommendation topics from being resolved as generic movie titles."""
    return bool(
        _BROAD_RECOMMENDATION_PATTERN.search(question)
        and _TOPIC_REQUEST_PATTERN.search(question)
    )


def _is_title_reference(question: str, title: str) -> bool:
    """Accept title mentions without treating ordinary words as movie names."""
    normalized_question = _normalize(question)
    normalized_title = _normalize(title)
    word_question = " ".join(re.findall(r"[\w]+", normalized_question, re.UNICODE))
    word_title = " ".join(re.findall(r"[\w]+", normalized_title, re.UNICODE))
    if word_question == word_title:
        return True

    title_words = word_title.split()
    if not title_words:
        return False
    pattern = rf"(?<!\w){re.escape(normalized_title)}(?!\w)"
    for match in re.finditer(pattern, normalized_question):
        before = re.findall(r"[\w]+", normalized_question[: match.start()], re.UNICODE)
        after = re.findall(r"[\w]+", normalized_question[match.end() :], re.UNICODE)
        if before and before[-1] in _TITLE_REFERENCE_CUES:
            return True
        if (
            after
            and after[0] in _TITLE_REFERENCE_CUES
            and not (
                not before
                and len(title_words) == 1
                and title_words[0] in _QUESTION_LEADING_WORDS
            )
        ):
            return True
        # A one-word title at the beginning is ambiguous (for example,
        # "Tell me ..." matching a film titled "Tell").
        if len(title_words) > 1 and not before and not after:
            return True
    return False


def resolve_movie_reference(
    store: Any,
    question: str,
    history: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve a title explicitly mentioned in the current user request."""
    normalized_question = " ".join(str(question or "").split())
    if not normalized_question:
        return {"status": "unresolved", "confidence": 0.0, "source": "none"}

    if _is_broad_topic_request(normalized_question):
        return {"status": "unresolved", "confidence": 0.0, "source": "semantic_search"}

    exact_movie = _find_exact_movie(store, normalized_question)
    if exact_movie:
        return {
            "status": "resolved",
            "title": str(exact_movie.get("title", "")),
            "movie_id": exact_movie.get("id"),
            "confidence": 1.0,
            "source": "exact_title",
            "search_query": str(exact_movie.get("title", "")),
        }

    if _is_follow_up_question(normalized_question):
        for previous_question in reversed(_history_questions(history)):
            exact_movie = _find_exact_movie(store, previous_question)
            if exact_movie:
                return {
                    "status": "resolved",
                    "title": str(exact_movie.get("title", "")),
                    "movie_id": exact_movie.get("id"),
                    "confidence": 0.95,
                    "source": "history_title",
                    "search_query": str(exact_movie.get("title", "")),
                }

    return {"status": "unresolved", "confidence": 0.0, "source": "semantic_search"}
