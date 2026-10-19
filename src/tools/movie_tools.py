"""Compatibility exports for the five-tool Brief 2 contract."""

from .brief2_tools import (
    ALL_TOOLS,
    MODEL_TOOL_REGISTRY,
    MODEL_TOOL_SPECS,
    calculate_movie_age,
    find_similar_horror_movies,
    horror_survival_simulator,
    query_movie_metadata,
    scrape_detailed_synopsis,
)

__all__ = [
    "ALL_TOOLS",
    "MODEL_TOOL_REGISTRY",
    "MODEL_TOOL_SPECS",
    "calculate_movie_age",
    "find_similar_horror_movies",
    "horror_survival_simulator",
    "query_movie_metadata",
    "scrape_detailed_synopsis",
]
