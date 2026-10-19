"""Parallel Brief 1 acquisition and deterministic gold-data publication."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import tempfile
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from ..logging_config import configure_logging
from ..tools.faiss_store import DEFAULT_INDEX_DIR, MovieFaissStore
from .models import CanonicalMovie, MovieRecord
from .reconciliation import reconcile_movies
from .sources import (
    ImdbSparkSource,
    ImdbSqliteSource,
    KaggleCsvSource,
    MovieSource,
    RottenTomatoesSource,
    SourceDependencyError,
    SourceNotConfigured,
    TmdbSource,
)

logger = logging.getLogger(__name__)


class MovieRepository(Protocol):
    def upsert_movies(self, movies: Sequence[CanonicalMovie]) -> int: ...


@dataclass(frozen=True)
class IngestionSettings:
    output_csv: Path
    index_dir: Path
    tmdb_bearer_token: str | None
    tmdb_api_key: str | None
    tmdb_pages: int
    rotten_tomatoes_enabled: bool
    rotten_tomatoes_url: str
    kaggle_csv_paths: tuple[Path, ...]
    imdb_sqlite_path: Path | None
    spark_basics_path: Path | None
    spark_ratings_path: Path | None

    @classmethod
    def from_environment(cls) -> IngestionSettings:
        project_root = Path(__file__).resolve().parents[2]
        kaggle_paths = tuple(
            Path(path.strip())
            for path in os.getenv("KAGGLE_CSV_PATHS", "").split(os.pathsep)
            if path.strip()
        )

        def optional_path(name: str) -> Path | None:
            value = os.getenv(name, "").strip()
            return Path(value) if value else None

        return cls(
            output_csv=Path(
                os.getenv(
                    "HORRAGOR_GOLD_CSV_PATH",
                    str(project_root / "data" / "aggregated_movies.csv"),
                )
            ),
            index_dir=Path(os.getenv("FAISS_INDEX_DIR", str(DEFAULT_INDEX_DIR))),
            tmdb_bearer_token=os.getenv("TMDB_BEARER_TOKEN", "").strip() or None,
            tmdb_api_key=os.getenv("TMDB_API_KEY", "").strip() or None,
            tmdb_pages=max(1, min(int(os.getenv("TMDB_PAGES", "5")), 50)),
            rotten_tomatoes_enabled=os.getenv(
                "ENABLE_ROTTEN_TOMATOES_SCRAPER", "false"
            ).strip().casefold()
            in {"1", "true", "yes", "on"},
            rotten_tomatoes_url=os.getenv(
                "ROTTEN_TOMATOES_HORROR_URL",
                "https://www.rottentomatoes.com/browse/movies_at_home/genres:horror",
            ),
            kaggle_csv_paths=kaggle_paths,
            imdb_sqlite_path=optional_path("IMDB_SQLITE_PATH"),
            spark_basics_path=optional_path("IMDB_SPARK_BASICS_PATH"),
            spark_ratings_path=optional_path("IMDB_SPARK_RATINGS_PATH"),
        )


@dataclass(frozen=True)
class SourceReport:
    source: str
    status: str
    record_count: int
    duration_ms: float
    error: str | None = None


@dataclass(frozen=True)
class PipelineReport:
    source_reports: tuple[SourceReport, ...]
    canonical_count: int
    output_csv: str
    index_records: int | None
    persisted_records: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def configured_sources(configuration: IngestionSettings) -> list[MovieSource]:
    """Build only explicitly configured external adapters."""
    sources: list[MovieSource] = []
    if configuration.tmdb_bearer_token or configuration.tmdb_api_key:
        sources.append(
            TmdbSource(
                bearer_token=configuration.tmdb_bearer_token,
                api_key=configuration.tmdb_api_key,
                pages=configuration.tmdb_pages,
            )
        )
    if configuration.rotten_tomatoes_enabled:
        sources.append(RottenTomatoesSource(url=configuration.rotten_tomatoes_url))
    if configuration.kaggle_csv_paths:
        sources.append(KaggleCsvSource(configuration.kaggle_csv_paths))
    if configuration.imdb_sqlite_path:
        sources.append(ImdbSqliteSource(configuration.imdb_sqlite_path))
    if configuration.spark_basics_path and configuration.spark_ratings_path:
        sources.append(
            ImdbSparkSource(
                configuration.spark_basics_path,
                configuration.spark_ratings_path,
            )
        )
    return sources


def _extract_one(source: MovieSource) -> tuple[list[MovieRecord], SourceReport]:
    started_at = time.perf_counter()
    try:
        records = source.extract()
        report = SourceReport(
            source=source.name,
            status="success",
            record_count=len(records),
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        return records, report
    except (SourceNotConfigured, SourceDependencyError) as exc:
        return [], SourceReport(
            source=source.name,
            status="skipped",
            record_count=0,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            error=str(exc),
        )
    except Exception as exc:
        logger.exception("Ingestion source %s failed", source.name)
        return [], SourceReport(
            source=source.name,
            status="failed",
            record_count=0,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            error=f"{type(exc).__name__}: {exc}",
        )


def extract_in_parallel(
    sources: Sequence[MovieSource],
    *,
    strict: bool = False,
) -> tuple[list[MovieRecord], tuple[SourceReport, ...]]:
    """Run independent channels concurrently and return deterministic reports."""
    if not sources:
        raise SourceNotConfigured("No ingestion source is configured")
    all_records: list[MovieRecord] = []
    reports: list[SourceReport] = []
    with ThreadPoolExecutor(max_workers=min(5, len(sources))) as executor:
        futures = {executor.submit(_extract_one, source): source.name for source in sources}
        for future in as_completed(futures):
            records, report = future.result()
            all_records.extend(records)
            reports.append(report)
    reports.sort(key=lambda report: report.source)
    if strict:
        failed = [report for report in reports if report.status != "success"]
        if failed:
            summary = "; ".join(f"{report.source}: {report.error}" for report in failed)
            raise RuntimeError(f"Strict ingestion failed: {summary}")
    return all_records, tuple(reports)


def write_gold_csv(movies: Sequence[CanonicalMovie], output_path: Path) -> None:
    """Atomically replace the gold CSV after every row is fully serialized."""
    if not movies:
        raise ValueError("Refusing to publish an empty gold dataset")
    rows = [movie.to_row() for movie in movies]
    preferred_fields = [
        "id", "tmdb_id", "imdb_id", "title", "release_date", "genre_names", "overview",
        "tagline", "vote_average", "imdb_rating", "tomatometer_score", "audience_score",
        "popularity", "poster_path", "budget", "revenue", "runtime", "cast", "crew", "sources",
    ]
    extra_fields = sorted(set().union(*(row.keys() for row in rows)) - set(preferred_fields))
    fieldnames = preferred_fields + extra_fields
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, output_path)
    except Exception:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name)
        raise


def run_pipeline(
    configuration: IngestionSettings,
    *,
    sources: Sequence[MovieSource] | None = None,
    repository: MovieRepository | None = None,
    strict: bool = False,
    rebuild_index: bool = True,
) -> PipelineReport:
    """Execute extraction, reconciliation, persistence, and index publication."""
    records, source_reports = extract_in_parallel(
        list(sources) if sources is not None else configured_sources(configuration),
        strict=strict,
    )
    movies = reconcile_movies(records)
    write_gold_csv(movies, configuration.output_csv)
    persisted_records = repository.upsert_movies(movies) if repository else None
    index_records: int | None = None
    if rebuild_index:
        stats = MovieFaissStore(
            csv_path=configuration.output_csv,
            index_dir=configuration.index_dir,
        ).rebuild()
        index_records = int(stats["records"])
    return PipelineReport(
        source_reports=source_reports,
        canonical_count=len(movies),
        output_csv=str(configuration.output_csv),
        index_records=index_records,
        persisted_records=persisted_records,
    )


def main() -> None:
    configure_logging("ingestion")
    parser = argparse.ArgumentParser(description="Build HorRAGor's reconciled gold dataset")
    parser.add_argument("--strict", action="store_true", help="Fail if any configured source fails")
    parser.add_argument("--no-rebuild-index", action="store_true")
    arguments = parser.parse_args()
    from ..persistence import repository_from_environment

    report = run_pipeline(
        IngestionSettings.from_environment(),
        repository=repository_from_environment(),
        strict=arguments.strict,
        rebuild_index=not arguments.no_rebuild_index,
    )
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()