"""FastAPI entry point for the private HorRAGor movie data layer."""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status

from ..config import settings
from ..http_observability import HttpObservabilityMiddleware
from ..logging_config import configure_logging
from ..metrics import metrics_response
from ..tools.faiss_store import MovieFaissStore, get_movie_store
from .schemas import (
    DataHealthResponse,
    MovieHit,
    MovieRecordResponse,
    MovieSearchResponse,
    SimilarMoviesResponse,
    StoreStatsResponse,
)

logger = logging.getLogger(__name__)


def _store_or_raise() -> MovieFaissStore:
    try:
        return get_movie_store()
    except Exception as exc:
        logger.exception("Movie data store is unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The movie data store is unavailable.",
        ) from exc


def require_internal_api_key(
    provided_key: Annotated[
        str | None,
        Header(alias="X-Internal-API-Key"),
    ] = None,
) -> None:
    """Validate the optional service credential used inside the private network."""
    expected_key = settings.data_api_key
    if expected_key and (
        provided_key is None or not secrets.compare_digest(provided_key, expected_key)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal service credential.",
        )


InternalAccess = Annotated[None, Depends(require_internal_api_key)]


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging("data-api")
    if (
        settings.environment in {"production", "staging"}
        and (not settings.data_api_key or len(settings.data_api_key) < 32)
    ):
        raise RuntimeError(
            "HORRAGOR_DATA_API_KEY must contain at least 32 characters in production"
        )
    store = _store_or_raise()
    logger.info("Movie data API ready: %s", store.stats())
    yield
    logger.info("Movie data API stopped")


app = FastAPI(
    title="HorRAGor Private Movie Data API",
    description="Network-isolated access to canonical movie records and FAISS retrieval.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(HttpObservabilityMiddleware, service="data-api")


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    """Expose process metrics to the private Prometheus service."""
    return metrics_response()


@app.get("/v1/stats", response_model=StoreStatsResponse)
def store_stats(_: InternalAccess) -> dict[str, Any]:
    """Return index metadata without exposing movie content."""
    return _store_or_raise().stats()


@app.get("/v1/movies/search", response_model=MovieSearchResponse)
def search_movies(
    _: InternalAccess,
    query: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(5, ge=1, le=50),
) -> MovieSearchResponse:
    """Search canonical records by title, synopsis, genre, or keyword."""
    store = _store_or_raise()
    return MovieSearchResponse(
        query=query,
        results=[
            MovieHit.model_validate(result)
            for result in store.search(query, limit=limit)
        ],
        index_size=store.count,
    )


@app.get("/v1/movies/{movie_id}/similar", response_model=SimilarMoviesResponse)
def similar_movies(
    movie_id: str,
    _: InternalAccess,
    limit: int = Query(5, ge=1, le=10),
) -> SimilarMoviesResponse:
    """Return neighbors calculated only from synopsis vectors."""
    store = _store_or_raise()
    if store.get_by_id(movie_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found.")
    return SimilarMoviesResponse(
        movie_id=movie_id,
        results=[
            MovieHit.model_validate(result)
            for result in store.find_similar_by_overview(movie_id, limit=limit)
        ],
        index_size=store.count,
    )


@app.get("/v1/movies/{movie_id}", response_model=MovieRecordResponse)
def get_movie(movie_id: str, _: InternalAccess) -> MovieRecordResponse:
    """Return one canonical movie by stable source identifier."""
    movie = _store_or_raise().get_by_id(movie_id)
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found.")
    return MovieRecordResponse(movie=movie)


@app.get("/health", response_model=DataHealthResponse)
def health_check() -> DataHealthResponse:
    """Report data-layer readiness without requiring a service credential."""
    store = _store_or_raise()
    return DataHealthResponse(
        status="healthy",
        service="data-api",
        records=store.count,
        dimension=store.dimension,
    )