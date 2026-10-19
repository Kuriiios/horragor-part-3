import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tools.faiss_store import MovieFaissStore


class OverviewSimilarityTests(unittest.TestCase):
    def test_searches_return_empty_when_index_loading_does_not_produce_an_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            store = MovieFaissStore(
                csv_path=root / "missing.csv",
                index_dir=root / "index",
                dimension=64,
            )
            with patch.object(store, "_ensure_loaded", return_value=None):
                self.assertEqual(store.search("Alien"), [])
                self.assertEqual(store.find_similar("1"), [])

    def test_similarity_ignores_shared_title_words_and_uses_overviews(self) -> None:
        records = [
            {
                "id": "1",
                "title": "Night House",
                "overview": "A family becomes trapped with a demon in an ancient house.",
            },
            {
                "id": "2",
                "title": "Night House Returns",
                "overview": "Astronauts perform a cheerful comedy mission on Mars.",
            },
            {
                "id": "3",
                "title": "The Demon Below",
                "overview": "A family becomes trapped with a demon in an ancient house.",
            },
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            csv_path = root / "movies.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=["id", "title", "overview"])
                writer.writeheader()
                writer.writerows(records)
            store = MovieFaissStore(csv_path=csv_path, index_dir=root / "index", dimension=64)

            results = store.find_similar_by_overview("1", limit=1)

        self.assertEqual(results[0]["movie"]["id"], "3")