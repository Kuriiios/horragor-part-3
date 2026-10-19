"""Safe batch repositories for SQLAlchemy databases and Supabase."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from ..ingestion.models import CanonicalMovie
from .models import Base, Credit, Genre, Movie, MovieGenre, MovieSource, Person, Source


def _normalized_title(title: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", title.casefold()))


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _stable_hash(*parts: Any) -> str:
    value = "|".join(str(part or "") for part in parts)
    return hashlib.blake2b(value.encode("utf-8"), digest_size=16).hexdigest()


def _movie_row(movie: CanonicalMovie) -> dict[str, Any]:
    return {
        "id": movie.stable_id,
        "tmdb_id": movie.tmdb_id,
        "imdb_id": movie.imdb_id,
        "title": movie.title,
        "normalized_title": _normalized_title(movie.title),
        "release_date": movie.release_date,
        "overview": movie.overview,
        "tagline": movie.tagline,
        "vote_average": movie.vote_average,
        "imdb_rating": movie.imdb_rating,
        "tomatometer_score": movie.tomatometer_score,
        "audience_score": movie.audience_score,
        "popularity": movie.popularity,
        "poster_path": movie.poster_path,
        "budget": movie.budget,
        "revenue": movie.revenue,
        "runtime": movie.runtime,
        "extra_attributes": movie.attributes,
    }


def _credit_rows(movie: CanonicalMovie) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    people: dict[str, dict[str, Any]] = {}
    credits: list[dict[str, Any]] = []
    for credit_type, entries in (("cast", movie.cast), ("crew", movie.crew)):
        for position, entry in enumerate(entries):
            name = str(entry.get("name", "")).strip()
            if not name:
                continue
            person_id = str(entry.get("id") or _stable_hash(name.casefold()))
            role_name = str(entry.get("character") or entry.get("job") or "").strip()
            people[person_id] = {"id": person_id, "name": name}
            credits.append(
                {
                    "id": _stable_hash(movie.stable_id, person_id, credit_type, role_name),
                    "movie_id": movie.stable_id,
                    "person_id": person_id,
                    "credit_type": credit_type,
                    "role_name": role_name,
                    "billing_order": entry.get("order", position),
                }
            )
    return list(people.values()), credits


class SqlAlchemyMovieRepository:
    """Transactional ORM upserts for PostgreSQL or local validation databases."""

    def __init__(self, engine: Engine, *, create_schema: bool = False) -> None:
        self.engine = engine
        if create_schema:
            Base.metadata.create_all(engine)

    @classmethod
    def from_url(cls, database_url: str, *, create_schema: bool = False):
        return cls(create_engine(database_url, pool_pre_ping=True), create_schema=create_schema)

    def upsert_movies(self, movies: Sequence[CanonicalMovie]) -> int:
        with Session(self.engine) as session, session.begin():
            for movie in movies:
                row = _movie_row(movie)
                row["release_date"] = _date(movie.release_date)
                session.merge(Movie(**row))
                for source_name in movie.sources:
                    session.merge(Source(name=source_name))
                    session.merge(
                        MovieSource(
                            movie_id=movie.stable_id,
                            source_name=source_name,
                            source_record_id=movie.tmdb_id or movie.imdb_id,
                            payload={"title": movie.title},
                        )
                    )
                for genre_name in movie.genres:
                    session.merge(Genre(name=genre_name))
                    session.merge(
                        MovieGenre(movie_id=movie.stable_id, genre_name=genre_name)
                    )
                people, credits = _credit_rows(movie)
                for person in people:
                    session.merge(Person(**person))
                for credit in credits:
                    session.merge(Credit(**credit))
        return len(movies)


class SupabaseMovieRepository:
    """Service-role Supabase adapter using bounded structured upserts only."""

    def __init__(self, client: Any, *, batch_size: int = 250) -> None:
        self.client = client
        self.batch_size = max(1, min(int(batch_size), 500))

    @classmethod
    def from_credentials(cls, url: str, service_role_key: str):
        from supabase import create_client

        return cls(create_client(url, service_role_key))

    def _upsert(self, table: str, rows: list[dict[str, Any]], conflict: str) -> None:
        for offset in range(0, len(rows), self.batch_size):
            batch = rows[offset : offset + self.batch_size]
            if batch:
                self.client.table(table).upsert(batch, on_conflict=conflict).execute()

    def upsert_movies(self, movies: Sequence[CanonicalMovie]) -> int:
        movie_rows = [_movie_row(movie) for movie in movies]
        source_rows = sorted({source for movie in movies for source in movie.sources})
        genre_rows = sorted({genre for movie in movies for genre in movie.genres})
        movie_sources = [
            {
                "movie_id": movie.stable_id,
                "source_name": source,
                "source_record_id": movie.tmdb_id or movie.imdb_id,
                "payload": {"title": movie.title},
            }
            for movie in movies
            for source in movie.sources
        ]
        movie_genres = [
            {"movie_id": movie.stable_id, "genre_name": genre}
            for movie in movies
            for genre in movie.genres
        ]
        people_by_id: dict[str, dict[str, Any]] = {}
        credit_rows: list[dict[str, Any]] = []
        for movie in movies:
            people, credits = _credit_rows(movie)
            people_by_id.update({person["id"]: person for person in people})
            credit_rows.extend(credits)
        self._upsert("movies", movie_rows, "id")
        self._upsert("sources", [{"name": name} for name in source_rows], "name")
        self._upsert("genres", [{"name": name} for name in genre_rows], "name")
        self._upsert("people", list(people_by_id.values()), "id")
        self._upsert("movie_sources", movie_sources, "movie_id,source_name")
        self._upsert("movie_genres", movie_genres, "movie_id,genre_name")
        self._upsert("credits", credit_rows, "id")
        return len(movies)


def repository_from_environment() -> SqlAlchemyMovieRepository | SupabaseMovieRepository | None:
    """Create the configured backend repository without exposing credentials to the UI."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return SqlAlchemyMovieRepository.from_url(database_url)
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if supabase_url and service_role_key:
        return SupabaseMovieRepository.from_credentials(supabase_url, service_role_key)
    return None