"""ASGI request correlation, Loguru context, and Prometheus instrumentation."""

from __future__ import annotations

import re
import time
from typing import Any
from uuid import uuid4

from loguru import logger
from starlette.datastructures import Headers, MutableHeaders

from .metrics import ACTIVE_REQUESTS, HTTP_DURATION, HTTP_ERRORS, HTTP_REQUESTS

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class RequestBodyLimitMiddleware:
    """Buffer at most a configured number of request bytes before validation."""

    def __init__(self, app: Any, max_bytes: int = 131_072) -> None:
        self.app = app
        self.max_bytes = max(1, int(max_bytes))

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("method") not in {
            "POST",
            "PUT",
            "PATCH",
        }:
            await self.app(scope, receive, send)
            return

        content_length = Headers(scope=scope).get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_bytes:
            await self._reject(send)
            return

        messages: list[dict[str, Any]] = []
        total_bytes = 0
        while True:
            message = await receive()
            messages.append(message)
            if message.get("type") != "http.request":
                break
            total_bytes += len(message.get("body", b""))
            if total_bytes > self.max_bytes:
                await self._reject(send)
                return
            if not message.get("more_body", False):
                break

        message_iterator = iter(messages)

        async def replay_receive() -> dict[str, Any]:
            return next(
                message_iterator,
                {"type": "http.request", "body": b"", "more_body": False},
            )

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(send: Any) -> None:
        body = b'{"detail":"Request body too large."}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class HttpObservabilityMiddleware:
    """Instrument HTTP traffic without buffering request or response bodies."""

    def __init__(self, app: Any, service: str) -> None:
        self.app = app
        self.service = service

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        supplied_request_id = headers.get("x-request-id", "")
        request_id = (
            supplied_request_id
            if _REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else uuid4().hex
        )
        method = str(scope.get("method", "UNKNOWN"))
        raw_path = str(scope.get("path", "/"))
        status_code = 500
        started_at = time.perf_counter()
        ACTIVE_REQUESTS.labels(self.service).inc()

        async def send_with_request_id(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Request-ID"] = request_id
            await send(message)

        with logger.contextualize(
            service=self.service,
            request_id=request_id,
            method=method,
            path=raw_path,
        ):
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception:
                route = self._route(scope, raw_path)
                HTTP_ERRORS.labels(self.service, method, route).inc()
                logger.exception("Unhandled HTTP request failure")
                raise
            finally:
                duration = time.perf_counter() - started_at
                route = self._route(scope, raw_path)
                ACTIVE_REQUESTS.labels(self.service).dec()
                HTTP_REQUESTS.labels(self.service, method, route, str(status_code)).inc()
                HTTP_DURATION.labels(self.service, method, route).observe(duration)
                log = logger.bind(status=status_code, duration_ms=round(duration * 1000, 2))
                if raw_path in {"/health", "/metrics"}:
                    log.debug("HTTP request completed")
                else:
                    log.info("HTTP request completed")

    @staticmethod
    def _route(scope: dict[str, Any], fallback: str) -> str:
        route = scope.get("route")
        template = getattr(route, "path", None)
        return str(template or fallback)[:160]