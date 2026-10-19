"""Parameterized IMDb SQLite extraction with the required horror/vote gates."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from ..models import MovieRecord
from ..normalization import normalize_movie_record
from .base import SourceNotConfigured


class ImdbSqliteSource:
    name = "imdb"

    def __init__(self, database_path: Path | str, *, minimum_votes: int = 1000) -> None:
        self.database_path = Path(database_path)
        self.minimum_votes = max(1000, int(minimum_votes))

    def extract(self) -> list[MovieRecord]:
        if not self.database_path.is_file():
            raise SourceNotConfigured(f"IMDb SQLite database not found: {self.database_path}")
        uri = f"file:{self.database_path.resolve().as_posix()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT
                    basics.tconst,
                    basics.primaryTitle,
                    basics.startYear,
                    basics.genres,
                    ratings.averageRating,
                    ratings.numVotes
                FROM title_basics AS basics
                INNER JOIN title_ratings AS ratings
                    ON ratings.tconst = basics.tconst
                WHERE (basics.genres LIKE '%Horror%' OR basics.genres LIKE '%Gore%')
                  AND ratings.numVotes >= ?
                  AND (basics.titleType IS NULL OR basics.titleType IN ('movie', 'tvMovie'))
                """,
                (self.minimum_votes,),
            ).fetchall()
        records: list[MovieRecord] = []
        for row in rows:
            raw = dict(row)
            record = normalize_movie_record(raw, self.name)
            if record is not None:
                records.append(record)
        return records