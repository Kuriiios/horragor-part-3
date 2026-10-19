"""Central Loguru configuration with transparent standard-library interception."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from threading import RLock
from types import FrameType
from typing import Any

from loguru import logger

_configuration_lock = RLock()
_configured = False


class InterceptHandler(logging.Handler):
    """Forward standard-library records to Loguru without losing tracebacks."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame: FrameType | None = logging.currentframe()
        depth = 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _enabled(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def configure_logging(service: str) -> Any:
    """Configure process-wide structured sinks once and return a service logger."""
    global _configured
    with _configuration_lock:
        if not _configured:
            level = os.getenv("HORRAGOR_LOG_LEVEL", "INFO").strip().upper()
            serialize = _enabled(
                os.getenv("HORRAGOR_LOG_JSON"),
                default=os.getenv("HORRAGOR_ENVIRONMENT", "development").casefold()
                in {"production", "staging"},
            )
            logger.remove()
            logger.add(
                sys.stderr,
                level=level,
                serialize=serialize,
                backtrace=False,
                diagnose=False,
                enqueue=True,
            )
            log_file = os.getenv("HORRAGOR_LOG_FILE", "").strip()
            if log_file:
                path = Path(log_file)
                path.parent.mkdir(parents=True, exist_ok=True)
                logger.add(
                    path,
                    level=level,
                    serialize=True,
                    rotation=os.getenv("HORRAGOR_LOG_ROTATION", "10 MB"),
                    retention=os.getenv("HORRAGOR_LOG_RETENTION", "7 days"),
                    compression="gz",
                    enqueue=True,
                    backtrace=False,
                    diagnose=False,
                )
            logging.basicConfig(
                handlers=[InterceptHandler()],
                level=0,
                force=True,
            )
            for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
                standard_logger = logging.getLogger(logger_name)
                standard_logger.handlers = [InterceptHandler()]
                standard_logger.propagate = False
            _configured = True
        logger.configure(extra={"service": service})
    return logger.bind(service=service)