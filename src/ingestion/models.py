"""Typed records shared by heterogeneous Brief 1 sources."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MovieRecord:
    """One normalized source record before master-data reconciliation."""

    source: str
    title: str
    release_date: str | None = None
    tmdb_id: str | None = None
    imdb_id: str | None = None
    genres: tuple[str, ...] = ()
    overview: str | None = None
    tagline: str | None = None
    vote_average: float | None = None
    imdb_rating: float | None = None
    tomatometer_score: float | None = None
    audience_score: float | None = None
    popularity: float | None = None
    poster_path: str | None = None
    budget: int | None = None
    revenue: int | None = None
    runtime: int | None = None
    cast: tuple[dict[str, Any], ...] = ()
    crew: tuple[dict[str, Any], ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def release_year(self) -> int | None:
        try:
            return int(self.release_date[:4]) if self.release_date else None
        except (TypeError, ValueError):
            return None


@dataclass(slots=True)
class CanonicalMovie:
    """Gold movie entity produced after deterministic source reconciliation."""

    title: str
    release_date: str | None
    tmdb_id: str | None
    imdb_id: str | None
    genres: list[str]
    overview: str | None
    tagline: str | None
    vote_average: float | None
    imdb_rating: float | None
    tomatometer_score: float | None
    audience_score: float | None
    popularity: float | None
    poster_path: str | None
    budget: int | None
    revenue: int | None
    runtime: int | None
    cast: list[dict[str, Any]]
    crew: list[dict[str, Any]]
    sources: list[str]
    attributes: dict[str, Any]

    @classmethod
    def from_record(cls, record: MovieRecord) -> CanonicalMovie:
        return cls(
            title=record.title,
            release_date=record.release_date,
            tmdb_id=record.tmdb_id,
            imdb_id=record.imdb_id,
            genres=list(record.genres),
            overview=record.overview,
            tagline=record.tagline,
            vote_average=record.vote_average,
            imdb_rating=record.imdb_rating,
            tomatometer_score=record.tomatometer_score,
            audience_score=record.audience_score,
            popularity=record.popularity,
            poster_path=record.poster_path,
            budget=record.budget,
            revenue=record.revenue,
            runtime=record.runtime,
            cast=list(record.cast),
            crew=list(record.crew),
            sources=[record.source],
            attributes=dict(record.attributes),
        )

    @property
    def release_year(self) -> int | None:
        try:
            return int(self.release_date[:4]) if self.release_date else None
        except (TypeError, ValueError):
            return None

    @property
    def stable_id(self) -> str:
        if self.tmdb_id:
            return self.tmdb_id
        if self.imdb_id:
            return self.imdb_id
        identity = f"{self.title.casefold()}|{self.release_year or ''}"
        return hashlib.blake2b(identity.encode("utf-8"), digest_size=8).hexdigest()

    def to_row(self) -> dict[str, str]:
        """Serialize to the flat UTF-8 CSV schema consumed by the FAISS service."""
        values: dict[str, Any] = {
            "id": self.stable_id,
            "tmdb_id": self.tmdb_id,
            "imdb_id": self.imdb_id,
            "title": self.title,
            "release_date": self.release_date,
            "genre_names": ", ".join(self.genres),
            "overview": self.overview,
            "tagline": self.tagline,
            "vote_average": self.vote_average,
            "imdb_rating": self.imdb_rating,
            "tomatometer_score": self.tomatometer_score,
            "audience_score": self.audience_score,
            "popularity": self.popularity,
            "poster_path": self.poster_path,
            "budget": self.budget,
            "revenue": self.revenue,
            "runtime": self.runtime,
            "cast": list(self.cast),
            "crew": list(self.crew),
            "sources": self.sources,
        }
        values.update(self.attributes)
        return {
            key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value or "")
            for key, value in values.items()
        }