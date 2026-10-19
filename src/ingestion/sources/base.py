"""Shared acquisition source contracts and expected skip conditions."""

from __future__ import annotations

from typing import Protocol

from ..models import MovieRecord


class SourceNotConfigured(RuntimeError):
    """Raised when an external source lacks its required path or credential."""


class SourceDependencyError(RuntimeError):
    """Raised when an optional acquisition dependency is not installed."""


class MovieSource(Protocol):
    """One independently executable acquisition channel."""

    name: str

    def extract(self) -> list[MovieRecord]: ...