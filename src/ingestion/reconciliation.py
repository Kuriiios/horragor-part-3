"""Priority-aware master-data reconciliation for normalized movie records."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from difflib import SequenceMatcher

from .models import CanonicalMovie, MovieRecord

SOURCE_PRIORITY = {
    "tmdb": 0,
    "rotten_tomatoes": 1,
    "kaggle": 2,
    "imdb": 3,
    "spark": 4,
}


def _normalized_title(title: str) -> str:
    text = unicodedata.normalize("NFKD", title)
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _title_similarity(left: str, right: str) -> float:
    try:
        from rapidfuzz.fuzz import ratio

        return float(ratio(left, right)) / 100.0
    except ImportError:
        return SequenceMatcher(None, left, right).ratio()


def _merge_unique_mappings(
    current: list[dict],
    incoming: tuple[dict, ...],
) -> None:
    seen = {str(item.get("id") or item.get("name") or item) for item in current}
    for item in incoming:
        identity = str(item.get("id") or item.get("name") or item)
        if identity not in seen:
            current.append(dict(item))
            seen.add(identity)


def _merge(movie: CanonicalMovie, record: MovieRecord) -> None:
    for field_name in (
        "release_date", "tmdb_id", "imdb_id", "overview", "tagline", "vote_average",
        "imdb_rating", "tomatometer_score", "audience_score", "popularity", "poster_path",
        "budget", "revenue", "runtime",
    ):
        if getattr(movie, field_name) in (None, ""):
            setattr(movie, field_name, getattr(record, field_name))
    existing_genres = {genre.casefold() for genre in movie.genres}
    movie.genres.extend(
        genre for genre in record.genres if genre.casefold() not in existing_genres
    )
    _merge_unique_mappings(movie.cast, record.cast)
    _merge_unique_mappings(movie.crew, record.crew)
    if record.source not in movie.sources:
        movie.sources.append(record.source)
    for key, value in record.attributes.items():
        movie.attributes.setdefault(key, value)


def reconcile_movies(
    records: Iterable[MovieRecord],
    *,
    fuzzy_threshold: float = 0.9,
) -> list[CanonicalMovie]:
    """Deduplicate by IDs, exact title/year, then fuzzy title/year in source priority order."""
    ordered = sorted(
        records,
        key=lambda record: (SOURCE_PRIORITY.get(record.source, 99), record.title.casefold()),
    )
    movies: list[CanonicalMovie] = []
    by_tmdb_id: dict[str, int] = {}
    by_imdb_id: dict[str, int] = {}
    by_title_year: dict[tuple[str, int | None], int] = {}
    by_year: dict[int | None, list[int]] = defaultdict(list)

    for record in ordered:
        title_key = _normalized_title(record.title)
        year = record.release_year
        position = by_tmdb_id.get(record.tmdb_id or "")
        if position is None:
            position = by_imdb_id.get(record.imdb_id or "")
        if position is None:
            position = by_title_year.get((title_key, year))
        if position is None and title_key:
            for candidate_position in by_year[year]:
                candidate_title = _normalized_title(movies[candidate_position].title)
                if _title_similarity(title_key, candidate_title) >= fuzzy_threshold:
                    position = candidate_position
                    break

        if position is None:
            position = len(movies)
            movies.append(CanonicalMovie.from_record(record))
            by_year[year].append(position)
        else:
            _merge(movies[position], record)

        movie = movies[position]
        if movie.tmdb_id:
            by_tmdb_id[movie.tmdb_id] = position
        if movie.imdb_id:
            by_imdb_id[movie.imdb_id] = position
        by_title_year[(_normalized_title(movie.title), movie.release_year)] = position

    return movies