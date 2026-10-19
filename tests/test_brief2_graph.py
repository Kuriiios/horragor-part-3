import asyncio
import unittest
from unittest.mock import patch

from src.graph.pipeline import app as graph_app
from src.graph.router import should_scrape_or_narrate
from src.graph.tools_nodes import _parse_tool_plan


class FakeStore:
    count = 1

    def __init__(self) -> None:
        self.movie = {
            "id": "42",
            "title": "Test Possession",
            "release_date": "2012-08-30",
            "genre_names": "Horror, Thriller",
            "overview": "A family faces a demon and a curse in their new home.",
        }

    def search(self, _: str, limit: int) -> list[dict]:
        return [{"score": 1.0, "movie": self.movie}][:limit]

    def get_by_id(self, movie_id: str | int) -> dict | None:
        return self.movie if str(movie_id) == "42" else None


class Brief2GraphTests(unittest.TestCase):
    def test_planner_accepts_only_the_five_tool_contract(self) -> None:
        plan = _parse_tool_plan(
            '{"tool_calls":['
            '{"name":"query_movie_metadata","arguments":{"movie_id":"42"}},'
            '{"name":"search_web","arguments":{"query":"not allowed"}},'
            '{"name":"calculate_movie_age","arguments":{"release_year":2012}}'
            ']}'
        )

        self.assertEqual(
            plan,
            [
                {"name": "query_movie_metadata", "arguments": {"movie_id": "42"}},
                {"name": "calculate_movie_age", "arguments": {"release_year": 2012}},
            ],
        )

    def test_router_moves_only_the_detailed_synopsis_tool_to_scraper(self) -> None:
        self.assertEqual(should_scrape_or_narrate({"pending_tool_calls": []}), "narration")
        self.assertEqual(
            should_scrape_or_narrate({"local_evidence_sufficient": False}),
            "scraper",
        )
        self.assertEqual(
            should_scrape_or_narrate({"local_evidence_sufficient": True}),
            "narration",
        )
        self.assertEqual(
            should_scrape_or_narrate(
                {"pending_tool_calls": [{"name": "scrape_detailed_synopsis", "arguments": {"movie_title": "Test Possession"}}]}
            ),
            "scraper",
        )

    def test_rag_binds_metadata_and_age_calls_to_resolved_local_values(self) -> None:
        metadata = {"movie_id": "42", "title": "Test Possession"}
        age = {"release_year": 2012, "reference_year": 2026, "age_years": 14}
        with (
            patch("src.graph.tools_nodes.get_movie_data_gateway", return_value=FakeStore()),
            patch(
                "src.graph.tools_nodes._call_tool_planner",
                return_value=[
                    {"name": "query_movie_metadata", "arguments": {"movie_id": "incorrect"}},
                    {"name": "calculate_movie_age", "arguments": {"release_year": 2020}},
                ],
            ),
            patch("src.graph.tools_nodes.query_movie_metadata", return_value=metadata) as query_metadata,
            patch("src.graph.tools_nodes.calculate_movie_age", return_value=age) as calculate_age,
            patch("src.graph.tools_nodes._post_local_llm", return_value=None),
        ):
            result = asyncio.run(graph_app.ainvoke({"question": "Who directed Test Possession and how old is it?"}))

        query_metadata.assert_called_once_with(movie_id="42")
        calculate_age.assert_called_once_with(release_year=2012)
        self.assertEqual(result["metadata"]["tools"]["movie_metadata"], metadata)
        self.assertEqual(result["metadata"]["tools"]["movie_age"], age)
        self.assertEqual(result["route"], "narration")

    def test_deep_detail_request_runs_the_scraper_before_narration(self) -> None:
        web_evidence = [{"title": "Test Possession (film)", "snippet": "A detailed public synopsis.", "source": "wikipedia"}]
        with (
            patch("src.graph.tools_nodes.get_movie_data_gateway", return_value=FakeStore()),
            patch("src.graph.tools_nodes._call_tool_planner", return_value=[{"name": "scrape_detailed_synopsis", "arguments": {"movie_title": "incorrect"}}]),
            patch("src.graph.tools_nodes.scrape_detailed_synopsis", return_value=web_evidence) as scrape,
            patch("src.graph.tools_nodes._post_local_llm", return_value=None),
        ):
            result = asyncio.run(graph_app.ainvoke({"question": "Give me a detailed plot for Test Possession"}))

        scrape.assert_called_once_with(movie_title="Test Possession")
        self.assertEqual(result["route"], "scraper")
        self.assertIn("A detailed public synopsis.", result["final_response"])

    def test_local_evidence_without_a_deep_request_skips_scraper(self) -> None:
        with (
            patch("src.graph.tools_nodes.get_movie_data_gateway", return_value=FakeStore()),
            patch("src.graph.tools_nodes._call_tool_planner", return_value=[]),
            patch("src.graph.tools_nodes.scrape_detailed_synopsis") as scrape,
            patch("src.graph.tools_nodes._post_local_llm", return_value=None),
        ):
            result = asyncio.run(graph_app.ainvoke({"question": "Tell me about Test Possession"}))

        scrape.assert_not_called()
        self.assertEqual(result["route"], "narration")

    def test_graph_aggregates_planner_and_narration_token_usage(self) -> None:
        def local_llm(
            *_,
            usage_callback=None,
            observation_name="",
            max_tokens=0,
            temperature=0.0,
        ):
            self.assertGreater(max_tokens, 0)
            self.assertGreaterEqual(temperature, 0.0)
            usage = {
                "plan-tool-calls": {"input": 10, "output": 2, "total": 12},
                "generate-narration": {"input": 20, "output": 8, "total": 28},
            }[observation_name]
            if usage_callback is None:
                raise AssertionError("usage_callback is required")
            usage_callback(usage)
            return '{"tool_calls":[]}' if observation_name == "plan-tool-calls" else "Grounded answer."

        with (
            patch("src.graph.tools_nodes.get_movie_data_gateway", return_value=FakeStore()),
            patch("src.graph.tools_nodes._post_local_llm", side_effect=local_llm),
        ):
            result = asyncio.run(graph_app.ainvoke({"question": "Tell me about Test Possession"}))

        self.assertEqual(
            result["token_usage"],
            {
                "input": 30,
                "output": 10,
                "total": 40,
                "by_generation": {
                    "plan-tool-calls": {"input": 10, "output": 2, "total": 12},
                    "generate-narration": {"input": 20, "output": 8, "total": 28},
                },
            },
        )

    def test_empty_local_evidence_routes_to_scraper_before_narration(self) -> None:
        from types import SimpleNamespace

        store = SimpleNamespace(
            count=0,
            search=lambda _, limit: [] if limit else [],
            get_by_id=lambda _: None,
        )
        web_evidence = [{"title": "A matching film", "snippet": "Web evidence."}]
        with (
            patch("src.graph.tools_nodes.get_movie_data_gateway", return_value=store),
            patch("src.graph.tools_nodes._call_tool_planner", return_value=[]),
            patch("src.graph.tools_nodes.search_web", return_value=web_evidence) as search,
            patch("src.graph.tools_nodes._post_local_llm", return_value=None),
        ):
            result = asyncio.run(
                graph_app.ainvoke({"question": "Tell me about an unknown haunted film"})
            )

        search.assert_called_once_with("Tell me about an unknown haunted film")
        self.assertEqual(result["route"], "scraper")
        self.assertEqual(result["scraper_results"], web_evidence)
        self.assertIn("Web evidence.", result["final_response"])

    def test_non_movie_question_returns_capabilities_without_tools_or_llm(self) -> None:
        with (
            patch("src.graph.tools_nodes.get_movie_data_gateway", return_value=FakeStore()),
            patch("src.graph.tools_nodes._call_tool_planner") as planner,
            patch("src.graph.tools_nodes._post_local_llm") as local_llm,
        ):
            result = asyncio.run(
                graph_app.ainvoke({"question": "What is the weather tomorrow?"})
            )

        planner.assert_not_called()
        local_llm.assert_not_called()
        self.assertEqual(result["metadata"]["scope"], "out_of_scope")
        self.assertEqual(result["metadata"]["narration_mode"], "capabilities")
        self.assertIn("films d'horreur", result["final_response"])


if __name__ == "__main__":
    unittest.main()