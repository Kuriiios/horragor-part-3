import os
import tempfile
import unittest
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from src.API.main_api import app
from src.auth.tokens import (
    AuthConfigurationError,
    AuthenticationError,
    InvalidTokenError,
    TokenService,
)
from src.config import settings


class FakeGateway:
    count = 1
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


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.password = "correct-password"
        cls.password_hash = PasswordHasher().hash(cls.password)

    def configuration(self, database_path: Path):
        return replace(
            settings,
            auth_enabled=True,
            auth_username="tester",
            auth_password_hash=self.password_hash,
            jwt_secret="test-signing-secret-with-sufficient-entropy",
            jwt_access_minutes=5,
            jwt_refresh_days=1,
            refresh_token_db_path=database_path,
        )

    def test_token_service_authenticates_verifies_and_rejects_refresh_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = TokenService(self.configuration(Path(directory) / "tokens.db"))

            subject = service.authenticate("tester", self.password)
            first_pair = service.issue_pair(subject)
            second_pair = service.rotate_refresh_token(first_pair.refresh_token)

            self.assertEqual(service.verify_access_token(first_pair.access_token), "tester")
            self.assertNotEqual(first_pair.refresh_token, second_pair.refresh_token)
            with self.assertRaises(InvalidTokenError):
                service.rotate_refresh_token(first_pair.refresh_token)

    def test_token_service_rejects_invalid_credentials_and_missing_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            configuration = self.configuration(Path(directory) / "tokens.db")
            service = TokenService(configuration)

            with self.assertRaises(AuthenticationError):
                service.authenticate("tester", "wrong-password")
            with self.assertRaises(AuthConfigurationError):
                TokenService(replace(configuration, jwt_secret=None)).validate_configuration()

    def test_http_login_protection_refresh_and_replay_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            configuration = self.configuration(Path(directory) / "tokens.db")
            service = TokenService(configuration)
            gateway = FakeGateway()
            with (
                patch.dict(os.environ, {"LANGFUSE_TRACING_ENABLED": "false"}),
                patch("src.API.main_api.settings", configuration),
                patch("src.auth.dependencies.settings", configuration),
                patch("src.API.main_api.get_token_service", return_value=service),
                patch("src.auth.dependencies.get_token_service", return_value=service),
                patch("src.API.main_api.get_movie_data_gateway", return_value=gateway),
                patch("src.API.main_api.shutdown_langfuse"),
                patch("src.API.main_api.start_langfuse_observation", return_value=nullcontext(None)),
                TestClient(app) as client,
            ):
                rejected = client.get(
                    "/movies/search",
                    params={"query": "possession"},
                )
                invalid_login = client.post(
                    "/auth/login",
                    json={"username": "tester", "password": "wrong-password"},
                )
                login = client.post(
                    "/auth/login",
                    json={"username": "tester", "password": self.password},
                )
                tokens = login.json()
                accepted = client.get(
                    "/movies/search",
                    params={"query": "possession"},
                    headers={"Authorization": f"Bearer {tokens['access_token']}"},
                )
                refreshed = client.post(
                    "/auth/refresh",
                    json={"refresh_token": tokens["refresh_token"]},
                )
                replayed = client.post(
                    "/auth/refresh",
                    json={"refresh_token": tokens["refresh_token"]},
                )

        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(invalid_login.status_code, 401)
        self.assertEqual(login.status_code, 200)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(replayed.status_code, 401)


if __name__ == "__main__":
    unittest.main()