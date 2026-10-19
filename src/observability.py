"""Optional Langfuse integrations for HorRAGor runtime tracing."""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _environment_file in (_PROJECT_ROOT / ".env", _PROJECT_ROOT / ".ENV"):
	if _environment_file.is_file():
		load_dotenv(_environment_file, override=False)


def is_langfuse_configured() -> bool:
	"""Return whether the required Langfuse credentials are available."""
	if os.getenv("LANGFUSE_TRACING_ENABLED", "true").strip().casefold() in {
		"0",
		"false",
		"no",
		"off",
	}:
		return False
	return bool(
		os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
		and os.getenv("LANGFUSE_SECRET_KEY", "").strip()
	)


def get_langfuse_client() -> Any | None:
	"""Return the configured SDK singleton without initializing disabled clients."""
	if not is_langfuse_configured():
		return None
	try:
		from langfuse import get_client

		return get_client()
	except (ImportError, RuntimeError, ValueError) as exc:
		logger.warning("Langfuse client is unavailable: %s", exc)
		return None


def create_langfuse_handler() -> Any | None:
	"""Create one callback for a graph run when Langfuse is configured."""
	if get_langfuse_client() is None:
		return None
	try:
		from langfuse.langchain import CallbackHandler

		return CallbackHandler()
	except (ImportError, RuntimeError, ValueError) as exc:
		logger.warning("Langfuse graph callback is unavailable: %s", exc)
		return None


def start_langfuse_observation(
	*,
	name: str,
	as_type: str = "span",
	input: Any = None,
	metadata: dict[str, Any] | None = None,
	model: str | None = None,
	model_parameters: dict[str, Any] | None = None,
) -> Any:
	"""Start a v4 observation, or a no-op context when tracing is disabled."""
	client = get_langfuse_client()
	if client is None:
		return nullcontext(None)
	observation_kwargs: dict[str, Any] = {"name": name, "as_type": as_type}
	if input is not None:
		observation_kwargs["input"] = input
	if metadata is not None:
		observation_kwargs["metadata"] = metadata
	if model is not None:
		observation_kwargs["model"] = model
	if model_parameters is not None:
		observation_kwargs["model_parameters"] = model_parameters
	return client.start_as_current_observation(**observation_kwargs)


@contextmanager
def _chat_trace_context(
	client: Any,
	*,
	name: str,
	question: str,
	metadata: dict[str, Any],
	attributes: dict[str, Any],
	propagate_attributes: Any,
) -> Generator[Any, None, None]:

	with client.start_as_current_observation(
		name=name,
		as_type="agent",
		input={"question": question},
		metadata=metadata,
	) as trace, propagate_attributes(**attributes):
		yield trace


def start_langfuse_chat_trace(
	*,
	question: str,
	session_id: str | None,
	metadata: dict[str, Any],
) -> Any:
	"""Create one trace for a chat turn and propagate its request attributes."""
	client = get_langfuse_client()
	if client is None:
		return nullcontext(None)
	try:
		from langfuse import propagate_attributes
	except (ImportError, RuntimeError, ValueError) as exc:
		logger.warning("Langfuse trace context is unavailable: %s", exc)
		return nullcontext(None)

	attributes: dict[str, Any] = {
		"trace_name": "answer-chat-question",
		"tags": ["horragor", "chat"],
	}
	if session_id:
		attributes["session_id"] = session_id
	environment = os.getenv("LANGFUSE_TRACING_ENVIRONMENT", "").strip()
	if environment:
		attributes["environment"] = environment
	return _chat_trace_context(
		client,
		name="answer-chat-question",
		question=question,
		metadata=metadata,
		attributes=attributes,
		propagate_attributes=propagate_attributes,
	)


def shutdown_langfuse() -> None:
	"""Flush and close the singleton during API shutdown when tracing is enabled."""
	client = get_langfuse_client()
	if client is None:
		return
	try:
		client.shutdown()
	except (RuntimeError, ValueError) as exc:
		logger.warning("Langfuse shutdown failed: %s", exc)


def langfuse_usage_details(usage: Any) -> dict[str, int] | None:
	"""Map OpenAI-compatible usage fields to Langfuse usage fields."""
	if not isinstance(usage, dict):
		return None

	field_aliases = {
		"input": ("prompt_tokens", "input_tokens"),
		"output": ("completion_tokens", "output_tokens"),
		"total": ("total_tokens",),
	}
	details: dict[str, int] = {}
	for target, aliases in field_aliases.items():
		for alias in aliases:
			value = usage.get(alias)
			if isinstance(value, int) and not isinstance(value, bool):
				details[target] = value
				break
	return details or None