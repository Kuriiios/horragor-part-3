"""Heterogeneous movie acquisition adapters required by Brief 1."""

from .base import MovieSource, SourceDependencyError, SourceNotConfigured
from .imdb_spark import ImdbSparkSource
from .imdb_sqlite import ImdbSqliteSource
from .kaggle import KaggleCsvSource
from .rotten_tomatoes import RottenTomatoesSource
from .tmdb import TmdbSource

__all__ = [
    "ImdbSparkSource",
    "ImdbSqliteSource",
    "KaggleCsvSource",
    "MovieSource",
    "RottenTomatoesSource",
    "SourceDependencyError",
    "SourceNotConfigured",
    "TmdbSource",
]