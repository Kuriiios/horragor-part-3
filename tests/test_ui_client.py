import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

from src.ui.api_client import ApiClientError, HorragorApiClient


def fake_response(status_code: int, payload: dict) -> Mock:
    response = Mock(
        status_code=status_code,
        ok=status_code < 400,
        content=b"{}",
    )
    response.json.return_value = payload
    return response


class FakePresentationClient:
    base_url = "https://intelligence-api:8000"

    def __init__(self, *, auth_required: bool = False, ask_error: bool = False) -> None:
        self.auth_required = auth_required
        self.ask_error = ask_error
        self.is_authenticated = False
        self.login_calls: list[tuple[str, str]] = []
        self.logout_calls = 0
        self.ask_calls: list[tuple[str, dict]] = []

    def check_health(self) -> dict:
        return {
            "auth_enabled": self.auth_required,
            "faiss_router": "ready",
            "records": 2,
            "narration_model": {
                "status": "disabled" if self.auth_required else "ready",
                "model": "test-model",
            },
        }

    def login(self, username: str, password: str) -> None:
        self.login_calls.append((username, password))
        self.is_authenticated = True

    def logout(self) -> None:
        self.logout_calls += 1
        self.is_authenticated = False

    def ask(self, question: str, **kwargs) -> dict:
        self.ask_calls.append((question, kwargs))
        if self.ask_error:
            raise ApiClientError("service unavailable")
        return {
            "response": "Grounded answer",
            "token_usage": {"input": 1, "output": 2, "total": 3},
            "verdict": {
                "is_valid": True,
                "score": 9,
                "justification": "Grounded in evidence.",
            },
            "metadata": {
                "matches": [{"title": "Test Film", "id": "42", "score": 1.0}]
            },
        }


class ApiClientTests(unittest.TestCase):
    def test_client_refreshes_once_and_retries_with_the_new_access_token(self) -> None:
        session = Mock()
        session.request.side_effect = [
            fake_response(200, {"access_token": "old-access", "refresh_token": "old-refresh"}),
            fake_response(401, {"detail": "expired"}),
            fake_response(200, {"access_token": "new-access", "refresh_token": "new-refresh"}),
            fake_response(200, {"response": "grounded"}),
        ]
        client = HorragorApiClient("https://api.internal", session=session)
        client.login("user", "password123")

        result = client.ask("question")

        self.assertEqual(result["response"], "grounded")
        self.assertEqual(session.request.call_count, 4)
        self.assertEqual(
            session.request.call_args_list[-1].kwargs["headers"],
            {"Authorization": "Bearer new-access"},
        )

    def test_client_refuses_to_send_credentials_over_remote_http(self) -> None:
        session = Mock()
        client = HorragorApiClient("http://api.example.test", session=session)

        with self.assertRaises(ApiClientError):
            client.login("user", "password123")

        session.request.assert_not_called()

    def test_chat_payload_bounds_history_content_and_session_id(self) -> None:
        session = Mock()
        session.request.return_value = fake_response(200, {"response": "grounded"})
        client = HorragorApiClient("http://localhost:8000", session=session)
        history = [
            {"role": "user", "content": f"message-{index}" + "x" * 5000}
            for index in range(25)
        ]

        client.ask("question", history=history, session_id="s" * 200)

        payload = session.request.call_args.kwargs["json"]
        self.assertEqual(len(payload["history"]), 20)
        self.assertEqual(len(payload["history"][0]["content"]), 4000)
        self.assertEqual(len(payload["session_id"]), 128)

    def test_health_failure_returns_none(self) -> None:
        session = Mock()
        session.request.side_effect = OSError("network unavailable")
        client = HorragorApiClient("http://localhost:8000", session=session)

        with patch("src.ui.api_client.requests.RequestException", OSError):
            self.assertIsNone(client.check_health())

    def test_logout_revokes_refresh_token_and_clears_session(self) -> None:
        session = Mock()
        session.request.side_effect = [
            fake_response(200, {"access_token": "access", "refresh_token": "refresh"}),
            fake_response(204, {}),
        ]
        client = HorragorApiClient("https://api.internal", session=session)
        client.login("user", "password123")

        client.logout()

        self.assertFalse(client.is_authenticated)
        self.assertEqual(
            session.request.call_args.kwargs["json"],
            {"refresh_token": "refresh"},
        )

    def test_failed_refresh_clears_tokens(self) -> None:
        session = Mock()
        session.request.side_effect = [
            fake_response(200, {"access_token": "access", "refresh_token": "refresh"}),
            fake_response(401, {"detail": "expired"}),
        ]
        client = HorragorApiClient("https://api.internal", session=session)
        client.login("user", "password123")

        with self.assertRaises(ApiClientError):
            client.refresh()

        self.assertFalse(client.is_authenticated)

    def test_client_rejects_invalid_urls_and_response_contracts(self) -> None:
        with self.assertRaises(ValueError):
            HorragorApiClient("not-a-url")

        session = Mock()
        response = Mock(status_code=200, ok=True, content=b"not-json")
        response.json.side_effect = ValueError("invalid")
        session.request.return_value = response
        client = HorragorApiClient("https://api.internal", session=session)
        with self.assertRaises(ApiClientError):
            client.ask("question")


class StreamlitSmokeTests(unittest.TestCase):
    app_path = Path(__file__).resolve().parents[1] / "app_frontend.py"

    def test_app_renders_without_an_api(self) -> None:
        with patch.dict(
            os.environ,
            {
                "HORRAGOR_API_URL": "http://127.0.0.1:65534",
                "HORRAGOR_HEALTH_TIMEOUT": "0.5",
            },
        ):
            rendered = AppTest.from_file(self.app_path).run(timeout=10)

        self.assertEqual(len(rendered.exception), 0)
        self.assertEqual(len(rendered.chat_input), 1)
        self.assertGreaterEqual(len(rendered.error), 1)

    def test_app_submits_and_renders_a_grounded_chat_turn(self) -> None:
        client = FakePresentationClient()
        with patch("src.ui.HorragorApiClient.from_environment", return_value=client):
            rendered = AppTest.from_file(self.app_path).run(timeout=10)
            rendered.chat_input[0].set_value("Tell me about Test Film").run(timeout=10)

        self.assertEqual(len(rendered.exception), 0)
        self.assertEqual(len(rendered.chat_message), 2)
        self.assertGreaterEqual(len(rendered.caption), 3)
        self.assertEqual(len(rendered.expander), 1)
        self.assertEqual(client.ask_calls[0][0], "Tell me about Test Film")

    def test_app_logs_in_and_logs_out_when_authentication_is_required(self) -> None:
        client = FakePresentationClient(auth_required=True)
        with patch("src.ui.HorragorApiClient.from_environment", return_value=client):
            rendered = AppTest.from_file(self.app_path).run(timeout=10)
            self.assertTrue(rendered.chat_input[0].disabled)
            rendered.text_input[0].set_value("tester")
            rendered.text_input[1].set_value("password123")
            rendered.button[0].click().run(timeout=10)
            self.assertFalse(rendered.chat_input[0].disabled)
            rendered.button[0].click().run(timeout=10)

        self.assertEqual(client.login_calls, [("tester", "password123")])
        self.assertEqual(client.logout_calls, 1)

    def test_app_displays_chat_transport_errors(self) -> None:
        client = FakePresentationClient(ask_error=True)
        with patch("src.ui.HorragorApiClient.from_environment", return_value=client):
            rendered = AppTest.from_file(self.app_path).run(timeout=10)
            rendered.chat_input[0].set_value("Tell me about Test Film").run(timeout=10)

        self.assertEqual(len(rendered.exception), 0)
        self.assertGreaterEqual(len(rendered.error), 1)


if __name__ == "__main__":
    unittest.main()