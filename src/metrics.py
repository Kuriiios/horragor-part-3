"""Low-cardinality Prometheus metrics shared by HorRAGor services."""

from __future__ import annotations

from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

HTTP_REQUESTS = Counter(
    "horragor_http_requests_total",
    "Completed HTTP requests.",
    ("service", "method", "route", "status"),
)
HTTP_ERRORS = Counter(
    "horragor_http_errors_total",
    "HTTP requests that raised before a response was completed.",
    ("service", "method", "route"),
)
HTTP_DURATION = Histogram(
    "horragor_http_request_duration_seconds",
    "HTTP request latency.",
    ("service", "method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 120),
)
ACTIVE_REQUESTS = Gauge(
    "horragor_http_active_requests",
    "HTTP requests currently in progress.",
    ("service",),
)
GRAPH_ROUTES = Counter(
    "horragor_graph_routes_total",
    "Completed graph turns by selected route.",
    ("route", "narration_mode"),
)
LLM_TOKENS = Counter(
    "horragor_llm_tokens_total",
    "Local model tokens reported by generation and direction.",
    ("generation", "direction"),
)
TOOL_CALLS = Counter(
    "horragor_tool_calls_total",
    "Movie tool calls by tool and outcome.",
    ("tool", "outcome"),
)


def metrics_response() -> Response:
    """Return the current default registry in Prometheus text format."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def record_graph_result(
    route: str,
    narration_mode: Any,
    token_usage: Any,
) -> None:
    """Record bounded graph dimensions and validated generation token counts."""
    normalized_route = route if route in {"narration", "scraper"} else "unknown"
    normalized_mode = (
        narration_mode
        if narration_mode in {"local_llm", "fallback", "capabilities"}
        else "unknown"
    )
    GRAPH_ROUTES.labels(normalized_route, normalized_mode).inc()
    if not isinstance(token_usage, dict):
        return
    generations = token_usage.get("by_generation")
    if not isinstance(generations, dict):
        return
    for generation, usage in generations.items():
        if not isinstance(generation, str) or not isinstance(usage, dict):
            continue
        for direction in ("input", "output"):
            count = usage.get(direction)
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                LLM_TOKENS.labels(generation[:80], direction).inc(count)


def record_tool_call(tool_name: str, outcome: str) -> None:
    """Record a model-visible tool call using bounded labels."""
    normalized_outcome = outcome if outcome in {"success", "empty", "error"} else "error"
    TOOL_CALLS.labels(tool_name[:80], normalized_outcome).inc()