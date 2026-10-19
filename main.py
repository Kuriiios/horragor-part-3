"""Compatibility ASGI entry point for ``uvicorn main:app``."""

from src.API.main_api import app

__all__ = ["app"]
