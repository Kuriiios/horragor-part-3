import asyncio
import unittest
from contextlib import nullcontext
from dataclasses import replace
from unittest.mock import AsyncMock, Mock, patch

import requests
from fastapi import HTTPException

from src.API import main_api
from src.API.api_schemas import ChatRequest, LoginRequest, RefreshTokenRequest
from src.auth.tokens import AuthConfigurationError, InvalidTokenError
from src.config import settings


class FakeObservation:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *_) -> None:
        return None

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


class MainApiTests(unittest.TestCase):
    def test_model_health_reports_disabled_ready_and_unavailable(self) -> None:
        disabled = replace(settings, llm_base_url=None)
        with patch("src.API.main_api.settings", disabled):
            self.assertEqual(main_api._model_health()["status"], "disabled")

        enabled = replace(settings, llm_base_url="http://model:8001/v1")
        response = Mock()
        with (
            patch("src.API.main_api.settings", enabled),
            patch("src.API.main_api.requests.get", return_value=response),
        ):
            self.assertEqual(main_api._model_health()["status"], "ready")
        response.raise_for_status.assert_called_once_with()

        with (
            patch("src.API.main_api.settings", enabled),
            patch(
                "src.API.main_api.requests.get",
                side_effect=requests.RequestException("offline"),
            ),
        ):
            self.assertEqual(main_api._model_health()["status"], "unavailable")

    def test_gateway_and_search_failures_become_service_unavailable(self) -> None:
        with patch(
            "src.API.main_api.get_movie_data_gateway",
            side_effect=RuntimeError("offline"),
        ), self.assertRaises(HTTPException) as gateway_error:
            main_api._gateway_or_raise()
        self.assertEqual(gateway_error.exception.status_code, 503)

        gateway = Mock()
        gateway.search.side_effect = RuntimeError("offline")
        with (
            patch("src.API.main_api.get_movie_data_gateway", return_value=gateway),
            patch(
                "src.API.main_api.start_langfuse_observation",
                return_value=nullcontext(None),
            ),self.assertRaises(HTTPException) as search_error
        ):
            asyncio.run(main_api.search_movies("haunted", 2))
        self.assertEqual(search_error.exception.status_code, 503)

    def test_login_disabled_and_misconfigured_are_explicit(self) -> None:
        with (
            patch("src.API.main_api.settings", replace(settings, auth_enabled=False)),
            self.assertRaises(HTTPException) as disabled_error,
        ):
            main_api.login(LoginRequest(username="tester", password="password123"))
        self.assertEqual(disabled_error.exception.status_code, 404)

        service = Mock()
        service.authenticate.side_effect = AuthConfigurationError("missing secret")
        with (
            patch("src.API.main_api.settings", replace(settings, auth_enabled=True)),
            patch("src.API.main_api.get_token_service", return_value=service),
            self.assertRaises(HTTPException) as configuration_error,
        ):
            main_api.login(LoginRequest(username="tester", password="password123"))
        self.assertEqual(configuration_error.exception.status_code, 503)

    def test_invalid_refresh_and_logout_are_safe(self) -> None:
        service = Mock()
        service.rotate_refresh_token.side_effect = InvalidTokenError("invalid")
        service.revoke_refresh_token.side_effect = InvalidTokenError("invalid")
        request = RefreshTokenRequest(refresh_token="x" * 32)
        with patch("src.API.main_api.get_token_service", return_value=service):
            with self.assertRaises(HTTPException) as refresh_error:
                main_api.refresh_access_token(request)
            response = main_api.logout(request)

        self.assertEqual(refresh_error.exception.status_code, 401)
        self.assertEqual(response.status_code, 204)

    def test_graph_failure_updates_trace_and_returns_service_unavailable(self) -> None:
        graph = Mock()
        graph.ainvoke = AsyncMock(side_effect=RuntimeError("graph unavailable"))
        trace = FakeObservation()
        with (
            patch("src.API.main_api.graph_app", graph),
            patch("src.API.main_api.start_langfuse_chat_trace", return_value=trace),
            patch("src.API.main_api.create_langfuse_handler", return_value=None),
            self.assertRaises(HTTPException) as graph_error,
        ):
            asyncio.run(main_api.process_chat_message(ChatRequest(question="A horror film?")))

        self.assertEqual(graph_error.exception.status_code, 503)
        self.assertEqual(trace.updates[0]["level"], "ERROR")

    def test_malformed_graph_metadata_produces_a_bounded_fallback_response(self) -> None:
        graph = Mock()
        graph.ainvoke = AsyncMock(
            return_value={
                "metadata": {"top_score": "not-a-number", "route": "scraper"},
                "scraper_results": [{"snippet": "evidence"}],
                "final_response": "",
                "token_usage": "invalid",
            }
        )
        with (
            patch("src.API.main_api.graph_app", graph),
            patch(
                "src.API.main_api.start_langfuse_chat_trace",
                return_value=nullcontext(None),
            ),
            patch("src.API.main_api.create_langfuse_handler", return_value=None),
            patch("src.API.main_api.record_graph_result") as record_result,
        ):
            response = asyncio.run(
                main_api.process_chat_message(ChatRequest(question="An unknown horror film?"))
            )

        self.assertTrue(response.verdict.is_valid)
        self.assertEqual(response.verdict.score, 0)
        self.assertIn("No reliable movie evidence", response.response)
        record_result.assert_called_once_with("scraper", None, None)

    def test_health_and_metrics_report_dependencies(self) -> None:
        gateway = Mock()
        gateway.stats.return_value = {"records": 12, "dimension": 64}
        configured = replace(settings, data_api_url="http://data-api:8002")
        with (
            patch("src.API.main_api.settings", configured),
            patch("src.API.main_api.get_movie_data_gateway", return_value=gateway),
            patch("src.API.main_api._model_health", return_value={"status": "ready"}),
        ):
            health = asyncio.run(main_api.health_check())

        self.assertEqual(health["records"], 12)
        self.assertEqual(health["data_api"], "ready")
        self.assertEqual(main_api.prometheus_metrics().status_code, 200)

        gateway.stats.side_effect = RuntimeError("offline")
        with (
            patch("src.API.main_api.get_movie_data_gateway", return_value=gateway),
            self.assertRaises(HTTPException) as health_error,
        ):
            asyncio.run(main_api.health_check())
        self.assertEqual(health_error.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()