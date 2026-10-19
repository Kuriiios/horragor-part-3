import unittest
from unittest.mock import Mock, patch

from src.tools.brief2_scraper import scrape_detailed_synopsis


class Brief2ScraperTests(unittest.TestCase):
    def test_scraper_searches_then_fetches_one_matching_film_page(self) -> None:
        search_response = Mock()
        search_response.json.return_value = {"query": {"pages": [{"title": "Test Possession (film)", "extract": "An introduction.", "fullurl": "https://example.test/test-possession"}]}}
        detail_response = Mock()
        detail_response.json.return_value = {
            "parse": {
                "title": "Test Possession (film)",
                "text": (
                    "<div><p>An introduction from Wikipedia.</p>"
                    "<h2>Plot</h2><p>A detailed plot from Wikipedia.</p>"
                    "<h2>Production</h2><p>Production information from Wikipedia.</p></div>"
                ),
            }
        }

        with patch("src.tools.brief2_scraper.requests.get", side_effect=[search_response, detail_response]) as request:
            result = scrape_detailed_synopsis("Test Possession")

        self.assertEqual(result[0]["detail_level"], "detailed")
        self.assertEqual(result[0]["snippet"], "A detailed plot from Wikipedia.")
        self.assertEqual(
            result[0]["wikipedia_sections"]["production"],
            "Production information from Wikipedia.",
        )
        self.assertEqual(request.call_count, 2)

    def test_scraper_rejects_an_unrelated_search_result(self) -> None:
        response = Mock()
        response.json.return_value = {"query": {"pages": [{"title": "Unrelated Film", "extract": "No match."}]}}

        with patch("src.tools.brief2_scraper.requests.get", return_value=response) as request:
            self.assertEqual(scrape_detailed_synopsis("Test Possession"), [])

        request.assert_called_once()