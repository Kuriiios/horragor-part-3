import csv
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.ingestion.models import MovieRecord
from src.ingestion.pipeline import IngestionSettings, extract_in_parallel, run_pipeline
from src.ingestion.sources import (
    ImdbSqliteSource,
    KaggleCsvSource,
    RottenTomatoesSource,
    TmdbSource,
)


class FakeSource:
    def __init__(self, name: str, records: list[MovieRecord]) -> None:
        self.name = name
        self.records = records

    def extract(self) -> list[MovieRecord]:
        return list(self.records)


class IngestionSourceTests(unittest.TestCase):
    def test_tmdb_source_uses_bounded_horror_discovery(self) -> None:
        response = Mock()
        response.json.return_value = {
            "results": [
                {
                    "id": 10,
                    "title": "Mock Horror",
                    "release_date": "2020-01-02",
                    "overview": "Dark evidence.",
                }
            ],
            "total_pages": 1,
        }
        session = Mock()
        session.get.return_value = response

        records = TmdbSource(api_key="key", pages=20, session=session).extract()

        self.assertEqual(records[0].tmdb_id, "10")
        self.assertEqual(records[0].genres, ("Horror",))
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(session.get.call_args.kwargs["params"]["with_genres"], "27")

    def test_sqlite_source_applies_horror_and_vote_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "imdb.db"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    "CREATE TABLE title_basics(tconst TEXT, titleType TEXT, primaryTitle TEXT, startYear TEXT, genres TEXT)"
                )
                connection.execute(
                    "CREATE TABLE title_ratings(tconst TEXT, averageRating REAL, numVotes INTEGER)"
                )
                connection.executemany(
                    "INSERT INTO title_basics VALUES (?, 'movie', ?, '1999', ?)",
                    [
                        ("tt1", "Included Horror", "Horror"),
                        ("tt2", "Low Vote Horror", "Horror"),
                        ("tt3", "Popular Comedy", "Comedy"),
                    ],
                )
                connection.executemany(
                    "INSERT INTO title_ratings VALUES (?, 7.1, ?)",
                    [("tt1", 1500), ("tt2", 999), ("tt3", 5000)],
                )

            records = ImdbSqliteSource(database).extract()

        self.assertEqual([record.imdb_id for record in records], ["tt1"])
        self.assertEqual(records[0].release_date, "1999-01-01")

    def test_polars_source_filters_and_normalizes_local_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kaggle.csv"
            with path.open("w", encoding="utf-8", newline="") as output:
                writer = csv.DictWriter(
                    output,
                    fieldnames=["title", "year", "genre", "synopsis"],
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "title": "CSV Horror",
                            "year": "2002",
                            "genre": "Horror",
                            "synopsis": "<p>Dark evidence.</p>",
                        },
                        {
                            "title": "CSV Comedy",
                            "year": "2002",
                            "genre": "Comedy",
                            "synopsis": "A joke.",
                        },
                    ]
                )

            records = KaggleCsvSource([path]).extract()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].title, "CSV Horror")
        self.assertEqual(records[0].overview, "Dark evidence.")

    def test_selenium_source_captures_scores_year_consensus_and_provenance(self) -> None:
        class Card:
            text = "Mock Horror 92% 81%"

            def find_element(self, _, selector):
                values = {
                    "[data-qa='discovery-media-list-item-title']": SimpleNamespace(
                        text="Mock Horror"
                    ),
                    "score-pairs": SimpleNamespace(text="92% 81%"),
                    "[data-qa='discovery-media-list-item-start-date']": SimpleNamespace(
                        text="Streaming Jan 1, 2022"
                    ),
                    "a": SimpleNamespace(
                        text="",
                        get_attribute=lambda _: "https://www.rottentomatoes.com/m/mock_horror",
                    ),
                }
                if selector not in values:
                    raise RuntimeError("not found")
                return values[selector]

        driver = Mock()
        driver.find_element.side_effect = lambda _, selector: (
            SimpleNamespace(text="A chilling and precise nightmare.")
            if selector == "[data-qa='score-panel-critics-consensus']"
            else (_ for _ in ()).throw(RuntimeError("not found"))
        )
        wait = Mock()
        wait.until.return_value = [Card()]
        with patch("selenium.webdriver.support.ui.WebDriverWait", return_value=wait):
            records = RottenTomatoesSource(
                max_items=1,
                driver_factory=lambda: driver,
            ).extract()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].release_date, "2022-01-01")
        self.assertEqual(records[0].tomatometer_score, 92.0)
        self.assertEqual(records[0].audience_score, 81.0)
        self.assertEqual(
            records[0].attributes["critics_consensus"],
            "A chilling and precise nightmare.",
        )
        self.assertIn("rottentomatoes.com", records[0].attributes["source_url"])
        driver.quit.assert_called_once_with()

    def test_pipeline_publishes_reconciled_csv_and_reports_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configuration = replace(
                IngestionSettings.from_environment(),
                output_csv=root / "gold.csv",
                index_dir=root / "index",
            )
            sources = [
                FakeSource(
                    "tmdb",
                    [
                        MovieRecord(
                            source="tmdb",
                            tmdb_id="10",
                            title="Mock Horror",
                            release_date="2020-01-02",
                            genres=("Horror",),
                        )
                    ],
                ),
                FakeSource(
                    "kaggle",
                    [
                        MovieRecord(
                            source="kaggle",
                            title="Mock Horror",
                            release_date="2020-01-02",
                            genres=("Horror",),
                            overview="A complete synopsis.",
                        )
                    ],
                ),
            ]

            report = run_pipeline(
                configuration,
                sources=sources,
                rebuild_index=False,
            )
            with configuration.output_csv.open(encoding="utf-8", newline="") as input_file:
                rows = list(csv.DictReader(input_file))

        self.assertEqual(report.canonical_count, 1)
        self.assertEqual({item.status for item in report.source_reports}, {"success"})
        self.assertEqual(rows[0]["id"], "10")
        self.assertEqual(rows[0]["overview"], "A complete synopsis.")

    def test_parallel_extraction_strict_mode_reports_failures(self) -> None:
        failing_source = Mock(name="broken-source")
        failing_source.name = "broken"
        failing_source.extract.side_effect = RuntimeError("boom")

        records, reports = extract_in_parallel([failing_source])

        self.assertEqual(records, [])
        self.assertEqual(reports[0].status, "failed")
        with self.assertRaises(RuntimeError):
            extract_in_parallel([failing_source], strict=True)


if __name__ == "__main__":
    unittest.main()