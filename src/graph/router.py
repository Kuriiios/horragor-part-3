"""Conditional routing rules for the HorRAGor graph."""

from __future__ import annotations

from ..models.state import AgentState

_WEB_TOOL_NAMES = {"scrape_detailed_synopsis"}


def should_scrape_or_narrate(state: AgentState) -> str:
	"""Route to web enrichment when local evidence is insufficient."""
	metadata = state.get("metadata", {})
	if isinstance(metadata, dict) and metadata.get("scope") == "out_of_scope":
		return "narration"
	if state.get("local_evidence_sufficient") is False:
		return "scraper"
	pending_tool_calls = state.get("pending_tool_calls", [])
	if isinstance(pending_tool_calls, list) and any(
		isinstance(call, dict)
		and call.get("name") in _WEB_TOOL_NAMES
		for call in pending_tool_calls
	):
		return "scraper"
	return "narration"
