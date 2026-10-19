import re
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from src.http_observability import HttpObservabilityMiddleware, RequestBodyLimitMiddleware


class HttpObservabilityTests(unittest.TestCase):
    def test_oversized_body_is_rejected_before_endpoint_parsing(self) -> None:
        app = FastAPI()
        app.add_middleware(RequestBodyLimitMiddleware, max_bytes=16)
        calls: list[bool] = []

        @app.post("/chat")
        def chat() -> dict[str, str]:
            calls.append(True)
            return {"status": "unexpected"}

        with TestClient(app) as client:
            response = client.post("/chat", content=b"x" * 17)

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json(), {"detail": "Request body too large."})
        self.assertEqual(calls, [])

    def test_request_id_is_echoed_and_route_template_is_measured(self) -> None:
        app = FastAPI()
        app.add_middleware(HttpObservabilityMiddleware, service="observability-test")

        @app.get("/items/{item_id}")
        def get_item(item_id: str) -> dict[str, str]:
            return {"item_id": item_id}

        with TestClient(app) as client:
            response = client.get(
                "/items/42",
                headers={"X-Request-ID": "request-42"},
            )

        metrics = generate_latest().decode("utf-8")
        self.assertEqual(response.headers["X-Request-ID"], "request-42")
        self.assertIn('service="observability-test"', metrics)
        self.assertIn('route="/items/{item_id}"', metrics)

    def test_unsafe_request_id_is_replaced(self) -> None:
        app = FastAPI()
        app.add_middleware(HttpObservabilityMiddleware, service="request-id-test")

        @app.get("/health")
        def health() -> dict[str, str]:
            return {"status": "healthy"}

        with TestClient(app) as client:
            response = client.get(
                "/health",
                headers={"X-Request-ID": "invalid request id with spaces"},
            )

        self.assertNotEqual(
            response.headers["X-Request-ID"],
            "invalid request id with spaces",
        )
        self.assertRegex(response.headers["X-Request-ID"], re.compile(r"^[a-f0-9]{32}$"))


if __name__ == "__main__":
    unittest.main()