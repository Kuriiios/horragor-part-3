"""Polars lazy ingestion for one or more local Kaggle CSV datasets."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..models import MovieRecord
from ..normalization import normalize_movie_record
from .base import SourceDependencyError, SourceNotConfigured


class KaggleCsvSource:
    name = "kaggle"

    def __init__(self, paths: Sequence[Path | str]) -> None:
        self.paths = [Path(path) for path in paths]

    def extract(self) -> list[MovieRecord]:
        existing_paths = [path for path in self.paths if path.is_file()]
        if not existing_paths:
            raise SourceNotConfigured("No configured Kaggle CSV file exists")
        try:
            import polars as pl
        except ImportError as exc:
            raise SourceDependencyError(
                "Install the ingestion extra to use Polars CSV ingestion"
            ) from exc
        frames = [
            pl.scan_csv(path, infer_schema_length=10_000, ignore_errors=True)
            for path in existing_paths
        ]
        combined = pl.concat(frames, how="diagonal_relaxed").collect(engine="streaming")
        records: list[MovieRecord] = []
        for raw in combined.iter_rows(named=True):
            record = normalize_movie_record(dict(raw), self.name)
            if record is not None:
                records.append(record)
        return records