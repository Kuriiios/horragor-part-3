"""Shared state passed between HorRAGor graph nodes."""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
	"""Data contract shared by the RAG, scraper, and narration agents."""

	question: str
	history: list[dict[str, Any]]
	resolved_query: str
	rag_results: list[dict[str, Any]]
	local_context: str
	local_evidence_sufficient: bool
	scraper_results: list[dict[str, Any]]
	tool_results: dict[str, Any]
	pending_tool_calls: list[dict[str, Any]]
	final_response: str
	route: str
	token_usage: dict[str, Any]
	metadata: dict[str, Any]
