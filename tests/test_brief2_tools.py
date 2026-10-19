import unittest
from datetime import date
from unittest.mock import patch

from src.tools.brief2_tools import (
    ALL_TOOLS,
    MODEL_TOOL_SPECS,
    calculate_movie_age,
    find_similar_horror_movies,
    horror_survival_simulator,
    query_movie_metadata,
    scrape_detailed_synopsis,
)


class FakeMovieStore:
    def __init__(self) -> None:
        self.movie = {
            "id": "42", "title": "Test Possession", "release_date": "2012-08-30",
            "overview": "A family faces a demon and a curse in their new home.",
            "genre_names": "Horror, Thriller", "vote_average": "6.5", "runtime": "92",
            "cast": "[{'name': 'Lead Actor'}]", "crew": "[{'name': 'Director Name', 'job': 'Director'}]",
        }

    def get_by_id(self, movie_id: str | int) -> dict[str, str] | None:
        return self.movie if str(movie_id) == "42" else None

    def find_similar_by_overview(self, movie_id: str | int, limit: int) -> list[dict]:
        if str(movie_id) != "42":
            return []
        return [{"score": 0.8, "movie": {"id": "43", "title": "A Similar Film", "release_date": "2014-01-01", "genre_names": "Horror", "overview": "A related nightmare."}}][:limit]


class Brief2ToolTests(unittest.TestCase):
    def test_metadata_uses_a_resolved_id_and_returns_required_facts(self) -> None:
        with patch("src.tools.brief2_tools.get_movie_data_gateway", return_value=FakeMovieStore()):
            metadata = query_movie_metadata("42")

        if metadata is None:
            self.fail("Expected metadata for a known movie")
        self.assertEqual(metadata["title"], "Test Possession")
        self.assertEqual(metadata["director"], "Director Name")
        self.assertEqual(metadata["release_year"], 2012)
        self.assertEqual(metadata["cast"], ["Lead Actor"])

    def test_metadata_rejects_unknown_id_without_semantic_fallback(self) -> None:
        with patch("src.tools.brief2_tools.get_movie_data_gateway", return_value=FakeMovieStore()):
            self.assertIsNone(query_movie_metadata("not-a-movie-id"))

    def test_similarity_uses_the_resolved_id(self) -> None:
        with patch("src.tools.brief2_tools.get_movie_data_gateway", return_value=FakeMovieStore()):
            result = find_similar_horror_movies("42", k=20)

        if result is None:
            self.fail("Expected recommendations for a known movie")
        self.assertEqual(result["reference_movie"]["movie_id"], "42")
        self.assertEqual(result["recommendations"][0]["movie_id"], "43")
        self.assertIn("A Similar Film", result["summary"])
        self.assertIn("nightmare", result["summary"].lower())
        self.assertIn(result["recommendations"][0]["reason"], result["summary"])

    def test_similarity_reason_uses_shared_overview_elements(self) -> None:
        store = FakeMovieStore()
        store.find_similar_by_overview = lambda movie_id, limit: (
            [
                {
                    "score": 0.9,
                    "movie": {
                        "id": "43",
                        "title": "A Cursed Home",
                        "release_date": "2014-01-01",
                        "genre_names": "Horror",
                        "overview": "A family faces a demon and a curse in an old home.",
                    },
                }
            ][:limit]
            if str(movie_id) == "42"
            else []
        )

        with patch("src.tools.brief2_tools.get_movie_data_gateway", return_value=store):
            result = find_similar_horror_movies("42")

        if result is None:
            self.fail("Expected recommendations for a known movie")
        reason = result["recommendations"][0]["reason"]
        self.assertIn("demon", reason)
        self.assertIn("curse", reason)
        self.assertIn("both synopses", reason)

    def test_similarity_summary_handles_no_matches(self) -> None:
        store = FakeMovieStore()

        def no_similar_movies(movie_id: str | int, limit: int) -> list[dict]:
            self.assertEqual(str(movie_id), "42")
            self.assertEqual(limit, 5)
            return []

        store.find_similar_by_overview = no_similar_movies

        with patch("src.tools.brief2_tools.get_movie_data_gateway", return_value=store):
            result = find_similar_horror_movies("42")

        if result is None:
            self.fail("Expected an empty recommendation result for a known movie")
        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["summary"], "I could not find a similar horror movie for Test Possession.")

    def test_similarity_uses_the_overview_specific_store_method(self) -> None:
        store = FakeMovieStore()
        with patch("src.tools.brief2_tools.get_movie_data_gateway", return_value=store):
            find_similar_horror_movies("42")

        self.assertFalse(hasattr(store, "find_similar"))

    def test_age_calculator_uses_only_the_supplied_release_year(self) -> None:
        self.assertEqual(calculate_movie_age(2012, as_of=date(2026, 8, 26))["age_years"], 14)

    def test_survival_simulator_uses_the_supplied_synopsis_and_is_fictional(self) -> None:
        result = horror_survival_simulator("A family is haunted by a demon after opening a cursed box.")

        self.assertTrue(result["fictional"])
        self.assertIn("Demonic force", result["primary_threats"])

    def test_model_exposes_exactly_the_five_brief_tools(self) -> None:
        expected = {"query_movie_metadata", "find_similar_horror_movies", "scrape_detailed_synopsis", "calculate_movie_age", "horror_survival_simulator"}
        self.assertEqual({tool.__name__ for tool in ALL_TOOLS}, expected)
        self.assertEqual({spec["name"] for spec in MODEL_TOOL_SPECS}, expected)
        self.assertIn(scrape_detailed_synopsis, ALL_TOOLS)


if __name__ == "__main__":
    unittest.main()