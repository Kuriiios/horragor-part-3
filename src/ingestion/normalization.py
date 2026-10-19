"""Source-independent normalization and thematic quality gates."""

from __future__ import annotations

import html
import math
import re
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any

from .models import MovieRecord

_MISSING = {"", "na", "n/a", "nan", "none", "null", "\\n"}
_HORROR_GENRES = {"horror", "gore", "horreur", "epouvante", "épouvante"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def clean_text(value: Any) -> str | None:
    """Decode HTML and normalize Unicode plus repeated whitespace."""
    if value is None:
        return None
    raw = str(value).strip()
    if raw.casefold() in _MISSING:
        return None
    parser = _TextExtractor()
    try:
        parser.feed(html.unescape(raw))
        text = " ".join(parser.parts)
    except ValueError:
        text = raw
    normalized = unicodedata.normalize("NFC", " ".join(text.split())).strip()
    return normalized or None


def normalize_date(value: Any) -> str | None:
    """Normalize full dates and year-only values to ISO 8601."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    if text.casefold() in _MISSING:
        return None
    if re.fullmatch(r"\d{4}", text):
        year = int(text)
        return f"{year:04d}-01-01" if 1888 <= year <= 2200 else None
    normalized = text.replace("/", "-")
    for format_string in ("%Y-%m-%d", "%d-%m-%Y", "%Y-%m"):
        try:
            parsed = datetime.strptime(normalized, format_string).date()
            if format_string == "%Y-%m":
                parsed = parsed.replace(day=1)
            return parsed.isoformat()
        except ValueError:
            continue
    return None


def normalize_number(
    value: Any,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    if minimum is not None and parsed < minimum:
        return None
    if maximum is not None and parsed > maximum:
        return None
    return parsed


def normalize_integer(value: Any, *, minimum: int = 0) -> int | None:
    number = normalize_number(value, minimum=float(minimum))
    return int(number) if number is not None else None


def normalize_identifier(value: Any) -> str | None:
    text = clean_text(value)
    return text if text and text.casefold() not in _MISSING else None


def normalize_genres(value: Any) -> tuple[str, ...]:
    entries: Iterable[Any]
    if isinstance(value, (list, tuple, set)):
        entries = value
    elif isinstance(value, str):
        entries = re.split(r"[,|;/]", value)
    else:
        entries = ()
    genres: list[str] = []
    for entry in entries:
        candidate = entry.get("name") if isinstance(entry, dict) else entry
        genre = clean_text(candidate)
        if genre and genre.casefold() not in {item.casefold() for item in genres}:
            genres.append(genre)
    return tuple(genres)


def is_horror(genres: Iterable[str]) -> bool:
    normalized = {genre.casefold() for genre in genres}
    return bool(normalized & _HORROR_GENRES)


def _sequence_of_mappings(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(entry) for entry in value if isinstance(entry, dict))


def normalize_movie_record(raw: dict[str, Any], source: str) -> MovieRecord | None:
    """Map one heterogeneous source payload to the canonical staging contract."""
    title = clean_text(
        raw.get("title")
        or raw.get("primaryTitle")
        or raw.get("original_title")
        or raw.get("movie_title")
    )
    genres = normalize_genres(raw.get("genres") or raw.get("genre_names") or raw.get("genre"))
    if not title or not is_horror(genres):
        return None

    release_date = normalize_date(
        raw.get("release_date") or raw.get("startYear") or raw.get("year")
    )
    tmdb_id = normalize_identifier(raw.get("tmdb_id"))
    if source == "tmdb" and not tmdb_id:
        tmdb_id = normalize_identifier(raw.get("id"))
    imdb_id = normalize_identifier(raw.get("imdb_id") or raw.get("tconst"))
    known_keys = {
        "id", "tmdb_id", "imdb_id", "tconst", "title", "primaryTitle", "original_title",
        "movie_title", "release_date", "startYear", "year", "genres", "genre_names", "genre",
        "overview", "synopsis", "plot", "tagline", "vote_average", "averageRating",
        "imdb_rating", "tomatometer_score", "audience_score", "popularity", "poster_path",
        "budget", "revenue", "runtime", "cast", "crew",
    }
    attributes = {
        str(key): value
        for key, value in raw.items()
        if key not in known_keys and value not in (None, "")
    }
    return MovieRecord(
        source=source,
        title=title,
        release_date=release_date,
        tmdb_id=tmdb_id,
        imdb_id=imdb_id,
        genres=genres,
        overview=clean_text(raw.get("overview") or raw.get("synopsis") or raw.get("plot")),
        tagline=clean_text(raw.get("tagline")),
        vote_average=normalize_number(raw.get("vote_average"), minimum=0, maximum=10),
        imdb_rating=normalize_number(
            raw.get("imdb_rating") or raw.get("averageRating"),
            minimum=0,
            maximum=10,
        ),
        tomatometer_score=normalize_number(
            raw.get("tomatometer_score"), minimum=0, maximum=100
        ),
        audience_score=normalize_number(raw.get("audience_score"), minimum=0, maximum=100),
        popularity=normalize_number(raw.get("popularity"), minimum=0),
        poster_path=clean_text(raw.get("poster_path")),
        budget=normalize_integer(raw.get("budget")),
        revenue=normalize_integer(raw.get("revenue")),
        runtime=normalize_integer(raw.get("runtime")),
        cast=_sequence_of_mappings(raw.get("cast")),
        crew=_sequence_of_mappings(raw.get("crew")),
        attributes=attributes,
    )