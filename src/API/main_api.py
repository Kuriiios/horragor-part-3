"""FastAPI entry point for HorRAGor's retrieval and multi-agent chat service."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from typing import Any

import requests
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from ..auth.dependencies import require_authenticated_user
from ..auth.tokens import (
    AuthConfigurationError,
    AuthenticationError,
    InvalidTokenError,
    get_token_service,
)
from ..config import settings
from ..data_gateway import get_movie_data_gateway
from ..graph.pipeline import app as graph_app
from ..http_observability import HttpObservabilityMiddleware, RequestBodyLimitMiddleware
from ..logging_config import configure_logging
from ..metrics import metrics_response, record_graph_result
from ..models.state import AgentState
from ..observability import (
    create_langfuse_handler,
    shutdown_langfuse,
    start_langfuse_chat_trace,
    start_langfuse_observation,
)
from .api_schemas import (
    ChatRequest,
    ChatResponse,
    JudgeVerdict,
    LoginRequest,
    MovieHit,
    MovieSearchResponse,
    RefreshTokenRequest,
    TokenResponse,
    TokenUsageSummary,
)

logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _model_health() -> dict[str, Any]:
    """Check the optional local model service without affecting FAISS health."""
    if not settings.llm_base_url:
        return {"status": "disabled", "model": settings.llm_model}
    try:
        response = requests.get(
            f"{settings.llm_base_url.rstrip('/')}/models",
            timeout=1.0,
        )
        response.raise_for_status()
    except requests.RequestException:
        return {
            "status": "unavailable",
            "model": settings.llm_model,
            "endpoint": settings.llm_base_url,
        }
    return {
        "status": "ready",
        "model": settings.llm_model,
        "endpoint": settings.llm_base_url,
    }


def _gateway_or_raise():
    try:
        return get_movie_data_gateway()
    except Exception as exc:
        logger.exception("Movie data gateway is unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The movie data service is unavailable.",
        ) from exc

def _graph_config() -> RunnableConfig:
    """Build per-request LangGraph configuration without requiring Langfuse."""
    config: RunnableConfig = {"run_name": "run-movie-agent-graph"}
    handler = create_langfuse_handler()
    if handler is not None:
        config["callbacks"] = [handler]
    return config


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging("intelligence-api")
    logger.info("Connecting to the HorRAGor movie data layer")
    try:
        gateway = get_movie_data_gateway()
        stats = await run_in_threadpool(gateway.stats)
        logger.info("Movie data layer ready: %s", stats)
    except Exception:
        logger.exception("FAISS movie index failed to initialise")
    if settings.auth_enabled:
        get_token_service().validate_configuration()
        logger.info("Bearer authentication is enabled")
    try:
        yield
    finally:
        shutdown_langfuse()
        logger.info("HorRAGor API stopped")


app = FastAPI(
    title="HorRAGor Movie Retrieval API",
    description="Multi-agent horror movie retrieval with local FAISS evidence and optional web enrichment.",
    version="3.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_bytes=settings.max_request_body_bytes,
)
app.add_middleware(HttpObservabilityMiddleware, service="intelligence-api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    """Expose process metrics to the private Prometheus service."""
    return metrics_response()


@app.post("/auth/login", response_model=TokenResponse)
def login(request: LoginRequest) -> TokenResponse:
    """Authenticate deployment-managed credentials and issue a token pair."""
    if not settings.auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authentication is disabled in this environment.",
        )
    try:
        service = get_token_service()
        subject = service.authenticate(request.username, request.password)
        return TokenResponse(**asdict(service.issue_pair(subject)))
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        ) from exc
    except AuthConfigurationError as exc:
        logger.error("Authentication configuration is incomplete: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        ) from exc


@app.post("/auth/refresh", response_model=TokenResponse)
def refresh_access_token(request: RefreshTokenRequest) -> TokenResponse:
    """Consume a refresh token and return a newly rotated pair."""
    try:
        return TokenResponse(
            **asdict(get_token_service().rotate_refresh_token(request.refresh_token))
        )
    except (AuthConfigurationError, InvalidTokenError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The refresh token is invalid or expired.",
        ) from exc


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: RefreshTokenRequest) -> Response:
    """Revoke a refresh token without exposing whether it was already consumed."""
    with suppress(AuthConfigurationError, InvalidTokenError):
        get_token_service().revoke_refresh_token(request.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get(
    "/movies/search",
    response_model=MovieSearchResponse,
    summary="Search movie metadata and synopses with FAISS",
    dependencies=[Depends(require_authenticated_user)],
)
async def search_movies(
    query: str = Query(..., min_length=1, description="Movie title, synopsis, or topic"),
    limit: int = Query(5, ge=1, le=50, description="Maximum number of matches"),
) -> MovieSearchResponse:
    with start_langfuse_observation(
        name="search-movies",
        as_type="retriever",
        input={"query": query, "limit": limit},
        metadata={"feature": "movie-search", "index": "faiss"},
    ) as retrieval_observation:
        gateway = _gateway_or_raise()
        try:
            results = await run_in_threadpool(gateway.search, query, limit)
            index_size = gateway.count
        except Exception as exc:
            logger.exception("Movie search failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The movie data service is unavailable.",
            ) from exc
        if retrieval_observation is not None:
            retrieval_observation.update(
                output={"match_count": len(results), "index_size": index_size}
            )
        return MovieSearchResponse(
            query=query,
            results=[MovieHit.model_validate(result) for result in results],
            index_size=index_size,
        )


@app.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Answer a question through the RAG, scraper, and narration graph",
    dependencies=[Depends(require_authenticated_user)],
)
async def process_chat_message(request: ChatRequest) -> ChatResponse:
    trace_metadata = {
        "feature": "horror-movie-chat",
        "history_turns": len(request.history),
    }
    with start_langfuse_chat_trace(
        question=request.question,
        session_id=request.session_id,
        metadata=trace_metadata,
    ) as trace:
        try:
            graph_input: AgentState = {"question": request.question}
            if request.history:
                graph_input["history"] = [
                    message.model_dump() for message in request.history
                ]
            result = await graph_app.ainvoke(graph_input, config=_graph_config())
        except Exception as exc:
            if trace is not None:
                trace.update(level="ERROR", status_message=str(exc))
            logger.exception("HorRAGor graph failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The HorRAGor agent graph is unavailable.",
            ) from exc

        metadata = result.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        top_score = _safe_float(metadata.get("top_score"))
        has_evidence = bool(result.get("rag_results")) or bool(
            result.get("scraper_results")
        )
        resolution = metadata.get("entity_resolution")
        resolution_confidence = 0.0
        if isinstance(resolution, dict):
            resolution_confidence = _safe_float(resolution.get("confidence"))
        is_ambiguous = isinstance(resolution, dict) and resolution.get("status") == "ambiguous"
        route = str(metadata.get("route", result.get("route", "narration")))
        score = round(top_score * 10)
        if not top_score and has_evidence and resolution_confidence >= 0.9:
            score = 8
        verdict = JudgeVerdict(
            is_valid=has_evidence and not is_ambiguous,
            score=max(0, min(10, score)),
            justification=(
                "Response grounded in evidence for the resolved movie."
                if resolution_confidence >= 0.9 and has_evidence
                else "Response grounded in FAISS evidence."
                if route == "narration"
                else "Response grounded with the scraper branch after weak local evidence."
            ),
        )
        response = str(result.get("final_response", "")).strip()
        raw_token_usage = result.get("token_usage")
        token_usage: TokenUsageSummary | None = None
        if isinstance(raw_token_usage, dict) and raw_token_usage:
            try:
                token_usage = TokenUsageSummary.model_validate(raw_token_usage)
            except ValidationError:
                logger.warning("Ignoring malformed graph token usage")
        chat_response = ChatResponse(
            response=response or f"No reliable movie evidence was found for: {request.question}",
            verdict=verdict,
            token_usage=token_usage,
            metadata=metadata,
        )
        if trace is not None:
            trace.update(
                output=chat_response.response,
                metadata={
                    **trace_metadata,
                    "route": route,
                    "has_evidence": has_evidence,
                    "verdict_score": verdict.score,
                    "narration_mode": metadata.get("narration_mode"),
                },
            )
        record_graph_result(
            route,
            metadata.get("narration_mode"),
            token_usage.model_dump() if token_usage else None,
        )
        return chat_response


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> dict[str, Any]:
    """Report whether the data and optional narration services are ready."""
    try:
        gateway = get_movie_data_gateway()
        stats = await run_in_threadpool(gateway.stats)
        model_health = await run_in_threadpool(_model_health)
        return {
            "status": "healthy",
            "auth_enabled": settings.auth_enabled,
            "data_api": "ready" if settings.data_api_url else "local",
            "faiss_router": "ready",
            "records": int(stats.get("records", 0)),
            "dimension": int(stats.get("dimension", 0)),
            "narration_model": model_health,
        }
    except Exception as exc:
        logger.exception("FAISS health check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The movie retrieval index is unavailable.",
        ) from exc