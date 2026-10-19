"""Movie data access boundary for local development and private HTTP deployments."""

from __future__ import annotations

import logging
from threading import RLock, local
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import settings

if TYPE_CHECKING:
    from .tools.faiss_store import MovieFaissStore

logger = logging.getLogger(__name__)


class DataGatewayUnavailable(RuntimeError):
    """Raised when the private movie data service cannot satisfy a request."""


@runtime_checkable
class MovieDataGateway(Protocol):
    """Operations consumed by the graph and the intelligence API."""

    @property
    def count(self) -> int: ...

    @property
    def dimension(self) -> int: ...

    def stats(self) -> dict[str, Any]: ...

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]: ...

    def get_by_id(self, movie_id: str | int) -> dict[str, str] | None: ...

    def find_similar_by_overview(
        self,
        movie_id: str | int,
        limit: int = 5,
    ) -> list[dict[str, Any]]: ...


class LocalMovieDataGateway:
    """In-process adapter used by tests and single-process development."""

    def __init__(self, store: MovieFaissStore | None = None) -> None:
        self._store = store

    @property
    def store(self) -> MovieFaissStore:
        if self._store is None:
            from .tools.faiss_store import get_movie_store

            self._store = get_movie_store()
        return self._store

    @property
    def count(self) -> int:
        return self.store.count

    @property
    def dimension(self) -> int:
        return self.store.dimension

    def stats(self) -> dict[str, Any]:
        return self.store.stats()

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return self.store.search(query, limit=limit)

    def get_by_id(self, movie_id: str | int) -> dict[str, str] | None:
        return self.store.get_by_id(movie_id)

    def find_similar_by_overview(
        self,
        movie_id: str | int,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        return self.store.find_similar_by_overview(movie_id, limit=limit)


class HttpMovieDataGateway:
    """HTTP adapter for the private data API with connection reuse and timeouts."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 5.0,
        session: requests.Session | None = None,
    ) -> None:
        normalized_url = base_url.strip().rstrip("/")
        if not normalized_url:
            raise ValueError("base_url must not be empty")
        self.base_url = normalized_url
        self.timeout_seconds = max(0.5, float(timeout_seconds))
        self._provided_session = session
        self._thread_local = local()
        self._headers = {"X-Internal-API-Key": api_key} if api_key else {}
        self._stats: dict[str, Any] | None = None

    @property
    def _session(self) -> requests.Session:
        if self._provided_session is not None:
            return self._provided_session
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            retry_policy = Retry(
                total=2,
                connect=2,
                read=0,
                status=2,
                allowed_methods=frozenset({"GET"}),
                status_forcelist=(502, 503, 504),
                backoff_factor=0.2,
                raise_on_status=False,
            )
            adapter = HTTPAdapter(
                max_retries=retry_policy,
                pool_connections=10,
                pool_maxsize=20,
            )
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            self._thread_local.session = session
        return session

    def _request_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> Any:
        try:
            response = self._session.get(
                f"{self.base_url}{path}",
                params=params,
                headers=self._headers,
                timeout=self.timeout_seconds,
            )
            if allow_not_found and response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise DataGatewayUnavailable(
                f"Movie data service request failed for {path}"
            ) from exc

    def _remember_stats(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        index_size = payload.get("index_size")
        dimension = payload.get("dimension")
        current = dict(self._stats or {})
        if isinstance(index_size, int):
            current["records"] = index_size
        if isinstance(dimension, int):
            current["dimension"] = dimension
        self._stats = current or None

    @property
    def count(self) -> int:
        return int(self.stats().get("records", 0))

    @property
    def dimension(self) -> int:
        return int(self.stats().get("dimension", 0))

    def stats(self) -> dict[str, Any]:
        if self._stats is None or "records" not in self._stats:
            payload = self._request_json("/v1/stats")
            if not isinstance(payload, dict):
                raise DataGatewayUnavailable("Movie data service returned invalid stats")
            self._stats = dict(payload)
        return dict(self._stats)

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        payload = self._request_json(
            "/v1/movies/search",
            params={"query": query, "limit": limit},
        )
        self._remember_stats(payload)
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise DataGatewayUnavailable("Movie data service returned invalid search results")
        return [result for result in results if isinstance(result, dict)]

    def get_by_id(self, movie_id: str | int) -> dict[str, str] | None:
        payload = self._request_json(
            f"/v1/movies/{quote(str(movie_id), safe='')}",
            allow_not_found=True,
        )
        if payload is None:
            return None
        movie = payload.get("movie") if isinstance(payload, dict) else None
        if not isinstance(movie, dict):
            raise DataGatewayUnavailable("Movie data service returned an invalid movie")
        return {str(key): str(value) for key, value in movie.items()}

    def find_similar_by_overview(
        self,
        movie_id: str | int,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        payload = self._request_json(
            f"/v1/movies/{quote(str(movie_id), safe='')}/similar",
            params={"limit": limit},
            allow_not_found=True,
        )
        if payload is None:
            return []
        self._remember_stats(payload)
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise DataGatewayUnavailable("Movie data service returned invalid similarity results")
        return [result for result in results if isinstance(result, dict)]


_gateway: MovieDataGateway | None = None
_gateway_signature: tuple[str | None, str | None, float] | None = None
_gateway_lock = RLock()


def get_movie_data_gateway() -> MovieDataGateway:
    """Return the configured local or private HTTP data gateway singleton."""
    global _gateway, _gateway_signature
    signature = (
        settings.data_api_url,
        settings.data_api_key,
        settings.data_api_timeout_seconds,
    )
    with _gateway_lock:
        if _gateway is not None and _gateway_signature == signature:
            return _gateway
        if settings.data_api_url:
            logger.info("Using private movie data API at %s", settings.data_api_url)
            _gateway = HttpMovieDataGateway(
                settings.data_api_url,
                api_key=settings.data_api_key,
                timeout_seconds=settings.data_api_timeout_seconds,
            )
        else:
            _gateway = LocalMovieDataGateway()
        _gateway_signature = signature
        return _gateway