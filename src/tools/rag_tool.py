"""RAG-facing helpers backed by the local FAISS movie store."""

from .faiss_store import MovieFaissStore, get_movie_store


def search_movies(query: str, limit: int = 5) -> list[dict]:
	"""Search the local movie knowledge base."""
	return get_movie_store().search(query, limit=limit)


def get_router() -> MovieFaissStore:
	"""Compatibility name for graph code that expects a retrieval router."""
	return get_movie_store()
