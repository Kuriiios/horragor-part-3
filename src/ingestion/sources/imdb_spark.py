"""PySpark processing for split high-volume IMDb basics and ratings files."""

from __future__ import annotations

from pathlib import Path

from ..models import MovieRecord
from ..normalization import normalize_movie_record
from .base import SourceDependencyError, SourceNotConfigured


class ImdbSparkSource:
    name = "spark"

    def __init__(
        self,
        basics_path: Path | str,
        ratings_path: Path | str,
        *,
        minimum_votes: int = 1000,
        app_name: str = "horragor-imdb-ingestion",
    ) -> None:
        self.basics_path = Path(basics_path)
        self.ratings_path = Path(ratings_path)
        self.minimum_votes = max(1000, int(minimum_votes))
        self.app_name = app_name

    def extract(self) -> list[MovieRecord]:
        if not self.basics_path.exists() or not self.ratings_path.exists():
            raise SourceNotConfigured("IMDb Spark basics and ratings paths are required")
        try:
            from pyspark.sql import SparkSession
            from pyspark.sql import functions as functions
        except ImportError as exc:
            raise SourceDependencyError(
                "Install the ingestion extra and Java to use PySpark ingestion"
            ) from exc

        spark = SparkSession.builder.appName(self.app_name).getOrCreate()
        try:
            basics = spark.read.option("header", True).option("sep", "\t").csv(
                str(self.basics_path)
            )
            ratings = spark.read.option("header", True).option("sep", "\t").csv(
                str(self.ratings_path)
            )
            horror = basics.filter(
                functions.col("genres").rlike(r"(^|,)(Horror|Gore)(,|$)")
            ).filter(
                functions.col("titleType").isin("movie", "tvMovie")
            )
            joined = horror.join(ratings, on="tconst", how="inner").filter(
                functions.col("numVotes").cast("long") >= self.minimum_votes
            )
            records: list[MovieRecord] = []
            for row in joined.toLocalIterator():
                record = normalize_movie_record(row.asDict(recursive=True), self.name)
                if record is not None:
                    records.append(record)
            return records
        finally:
            spark.stop()