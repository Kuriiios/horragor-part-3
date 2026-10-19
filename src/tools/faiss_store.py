"""Persistent FAISS retrieval for the aggregated movie dataset.

The FAISS index stores normalized text vectors. Complete movie rows live in a
JSON sidecar because FAISS only stores vectors and numeric labels.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path
from threading import RLock
from typing import Any

import faiss
import numpy as np

from ..logging_config import configure_logging

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV_PATH = PROJECT_ROOT / "data" / "aggregated_movies.csv"
DEFAULT_INDEX_DIR = PROJECT_ROOT / "data" / "faiss_index"

INDEX_FILENAME = "movies.index"
METADATA_FILENAME = "movies.json"
MANIFEST_FILENAME = "manifest.json"
INDEX_FORMAT_VERSION = 2
DEFAULT_DIMENSION = 768

_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_MISSING_VALUES = {"", "na", "n/a", "nan", "none", "null"}
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

# Synopsis fields carry the strongest retrieval signal. Keywords and genres
# help route broad questions without making the index depend on a database.
_SEARCH_FIELDS = (
    ("title", 8.0),
    ("overview", 4.0),
    ("tagline", 2.0),
    ("genre_names", 2.0),
    ("keywords", 1.0),
)


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(text.casefold().split())


def _tokens(value: Any) -> list[str]:
    return _TOKEN_PATTERN.findall(_normalize_text(value))


def _is_explicit_title_reference(query: str, title: str) -> bool:
    """Match complete titles without promoting ordinary words to titles."""
    normalized_query = _normalize_text(query)
    normalized_title = _normalize_text(title)
    query_tokens = _tokens(normalized_query)
    title_tokens = _tokens(normalized_title)
    if query_tokens == title_tokens:
        return True
    if not title_tokens:
        return False

    pattern = rf"(?<!\w){re.escape(normalized_title)}(?!\w)"
    for match in re.finditer(pattern, normalized_query):
        before = _tokens(normalized_query[: match.start()])
        after = _tokens(normalized_query[match.end() :])
        if before and before[-1] in _TITLE_REFERENCE_CUES:
            return True
        if (
            after
            and after[0] in _TITLE_REFERENCE_CUES
            and not (not before and len(title_tokens) == 1 and title_tokens[0] in _QUESTION_LEADING_WORDS)
        ):
            return True
    return False


def _feature_index(feature: str, dimension: int) -> int:
    digest = hashlib.blake2b(
        feature.encode("utf-8"), digest_size=8, person=b"horragor"
    ).digest()
    return int.from_bytes(digest, byteorder="little") % dimension


def _add_feature(vector: np.ndarray, feature: str, weight: float) -> None:
    vector[_feature_index(feature, vector.shape[0])] += weight


def _vectorize_record(record: dict[str, str], dimension: int) -> np.ndarray:
    vector = np.zeros(dimension, dtype=np.float32)

    for field, weight in _SEARCH_FIELDS:
        field_tokens = _tokens(record.get(field, ""))
        for token in field_tokens:
            _add_feature(vector, token, weight)

        for first, second in zip(field_tokens, field_tokens[1:], strict=False):
            _add_feature(vector, f"bigram:{first}:{second}", weight * 0.75)

    _normalize_vector(vector)
    return vector


def _vectorize_overview(overview: str, dimension: int) -> np.ndarray:
    """Build a similarity vector from synopsis text without title features."""
    vector = np.zeros(dimension, dtype=np.float32)
    overview_tokens = _tokens(overview)
    for token in overview_tokens:
        _add_feature(vector, token, 1.0)
    for first, second in zip(overview_tokens, overview_tokens[1:], strict=False):
        _add_feature(vector, f"bigram:{first}:{second}", 0.75)
    _normalize_vector(vector)
    return vector


def _vectorize_query(query: str, dimension: int) -> np.ndarray:
    vector = np.zeros(dimension, dtype=np.float32)
    query_tokens = _tokens(query)

    for token in query_tokens:
        _add_feature(vector, token, 1.0)

    for first, second in zip(query_tokens, query_tokens[1:], strict=False):
        _add_feature(vector, f"bigram:{first}:{second}", 0.75)

    _normalize_vector(vector)
    return vector


def _normalize_vector(vector: np.ndarray) -> None:
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector /= norm


def _clean_record(row: dict[str | None, str | None]) -> dict[str, str]:
    return {
        key.lstrip("\ufeff"): " ".join(str(value or "").split())
        for key, value in row.items()
        if key is not None
    }


def _read_movie_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.is_file():
        raise FileNotFoundError(f"Movie CSV not found: {csv_path}")

    records: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = {field.lstrip("\ufeff") for field in (reader.fieldnames or [])}
        missing_fields = {"id", "title"} - fieldnames
        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise ValueError(f"Movie CSV is missing required columns: {missing}")

        for row in reader:
            record = _clean_record(row)
            movie_id = _normalize_text(record.get("id"))
            title = record.get("title", "").strip()
            if movie_id in _MISSING_VALUES or not title:
                continue
            if movie_id in seen_ids:
                logger.warning("Skipping duplicate movie id: %s", movie_id)
                continue

            seen_ids.add(movie_id)
            records.append(record)

    if not records:
        raise ValueError(f"Movie CSV contains no usable records: {csv_path}")

    return records


class MovieFaissStore:
    """Load, build, and query the persistent movie FAISS index."""

    def __init__(
        self,
        csv_path: Path | str = DEFAULT_CSV_PATH,
        index_dir: Path | str = DEFAULT_INDEX_DIR,
        dimension: int = DEFAULT_DIMENSION,
    ) -> None:
        if dimension < 32:
            raise ValueError("FAISS vector dimension must be at least 32")

        self.csv_path = Path(csv_path).resolve()
        self.index_dir = Path(index_dir).resolve()
        self.dimension = dimension
        self.index_path = self.index_dir / INDEX_FILENAME
        self.metadata_path = self.index_dir / METADATA_FILENAME
        self.manifest_path = self.index_dir / MANIFEST_FILENAME
        self._lock = RLock()
        self._index: faiss.Index | None = None
        self._overview_index: faiss.Index | None = None
        self._records: list[dict[str, str]] = []
        self._id_to_position: dict[str, int] = {}
        self._title_to_positions: dict[str, list[int]] = {}

    @property
    def count(self) -> int:
        self._ensure_loaded()
        with self._lock:
            return len(self._records)

    def stats(self) -> dict[str, Any]:
        self._ensure_loaded()
        with self._lock:
            return {
                "records": len(self._records),
                "dimension": self.dimension,
                "index_path": str(self.index_path),
                "metadata_path": str(self.metadata_path),
                "source_path": str(self.csv_path),
            }

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return the closest movie rows ordered by cosine similarity."""
        if not _normalize_text(query):
            return []
        if limit < 1:
            return []

        self._ensure_loaded()
        with self._lock:
            index = self._index
            if index is None:
                logger.error("FAISS movie index is unavailable after loading")
                return []
            results: list[dict[str, Any]] = []
            exact_positions = self._find_title_matches(query)
            for position in exact_positions[:limit]:
                results.append({"score": 1.0, "movie": self._records[position]})

            remaining = limit - len(results)
            if remaining <= 0:
                return results

            query_vector = _vectorize_query(query, self.dimension).reshape(1, -1)
            scores, labels = index.search(
                query_vector,
                min(remaining + len(exact_positions), len(self._records)),
            )
            matched_positions = set(exact_positions)
            for score, label in zip(scores[0], labels[0], strict=True):
                if label < 0:
                    continue
                position = int(label)
                if position in matched_positions:
                    continue
                results.append(
                    {
                        "score": float(score),
                        "movie": self._records[position],
                    }
                )
                matched_positions.add(position)
                if len(results) == limit:
                    break
            return results

    def _find_title_matches(self, query: str) -> list[int]:
        normalized_query = _normalize_text(query)
        if not normalized_query:
            return []

        matches: list[int] = []
        for normalized_title in sorted(
            self._title_to_positions, key=len, reverse=True
        ):
            positions = self._title_to_positions[normalized_title]
            if _is_explicit_title_reference(normalized_query, normalized_title):
                matches.extend(positions)
        return matches

    def get_by_id(self, movie_id: str | int) -> dict[str, str] | None:
        """Return a movie row by its source CSV id."""
        self._ensure_loaded()
        with self._lock:
            position = self._id_to_position.get(_normalize_text(movie_id))
            return dict(self._records[position]) if position is not None else None

    def get_by_title(self, title: str) -> dict[str, str] | None:
        """Return the first movie row whose title matches exactly."""
        self._ensure_loaded()
        with self._lock:
            positions = self._title_to_positions.get(_normalize_text(title), [])
            return dict(self._records[positions[0]]) if positions else None

    def all_movies(self) -> list[dict[str, str]]:
        """Return clean copies of every indexed movie for safe catalog scans."""
        self._ensure_loaded()
        with self._lock:
            return [dict(record) for record in self._records]

    def find_similar(self, movie_id: str | int, limit: int = 5) -> list[dict[str, Any]]:
        """Return nearest indexed movies for a known movie id."""
        if limit < 1:
            return []

        self._ensure_loaded()
        with self._lock:
            index = self._index
            if index is None:
                logger.error("FAISS movie index is unavailable after loading")
                return []
            position = self._id_to_position.get(_normalize_text(movie_id))
            if position is None:
                return []

            query_vector = index.reconstruct(position).reshape(1, -1)
            scores, labels = index.search(
                query_vector, min(limit + 1, len(self._records))
            )
            results: list[dict[str, Any]] = []
            for score, label in zip(scores[0], labels[0], strict=True):
                if label < 0 or int(label) == position:
                    continue
                results.append(
                    {
                        "score": float(score),
                        "movie": self._records[int(label)],
                    }
                )
                if len(results) == limit:
                    break
            return results

    def find_similar_by_overview(
        self,
        movie_id: str | int,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return closest movies using synopsis vectors only, never titles."""
        if limit < 1:
            return []

        self._ensure_loaded()
        with self._lock:
            position = self._id_to_position.get(_normalize_text(movie_id))
            if position is None or not _normalize_text(
                self._records[position].get("overview")
            ):
                return []

            overview_index = self._get_overview_index()
            query_vector = overview_index.reconstruct(position).reshape(1, -1)
            scores, labels = overview_index.search(
                query_vector,
                min(limit + 1, len(self._records)),
            )
            results: list[dict[str, Any]] = []
            for score, label in zip(scores[0], labels[0], strict=True):
                if label < 0 or int(label) == position:
                    continue
                results.append(
                    {
                        "score": float(score),
                        "movie": self._records[int(label)],
                    }
                )
                if len(results) == limit:
                    break
            return results

    def rebuild(self) -> dict[str, Any]:
        """Rebuild all persisted artifacts from the current CSV."""
        with self._lock:
            return self._build_unlocked()

    def _ensure_loaded(self) -> None:
        if self._index is not None:
            return

        with self._lock:
            if self._index is not None:
                return
            if self._load_if_current():
                return
            logger.info("Building FAISS movie index from %s", self.csv_path)
            self._build_unlocked()

    def _source_signature(self) -> dict[str, int]:
        source_stat = self.csv_path.stat()
        return {
            "size": source_stat.st_size,
            "mtime_ns": source_stat.st_mtime_ns,
        }

    def _load_if_current(self) -> bool:
        if not all(
            path.is_file()
            for path in (self.index_path, self.metadata_path, self.manifest_path)
        ):
            return False

        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            source_signature = self._source_signature()
            if (
                manifest.get("format_version") != INDEX_FORMAT_VERSION
                or manifest.get("dimension") != self.dimension
                or manifest.get("source") != source_signature
            ):
                return False

            index = faiss.read_index(str(self.index_path))
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            records = payload.get("records")
            if (
                not isinstance(records, list)
                or not all(isinstance(record, dict) for record in records)
                or index.ntotal != len(records)
                or index.d != self.dimension
                or self._source_signature() != source_signature
            ):
                return False

            self._index = index
            self._overview_index = None
            self._records = records
            self._id_to_position = {
                _normalize_text(record.get("id")): position
                for position, record in enumerate(records)
            }
            self._title_to_positions = self._build_title_map(records)
            return True
        except (OSError, ValueError, TypeError, json.JSONDecodeError, RuntimeError) as exc:
            logger.warning("Unable to load persisted FAISS artifacts: %s", exc)
            return False

    def _build_unlocked(self) -> dict[str, Any]:
        source_signature = self._source_signature()
        records = _read_movie_rows(self.csv_path)
        if self._source_signature() != source_signature:
            raise RuntimeError("Movie CSV changed while the FAISS index was being built")
        vectors = np.vstack(
            [_vectorize_record(record, self.dimension) for record in records]
        ).astype(np.float32, copy=False)
        index = faiss.IndexFlatIP(self.dimension)
        index.add(vectors)
        manifest = {
            "format_version": INDEX_FORMAT_VERSION,
            "dimension": self.dimension,
            "record_count": len(records),
            "source": source_signature,
        }

        self.index_dir.mkdir(parents=True, exist_ok=True)
        temporary_dir = Path(tempfile.mkdtemp(prefix=".faiss-build-", dir=self.index_dir))
        try:
            temporary_index = temporary_dir / INDEX_FILENAME
            temporary_metadata = temporary_dir / METADATA_FILENAME
            temporary_manifest = temporary_dir / MANIFEST_FILENAME
            faiss.write_index(index, str(temporary_index))
            temporary_metadata.write_text(
                json.dumps({"records": records}, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            temporary_manifest.write_text(
                json.dumps(manifest, indent=2),
                encoding="utf-8",
            )

            for temporary_path, target_path in (
                (temporary_index, self.index_path),
                (temporary_metadata, self.metadata_path),
                (temporary_manifest, self.manifest_path),
            ):
                os.replace(temporary_path, target_path)
        finally:
            shutil.rmtree(temporary_dir, ignore_errors=True)

        self._index = index
        self._overview_index = None
        self._records = records
        self._id_to_position = {
            _normalize_text(record["id"]): position
            for position, record in enumerate(records)
        }
        self._title_to_positions = self._build_title_map(records)
        logger.info("FAISS movie index ready with %d records", len(records))
        return self.stats()

    def _get_overview_index(self) -> faiss.Index:
        """Create a lazily cached FAISS index containing overview text only."""
        overview_index = self._overview_index
        if overview_index is not None:
            return overview_index
        with self._lock:
            overview_index = self._overview_index
            if overview_index is None:
                vectors = np.vstack(
                    [
                        _vectorize_overview(record.get("overview", ""), self.dimension)
                        for record in self._records
                    ]
                ).astype(np.float32, copy=False)
                overview_index = faiss.IndexFlatIP(self.dimension)
                overview_index.add(vectors)
                self._overview_index = overview_index
        return overview_index

    @staticmethod
    def _build_title_map(records: list[dict[str, str]]) -> dict[str, list[int]]:
        title_to_positions: dict[str, list[int]] = {}
        for position, record in enumerate(records):
            normalized_title = _normalize_text(record.get("title"))
            if normalized_title:
                title_to_positions.setdefault(normalized_title, []).append(position)
        return title_to_positions


_store: MovieFaissStore | None = None
_store_lock = RLock()


def get_movie_store() -> MovieFaissStore:
    """Return the process-wide store configured by environment variables."""
    global _store
    csv_path = Path(os.getenv("MOVIES_CSV_PATH", str(DEFAULT_CSV_PATH)))
    index_dir = Path(os.getenv("FAISS_INDEX_DIR", str(DEFAULT_INDEX_DIR)))
    with _store_lock:
        if _store is None or _store.csv_path != csv_path.resolve() or _store.index_dir != index_dir.resolve():
            _store = MovieFaissStore(csv_path=csv_path, index_dir=index_dir)
        return _store


def main() -> None:
    configure_logging("faiss-indexer")
    parser = argparse.ArgumentParser(description="Build the HorRAGor movie FAISS index")
    parser.add_argument("--csv-path", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--dimension", type=int, default=DEFAULT_DIMENSION)
    args = parser.parse_args()
    store = MovieFaissStore(
        csv_path=args.csv_path,
        index_dir=args.index_dir,
        dimension=args.dimension,
    )
    print(json.dumps(store.rebuild(), indent=2))


if __name__ == "__main__":
    main()