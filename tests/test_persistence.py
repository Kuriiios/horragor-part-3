import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, Mock

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from src.ingestion.models import CanonicalMovie
from src.persistence.models import Credit, Genre, Movie, MovieSource, Person
from src.persistence.repositories import SqlAlchemyMovieRepository, SupabaseMovieRepository


def canonical_movie() -> CanonicalMovie:
    return CanonicalMovie(
        title="Test Horror",
        release_date="2020-01-01",
        tmdb_id="10",
        imdb_id="tt10",
        genres=["Horror", "Thriller"],
        overview="Dark evidence.",
        tagline=None,
        vote_average=7.0,
        imdb_rating=6.8,
        tomatometer_score=80.0,
        audience_score=75.0,
        popularity=1.0,
        poster_path=None,
        budget=3_000_000_000,
        revenue=4_000_000_000,
        runtime=90,
        cast=[{"id": 1, "name": "Lead Actor", "character": "Lead"}],
        crew=[{"id": 2, "name": "Director", "job": "Director"}],
        sources=["tmdb", "imdb"],
        attributes={"language": "en"},
    )


class SqlAlchemyRepositoryTests(unittest.TestCase):
    def test_upsert_is_idempotent_across_normalized_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'movies.db'}")
            repository = SqlAlchemyMovieRepository(engine, create_schema=True)
            movie = canonical_movie()

            repository.upsert_movies([movie])
            movie.overview = "Updated evidence."
            repository.upsert_movies([movie])

            with Session(engine) as session:
                counts = {
                    model.__tablename__: session.scalar(select(func.count()).select_from(model))
                    for model in (Movie, MovieSource, Genre, Person, Credit)
                }
                stored = session.get(Movie, "10")
                if stored is None:
                    self.fail("Expected the upserted movie")
                self.assertEqual(stored.overview, "Updated evidence.")
                self.assertEqual(stored.budget, 3_000_000_000)
            engine.dispose()

        self.assertEqual(
            counts,
            {"movies": 1, "movie_sources": 2, "genres": 2, "people": 2, "credits": 2},
        )


class SupabaseRepositoryTests(unittest.TestCase):
    def test_repository_uses_structured_bounded_upserts(self) -> None:
        executions: list[tuple[str, list[dict], str]] = []
        client = Mock()

        def table(name: str):
            query = Mock()

            def upsert(rows: list[dict], on_conflict: str):
                executions.append((name, rows, on_conflict))
                return query

            query.upsert.side_effect = upsert
            query.execute.return_value = Mock()
            return query

        client.table.side_effect = table
        repository = SupabaseMovieRepository(client, batch_size=1)

        count = repository.upsert_movies([canonical_movie()])

        self.assertEqual(count, 1)
        self.assertIn(("movies", [ANY], "id"), executions)
        self.assertTrue(all(len(rows) <= 1 for _, rows, _ in executions))
        self.assertNotIn("sql", " ".join(name for name, _, _ in executions).casefold())


if __name__ == "__main__":
    unittest.main()