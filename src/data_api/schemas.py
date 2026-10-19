"""Pydantic contracts exposed by the private movie data API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MovieHit(BaseModel):
    """One indexed movie and its cosine similarity score."""

    score: float
    movie: dict[str, str]


class MovieSearchResponse(BaseModel):
    """Bounded search response from the FAISS index."""

    query: str
    results: list[MovieHit]
    index_size: int = Field(ge=0)


class MovieRecordResponse(BaseModel):
    """One canonical movie record."""

    movie: dict[str, str]


class SimilarMoviesResponse(BaseModel):
    """Movies selected using synopsis-only similarity."""

    movie_id: str
    results: list[MovieHit]
    index_size: int = Field(ge=0)


class StoreStatsResponse(BaseModel):
    """Operational details for the persisted FAISS store."""

    records: int = Field(ge=0)
    dimension: int = Field(gt=0)
    index_path: str
    metadata_path: str
    source_path: str


class DataHealthResponse(BaseModel):
    """Readiness payload consumed by Docker and Uptime Kuma."""

    status: str
    service: str
    records: int = Field(ge=0)
    dimension: int = Field(gt=0)
    details: dict[str, Any] = Field(default_factory=dict)