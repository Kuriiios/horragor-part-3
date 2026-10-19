"""Bounded TMDB horror-film acquisition through the official REST API."""

from __future__ import annotations

from typing import Any

import requests

from ..models import MovieRecord
from ..normalization import normalize_movie_record
from .base import SourceNotConfigured


class TmdbSource:
    name = "tmdb"

    def __init__(
        self,
        *,
        bearer_token: str | None = None,
        api_key: str | None = None,
        pages: int = 5,
        timeout_seconds: float = 10.0,
        language: str = "en-US",
        session: requests.Session | None = None,
    ) -> None:
        self.bearer_token = (bearer_token or "").strip() or None
        self.api_key = (api_key or "").strip() or None
        self.pages = max(1, min(int(pages), 50))
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.language = language
        self.session = session or requests.Session()

    def extract(self) -> list[MovieRecord]:
        if not self.bearer_token and not self.api_key:
            raise SourceNotConfigured("TMDB_BEARER_TOKEN or TMDB_API_KEY is required")
        records: list[MovieRecord] = []
        headers = {"Authorization": f"Bearer {self.bearer_token}"} if self.bearer_token else {}
        for page in range(1, self.pages + 1):
            params: dict[str, Any] = {
                "with_genres": "27",
                "include_adult": "false",
                "include_video": "false",
                "language": self.language,
                "page": page,
                "sort_by": "popularity.desc",
            }
            if self.api_key:
                params["api_key"] = self.api_key
            response = self.session.get(
                "https://api.themoviedb.org/3/discover/movie",
                params=params,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            results = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(results, list):
                raise ValueError("TMDB response is missing a results list")
            for result in results:
                if not isinstance(result, dict):
                    continue
                raw = dict(result)
                raw["genres"] = ["Horror"]
                record = normalize_movie_record(raw, self.name)
                if record is not None:
                    records.append(record)
            total_pages = payload.get("total_pages") if isinstance(payload, dict) else None
            if isinstance(total_pages, int) and page >= total_pages:
                break
        return records