"""HTTP-only client used by Streamlit to reach the intelligence API."""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class ApiClientError(RuntimeError):
    """A safe presentation-layer error for API transport or contract failures."""


def _positive_float(value: str | None, default: float) -> float:
    try:
        parsed = float(value) if value is not None else default
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _tls_verification() -> bool | str:
    certificate_bundle = os.getenv("HORRAGOR_API_CA_BUNDLE", "").strip()
    if certificate_bundle:
        return certificate_bundle
    setting = os.getenv("HORRAGOR_API_TLS_VERIFY", "true").strip().casefold()
    return setting not in {"0", "false", "no", "off"}


class HorragorApiClient:
    """Connection-pooled client with access-token refresh and strict JSON contracts."""

    def __init__(
        self,
        base_url: str,
        *,
        request_timeout: float = 150.0,
        health_timeout: float = 5.0,
        verify_tls: bool | str = True,
        session: requests.Session | None = None,
    ) -> None:
        normalized_url = base_url.strip().rstrip("/")
        if not normalized_url:
            raise ValueError("base_url must not be empty")
        parsed_url = urlparse(normalized_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        self.base_url = normalized_url
        self.request_timeout = max(1.0, float(request_timeout))
        self.health_timeout = max(0.5, float(health_timeout))
        self.verify_tls = verify_tls
        self._session = session or requests.Session()
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    @classmethod
    def from_environment(cls) -> HorragorApiClient:
        llm_timeout = _positive_float(os.getenv("HORRAGOR_LLM_TIMEOUT_SECONDS"), 120.0)
        request_timeout = _positive_float(
            os.getenv("HORRAGOR_API_TIMEOUT"),
            llm_timeout + 30.0,
        )
        return cls(
            os.getenv("HORRAGOR_API_URL", "http://127.0.0.1:8000"),
            request_timeout=request_timeout,
            health_timeout=_positive_float(os.getenv("HORRAGOR_HEALTH_TIMEOUT"), 5.0),
            verify_tls=_tls_verification(),
        )

    @property
    def is_authenticated(self) -> bool:
        return bool(self._access_token and self._refresh_token)

    def _credentials_transport_is_safe(self) -> bool:
        parsed_url = urlparse(self.base_url)
        return parsed_url.scheme == "https" or parsed_url.hostname in _LOOPBACK_HOSTS

    @staticmethod
    def _parse_payload(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiClientError("L'API a renvoye une reponse JSON invalide.") from exc
        if not isinstance(payload, dict):
            raise ApiClientError("La reponse de l'API ne respecte pas le contrat attendu.")
        return payload

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
        retry_after_refresh: bool = True,
        log_transport_errors: bool = True,
    ) -> dict[str, Any]:
        headers = (
            {"Authorization": f"Bearer {self._access_token}"}
            if self._access_token
            else {}
        )
        try:
            response = self._session.request(
                method,
                f"{self.base_url}{path}",
                json=json,
                headers=headers,
                timeout=timeout or self.request_timeout,
                verify=self.verify_tls,
            )
        except requests.RequestException as exc:
            if log_transport_errors:
                logger.exception("HorRAGor API request failed: %s %s", method, path)
            else:
                logger.debug("HorRAGor API health probe failed: %s", exc)
            raise ApiClientError(f"Impossible de joindre l'API HorRAGor ({self.base_url}).") from exc

        if (
            response.status_code == 401
            and retry_after_refresh
            and self._refresh_token
            and path not in {"/auth/login", "/auth/refresh"}
        ):
            self.refresh()
            return self._request(
                method,
                path,
                json=json,
                timeout=timeout,
                retry_after_refresh=False,
                log_transport_errors=log_transport_errors,
            )

        payload = self._parse_payload(response) if response.content else {}
        if not response.ok:
            detail = payload.get("detail", "Erreur inconnue")
            raise ApiClientError(
                f"L'API HorRAGor a renvoye HTTP {response.status_code}: {detail}"
            )
        return payload

    def check_health(self) -> dict[str, Any] | None:
        """Return health information, or None when the API cannot be reached."""
        try:
            return self._request(
                "GET",
                "/health",
                timeout=self.health_timeout,
                retry_after_refresh=False,
                log_transport_errors=False,
            )
        except ApiClientError:
            return None

    def login(self, username: str, password: str) -> None:
        """Authenticate and retain the returned token pair in process memory."""
        if not self._credentials_transport_is_safe():
            raise ApiClientError("Connexion refusee: les identifiants exigent HTTPS.")
        payload = self._request(
            "POST",
            "/auth/login",
            json={"username": username, "password": password},
            retry_after_refresh=False,
        )
        self._set_tokens(payload)

    def _set_tokens(self, payload: dict[str, Any]) -> None:
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            raise ApiClientError("La reponse d'authentification est invalide.")
        self._access_token = access_token
        self._refresh_token = refresh_token

    def refresh(self) -> None:
        """Rotate the current refresh token and replace both local tokens."""
        if not self._refresh_token:
            raise ApiClientError("La session a expire; reconnectez-vous.")
        previous_refresh_token = self._refresh_token
        try:
            payload = self._request(
                "POST",
                "/auth/refresh",
                json={"refresh_token": previous_refresh_token},
                retry_after_refresh=False,
            )
            self._set_tokens(payload)
        except ApiClientError:
            self.clear_tokens()
            raise

    def logout(self) -> None:
        """Revoke the current refresh token and clear local credentials."""
        refresh_token = self._refresh_token
        try:
            if refresh_token:
                self._request(
                    "POST",
                    "/auth/logout",
                    json={"refresh_token": refresh_token},
                    retry_after_refresh=False,
                )
        finally:
            self.clear_tokens()

    def clear_tokens(self) -> None:
        self._access_token = None
        self._refresh_token = None

    def ask(
        self,
        question: str,
        *,
        history: list[dict[str, str]] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Send one bounded chat turn and validate its required response field."""
        payload: dict[str, Any] = {"question": question.strip()}
        bounded_history = [
            {"role": str(message["role"]), "content": str(message["content"])[:4000]}
            for message in (history or [])[-20:]
            if message.get("role") in {"user", "assistant"} and message.get("content")
        ]
        if bounded_history:
            payload["history"] = bounded_history
        if session_id:
            payload["session_id"] = session_id[:128]
        response = self._request("POST", "/chat", json=payload)
        if not isinstance(response.get("response"), str):
            raise ApiClientError("La reponse de l'API ne respecte pas le contrat attendu.")
        return response