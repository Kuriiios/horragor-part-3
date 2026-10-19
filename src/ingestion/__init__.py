"""Brief 1 acquisition, normalization, reconciliation, and persistence pipeline."""

from .models import CanonicalMovie, MovieRecord
from .normalization import normalize_movie_record
from .reconciliation import reconcile_movies

__all__ = [
    "CanonicalMovie",
    "MovieRecord",
    "normalize_movie_record",
    "reconcile_movies",
]