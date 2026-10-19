import unittest

from src.ingestion.normalization import clean_text, normalize_date, normalize_movie_record
from src.ingestion.reconciliation import reconcile_movies


class IngestionNormalizationTests(unittest.TestCase):
    def test_text_and_dates_are_normalized(self) -> None:
        self.assertEqual(clean_text(" <p>Caf&eacute;   noir</p> "), "Café noir")
        self.assertEqual(normalize_date("1999"), "1999-01-01")
        self.assertEqual(normalize_date("31/10/2004"), "2004-10-31")

    def test_non_horror_and_invalid_scores_are_rejected(self) -> None:
        self.assertIsNone(
            normalize_movie_record(
                {"id": 1, "title": "A Comedy", "genres": ["Comedy"]},
                "tmdb",
            )
        )
        record = normalize_movie_record(
            {
                "id": 2,
                "title": "A Horror",
                "genres": [{"name": "Horror"}],
                "release_date": "2020-01-02",
                "vote_average": 20,
                "tomatometer_score": "87%",
            },
            "tmdb",
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertIsNone(record.vote_average)
        self.assertEqual(record.tomatometer_score, 87.0)


class ReconciliationTests(unittest.TestCase):
    def test_priority_ids_and_fuzzy_title_year_produce_one_gold_record(self) -> None:
        tmdb = normalize_movie_record(
            {
                "id": "10",
                "imdb_id": "tt0000010",
                "title": "The Haunted House",
                "release_date": "2001-03-01",
                "genres": ["Horror"],
                "vote_average": 7.2,
            },
            "tmdb",
        )
        rotten_tomatoes = normalize_movie_record(
            {
                "imdb_id": "tt0000010",
                "title": "Haunted House",
                "year": 2001,
                "genres": ["Horror"],
                "tomatometer_score": 91,
                "audience_score": 84,
            },
            "rotten_tomatoes",
        )
        kaggle = normalize_movie_record(
            {
                "title": "The Hounted House",
                "year": 2001,
                "genres": "Horror|Thriller",
                "synopsis": "<p>A family enters a haunted home.</p>",
            },
            "kaggle",
        )
        records = [record for record in (kaggle, rotten_tomatoes, tmdb) if record]

        movies = reconcile_movies(records, fuzzy_threshold=0.8)

        self.assertEqual(len(movies), 1)
        movie = movies[0]
        self.assertEqual(movie.title, "The Haunted House")
        self.assertEqual(movie.tmdb_id, "10")
        self.assertEqual(movie.overview, "A family enters a haunted home.")
        self.assertEqual(movie.tomatometer_score, 91.0)
        self.assertEqual(movie.sources, ["tmdb", "rotten_tomatoes", "kaggle"])

    def test_same_title_in_different_years_stays_distinct(self) -> None:
        records = [
            normalize_movie_record(
                {"id": str(year), "title": "The Thing", "year": year, "genres": "Horror"},
                "tmdb",
            )
            for year in (1982, 2011)
        ]

        movies = reconcile_movies(record for record in records if record)

        self.assertEqual(len(movies), 2)


if __name__ == "__main__":
    unittest.main()