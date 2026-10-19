import unittest

from src.tools.movie_resolution import resolve_movie_reference


class ResolutionStore:
    def __init__(self) -> None:
        self.movies = {
            "Night House": {"id": "1373", "title": "Night House"},
            "Night Houses": {"id": "679", "title": "Night Houses"},
            "Dark Echo": {"id": "3806", "title": "Dark Echo"},
        }

    def search(self, query: str, limit: int) -> list[dict]:
        matches = [
            movie
            for movie in self.movies.values()
            if movie["title"].casefold() in query.casefold()
        ]
        if matches:
            matches.sort(key=lambda movie: len(movie["title"]), reverse=True)
            return [{"score": 1.0, "movie": matches[0]}][:limit]
        return [{"score": 1.0, "movie": {"id": "23015", "title": "12/12/12"}}][:limit]

    def get_by_title(self, title: str) -> dict[str, str] | None:
        return self.movies.get(title)


class MovieResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ResolutionStore()

    def test_embedded_title_resolves_exactly(self) -> None:
        resolution = resolve_movie_reference(
            self.store, "Who are the actors in Night House?"
        )

        self.assertEqual(resolution["title"], "Night House")
        self.assertEqual(resolution["movie_id"], "1373")
        self.assertEqual(resolution["source"], "exact_title")

    def test_longest_embedded_title_is_preferred(self) -> None:
        resolution = resolve_movie_reference(
            self.store, "Who are the actors in Night Houses?"
        )

        self.assertEqual(resolution["title"], "Night Houses")
        self.assertEqual(resolution["movie_id"], "679")

    def test_unresolved_ordinal_reference_is_not_invented(self) -> None:
        resolution = resolve_movie_reference(self.store, "the second film")

        self.assertEqual(resolution["status"], "unresolved")
        self.assertNotIn("title", resolution)

    def test_unresolved_title_does_not_use_semantic_match(self) -> None:
        self.store.movies.pop("Night Houses")
        resolution = resolve_movie_reference(
            self.store, "Tell me about an unrelated recipe"
        )

        self.assertEqual(resolution["status"], "unresolved")
        self.assertEqual(resolution["source"], "semantic_search")

    def test_follow_up_uses_previous_generic_title(self) -> None:
        resolution = resolve_movie_reference(
            self.store,
            "What are the actors for it?",
            [{"role": "user", "content": "Tell me about Night House"}],
        )

        self.assertEqual(resolution["title"], "Night House")
        self.assertEqual(resolution["source"], "history_title")

    def test_current_title_wins_over_previous_conversation_title(self) -> None:
        resolution = resolve_movie_reference(
            self.store,
            "Tell me about Night Houses",
            [{"role": "user", "content": "Tell me about Night House"}],
        )

        self.assertEqual(resolution["title"], "Night Houses")
        self.assertEqual(resolution["movie_id"], "679")
        self.assertEqual(resolution["source"], "exact_title")

    def test_new_explicit_title_does_not_fall_back_to_previous_title(self) -> None:
        resolution = resolve_movie_reference(
            self.store,
            "Tell me about an unreleased movie called Glass Garden",
            [{"role": "user", "content": "Tell me about Night House"}],
        )

        self.assertEqual(resolution["status"], "unresolved")
        self.assertEqual(resolution["source"], "semantic_search")

    def test_broad_topic_request_does_not_resolve_generic_movie_phrase(self) -> None:
        self.store.movies["Horror Movie"] = {"id": "991", "title": "Horror Movie"}
        resolution = resolve_movie_reference(
            self.store,
            "I want to see a horror movie about time travel",
        )

        self.assertEqual(resolution["status"], "unresolved")
        self.assertNotIn("title", resolution)


if __name__ == "__main__":
    unittest.main()
