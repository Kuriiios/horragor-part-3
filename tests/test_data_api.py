import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from src.data_api.main import app
from src.data_gateway import DataGatewayUnavailable, HttpMovieDataGateway


class FakeMovieStore:
    count = 2
    dimension = 64

    def stats(self) -> dict:
        return {
            "records": self.count,
            "dimension": self.dimension,
            "index_path": "movies.index",
            "metadata_path": "movies.json",
            "source_path": "movies.csv",
        }

    def search(self, query: str, limit: int = 5) -> list[dict]:
        return [
            {
                "score": 1.0,
                "movie": {"id": "42", "title": "Test Possession", "overview": query},
            }
        ][:limit]

    def get_by_id(self, movie_id: str | int) -> dict[str, str] | None:
        if str(movie_id) != "42":
            return None
        return {"id": "42", "title": "Test Possession", "overview": "A curse."}

    def find_similar_by_overview(self, _: str | int, limit: int = 5) -> list[dict]:
        return [
            {
                "score": 0.8,
                "movie": {"id": "43", "title": "Similar Film", "overview": "A curse."},
            }
        ][:limit]


class DataApiTests(unittest.TestCase):
    def test_routes_expose_bounded_store_operations(self) -> None:
        with (
            patch(
                "src.data_api.main.settings",
                SimpleNamespace(data_api_key=None, environment="development"),
            ),
            patch("src.data_api.main.get_movie_store", return_value=FakeMovieStore()),
            TestClient(app) as client,
        ):
            health = client.get("/health")
            search = client.get(
                "/v1/movies/search",
                params={"query": "a curse", "limit": 1},
            )
            movie = client.get("/v1/movies/42")
            similar = client.get("/v1/movies/42/similar", params={"limit": 1})
            missing = client.get("/v1/movies/missing")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["records"], 2)
        self.assertEqual(search.json()["results"][0]["movie"]["id"], "42")
        self.assertEqual(movie.json()["movie"]["title"], "Test Possession")
        self.assertEqual(similar.json()["results"][0]["movie"]["id"], "43")
        self.assertEqual(missing.status_code, 404)

    def test_internal_key_is_required_when_configured(self) -> None:
        configured_settings = SimpleNamespace(
            data_api_key="service-secret",
            environment="development",
        )
        with (
            patch("src.data_api.main.settings", configured_settings),
            patch("src.data_api.main.get_movie_store", return_value=FakeMovieStore()),
            TestClient(app) as client,
        ):
            rejected = client.get("/v1/stats")
            accepted = client.get(
                "/v1/stats",
                headers={"X-Internal-API-Key": "service-secret"},
            )

        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(accepted.status_code, 200)

    def test_production_startup_rejects_a_weak_service_key(self) -> None:
        configured_settings = SimpleNamespace(
            data_api_key="weak",
            environment="production",
        )
        with (
            patch("src.data_api.main.settings", configured_settings),
            self.assertRaises(RuntimeError),
            TestClient(app),
        ):
            pass


class HttpMovieDataGatewayTests(unittest.TestCase):
    def test_gateway_reuses_contract_and_service_credential(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {
            "query": "possession",
            "results": [{"score": 1.0, "movie": {"id": "42", "title": "Test"}}],
            "index_size": 2,
        }
        session = Mock()
        session.get.return_value = response
        gateway = HttpMovieDataGateway(
            "http://data-api:8002/",
            api_key="service-secret",
            timeout_seconds=3.0,
            session=session,
        )

        results = gateway.search("possession", limit=1)

        self.assertEqual(results[0]["movie"]["id"], "42")
        self.assertEqual(gateway.count, 2)
        session.get.assert_called_once_with(
            "http://data-api:8002/v1/movies/search",
            params={"query": "possession", "limit": 1},
            headers={"X-Internal-API-Key": "service-secret"},
            timeout=3.0,
        )

    def test_gateway_rejects_an_invalid_response_contract(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {"results": "not-a-list"}
        session = Mock()
        session.get.return_value = response
        gateway = HttpMovieDataGateway("http://data-api:8002", session=session)

        with self.assertRaises(DataGatewayUnavailable):
            gateway.search("possession")


if __name__ == "__main__":
    unittest.main()