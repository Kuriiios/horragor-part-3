"""Brief 2 tool execution inside the Brief 3 peer-to-peer graph."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

import requests

from ..config import settings
from ..data_gateway import MovieDataGateway, get_movie_data_gateway
from ..metrics import record_tool_call
from ..models.state import AgentState
from ..observability import (
    langfuse_usage_details,
    start_langfuse_observation,
)
from ..tools.brief2_tools import (
    MODEL_TOOL_SPECS,
    calculate_movie_age,
    find_similar_horror_movies,
    horror_survival_simulator,
    query_movie_metadata,
    scrape_detailed_synopsis,
)
from ..tools.movie_resolution import resolve_movie_reference
from ..tools.scraper_tool import search_web

logger = logging.getLogger(__name__)

TokenUsage = dict[str, int]
TokenUsageCallback = Callable[[TokenUsage], None]

_WEB_TOOL_NAME = "scrape_detailed_synopsis"
_MOVIE_SCOPE_PATTERN = re.compile(
    r"\b(?:movie|movies|film|films|cinema|horror|acteur|acteurs|actor|actors|"
    r"cast|director|directeur|directrice|genre|rating|note|plot|synopsis|"
    r"recommend|recommendation|similar|surviv|release|sortie|cinema|horreur)\b",
    re.IGNORECASE,
)
_CAPABILITIES_RESPONSE = (
    "Je suis HorRAGor, un assistant specialise dans les films d'horreur. "
    "Je peux donner les informations d'un film (realisateur, casting, annee, "
    "genres et note), recommander des films aux synopsis similaires, chercher "
    "des details supplementaires sur Wikipedia, calculer l'age d'un film et "
    "proposer un scenario de survie fictif. Je ne traite pas les sujets hors cinema."
)
_TOOL_RESULT_KEYS = {
    "query_movie_metadata": "movie_metadata",
    "find_similar_horror_movies": "similar_movies",
    "calculate_movie_age": "movie_age",
    "horror_survival_simulator": "survival_simulation",
    "scrape_detailed_synopsis": "detailed_synopsis",
}
_TOOL_OBSERVATION_NAMES = {
    "query_movie_metadata": "query-movie-metadata",
    "find_similar_horror_movies": "find-similar-horror-movies",
    "scrape_detailed_synopsis": "scrape-detailed-synopsis",
    "calculate_movie_age": "calculate-movie-age",
    "horror_survival_simulator": "simulate-horror-survival",
}


def _copy_metadata(state: AgentState) -> dict[str, Any]:
    metadata = state.get("metadata", {})
    return dict(metadata) if isinstance(metadata, dict) else {}


def _capture_token_usage(
    usage_by_generation: dict[str, TokenUsage],
    generation_name: str,
) -> TokenUsageCallback:
    def capture(usage: TokenUsage) -> None:
        usage_by_generation[generation_name] = dict(usage)

    return capture


def _token_usage_by_generation(value: Any) -> dict[str, TokenUsage]:
    if not isinstance(value, dict) or not isinstance(value.get("by_generation"), dict):
        return {}
    usage_by_generation: dict[str, TokenUsage] = {}
    for generation_name, usage in value["by_generation"].items():
        if not isinstance(generation_name, str) or not isinstance(usage, dict):
            continue
        normalized = {
            key: token_count
            for key, token_count in usage.items()
            if key in {"input", "output", "total"}
            and isinstance(token_count, int)
            and not isinstance(token_count, bool)
        }
        if normalized:
            usage_by_generation[generation_name] = normalized
    return usage_by_generation


def _token_usage_summary(
    usage_by_generation: dict[str, TokenUsage],
) -> dict[str, Any] | None:
    if not usage_by_generation:
        return None
    return {
        "input": sum(usage.get("input", 0) for usage in usage_by_generation.values()),
        "output": sum(usage.get("output", 0) for usage in usage_by_generation.values()),
        "total": sum(usage.get("total", 0) for usage in usage_by_generation.values()),
        "by_generation": {
            generation_name: dict(usage)
            for generation_name, usage in usage_by_generation.items()
        },
    }


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _score(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _local_context(results: list[dict[str, Any]]) -> str:
    lines = []
    for hit in results:
        movie = hit.get("movie") if isinstance(hit, dict) else None
        if not isinstance(movie, dict):
            continue
        lines.append(
            " | ".join(
                part for part in (
                    f"Movie ID: {movie.get('id', '')}",
                    f"Title: {movie.get('title', '')}",
                    f"Release date: {movie.get('release_date', '')}",
                    f"Genres: {movie.get('genre_names', '')}",
                    f"Synopsis: {_clip(movie.get('overview', ''), 900)}",
                ) if part
            )
        )
    return _clip("\n".join(lines), settings.max_context_chars)


def _tool_functions() -> dict[str, Any]:
    return {
        "query_movie_metadata": query_movie_metadata,
        "find_similar_horror_movies": find_similar_horror_movies,
        "scrape_detailed_synopsis": scrape_detailed_synopsis,
        "calculate_movie_age": calculate_movie_age,
        "horror_survival_simulator": horror_survival_simulator,
    }


def _tool_spec(name: str) -> dict[str, Any] | None:
    return next((spec for spec in MODEL_TOOL_SPECS if spec["name"] == name), None)


def _parse_tool_plan(content: str | None) -> list[dict[str, Any]] | None:
    """Accept only calls that satisfy the five model-visible JSON schemas."""
    if not content:
        return None
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        text = match.group(0)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    calls = payload.get("tool_calls") if isinstance(payload, dict) else None
    if not isinstance(calls, list):
        return None

    valid_calls: list[dict[str, Any]] = []
    for raw_call in calls[:5]:
        if not isinstance(raw_call, dict):
            continue
        name = raw_call.get("name")
        arguments = raw_call.get("arguments")
        if not isinstance(name, str) or not isinstance(arguments, dict):
            continue
        spec = _tool_spec(name)
        if spec is None:
            continue
        parameters = spec["parameters"]
        properties = parameters["properties"]
        if set(arguments) - set(properties):
            continue
        if any(key not in arguments or arguments[key] in (None, "") for key in parameters.get("required", [])):
            continue
        is_valid = True
        for key, value in arguments.items():
            schema = properties[key]
            expected_type = schema.get("type")
            if expected_type == "string" and not isinstance(value, str):
                is_valid = False
            if expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                is_valid = False
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and (
                    value < schema.get("minimum", value)
                    or value > schema.get("maximum", value)
                )
            ):
                is_valid = False
        if is_valid:
            valid_calls.append({"name": name, "arguments": arguments})
    return valid_calls


def _tool_planner_prompt(question: str, local_context: str, resolution: dict[str, Any]) -> str:
    return (
        "You select Python tools for a horror-film assistant. Return only one JSON object: "
        '{"tool_calls":[{"name":"tool_name","arguments":{}}]}. '
        "You can choose zero or more calls. Use only the supplied schemas. "
        "Use metadata for basic facts, similarity for recommendations, age for an age question, "
        "and survival only for an explicitly fictional survival question. Use detailed scraping only "
        "when the user asks for deep plot or anecdotal detail missing from the local evidence. "
        "Never invent a movie ID, title, release year, or synopsis.\n\n"
        f"RESOLUTION: {json.dumps(resolution, ensure_ascii=True)}\n"
        f"LOCAL EVIDENCE:\n{local_context or 'none'}\n\n"
        f"TOOL SCHEMAS:\n{json.dumps(MODEL_TOOL_SPECS, ensure_ascii=True)}\n\n"
        f"USER QUESTION:\n{question}"
    )


def _post_local_llm(
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    temperature: float,
    observation_name: str = "horragor-llm",
    usage_callback: TokenUsageCallback | None = None,
) -> str | None:
    if not settings.llm_base_url:
        return None
    with start_langfuse_observation(
        name=observation_name,
        as_type="generation",
        input=messages,
        model=settings.llm_model,
        model_parameters={"max_tokens": max_tokens, "temperature": temperature},
    ) as generation:
        try:
            response = requests.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                json={
                    "model": settings.llm_model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                headers={"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"},
                timeout=settings.llm_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            usage_details = langfuse_usage_details(body.get("usage"))
            if usage_callback is not None and usage_details is not None:
                usage_callback(usage_details)
            if generation is not None:
                generation.update(
                    output=content,
                    usage_details=usage_details,
                )
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            if generation is not None:
                generation.update(level="ERROR", status_message=str(exc))
            logger.warning("Local model request failed: %s", exc)
            return None
    return str(content).strip() or None


def _call_tool_planner(
    question: str,
    local_context: str,
    resolution: dict[str, Any],
    usage_callback: TokenUsageCallback | None = None,
) -> list[dict[str, Any]] | None:
    content = _post_local_llm(
        [
            {"role": "system", "content": "You are a strict JSON tool planner. Output JSON only."},
            {"role": "user", "content": _tool_planner_prompt(question, local_context, resolution)},
        ],
        max_tokens=min(settings.llm_max_tokens, 400),
        temperature=0.0,
        observation_name="plan-tool-calls",
        usage_callback=usage_callback,
    )
    return _parse_tool_plan(content)


def _resolved_movie(results: list[dict[str, Any]], movie_id: Any) -> dict[str, Any] | None:
    for result in results:
        movie = result.get("movie") if isinstance(result, dict) else None
        if isinstance(movie, dict) and str(movie.get("id", "")) == str(movie_id):
            return movie
    return None


def _safe_tool_calls(calls: list[dict[str, Any]], movie: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Bind planner calls to known local values before executing them."""
    safe_calls: list[dict[str, Any]] = []
    movie_id = str(movie.get("id", "")) if movie else ""
    movie_title = str(movie.get("title", "")) if movie else ""
    release_year_match = re.search(r"\b(\d{4})\b", str(movie.get("release_date", ""))) if movie else None
    overview = str(movie.get("overview", "")) if movie else ""
    for call in calls:
        name = call["name"]
        arguments = dict(call["arguments"])
        if name in {"query_movie_metadata", "find_similar_horror_movies"}:
            if not movie_id:
                continue
            arguments["movie_id"] = movie_id
        elif name == "scrape_detailed_synopsis":
            if not movie_title:
                continue
            arguments["movie_title"] = movie_title
        elif name == "calculate_movie_age":
            if release_year_match is None:
                continue
            arguments["release_year"] = int(release_year_match.group(1))
        elif name == "horror_survival_simulator":
            if len(overview) < 20:
                continue
            arguments["detailed_synopsis"] = overview
        safe_calls.append({"name": name, "arguments": arguments})
    return safe_calls


def _execute_tool_call(call: dict[str, Any]) -> Any:
    raw_name = call.get("name")
    if not isinstance(raw_name, str):
        return None
    function = _tool_functions().get(raw_name)
    arguments = call.get("arguments")
    if function is None or not isinstance(arguments, dict):
        return None
    name = raw_name
    with start_langfuse_observation(
        name=_TOOL_OBSERVATION_NAMES.get(name, "execute-movie-tool"),
        as_type="tool",
        input=arguments,
        metadata={"tool_name": name},
    ) as tool_observation:
        try:
            result = function(**arguments)
            if tool_observation is not None:
                tool_observation.update(output=result)
            record_tool_call(name, "success" if result is not None else "empty")
            return result
        except (TypeError, ValueError, KeyError) as exc:
            if tool_observation is not None:
                tool_observation.update(
                    output={"error": type(exc).__name__},
                    level="ERROR",
                    status_message=str(exc),
                )
            record_tool_call(name, "error")
            logger.warning("Tool %s failed: %s", name, exc)
            return None


def _tool_metadata(results: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in results.items() if key in set(_TOOL_RESULT_KEYS.values())}


def _is_movie_question(question: str) -> bool:
    return bool(_MOVIE_SCOPE_PATTERN.search(question))


def _retrieve_movie_evidence(
    question: str,
    history: list[dict[str, Any]],
) -> tuple[MovieDataGateway, dict[str, Any], list[dict[str, Any]]]:
    """Resolve and retrieve local evidence under one retriever observation."""
    store = get_movie_data_gateway()
    with start_langfuse_observation(
        name="retrieve-movie-evidence",
        as_type="retriever",
        input={"query": question, "limit": settings.rag_limit},
        metadata={
            "index": "faiss",
            "source": "private-data-api" if settings.data_api_url else "aggregated_movies.csv",
        },
    ) as retrieval_observation:
        resolution = resolve_movie_reference(store, question, history)
        resolved_id = resolution.get("movie_id")
        if not resolved_id and not _is_movie_question(question):
            if retrieval_observation is not None:
                retrieval_observation.update(
                    output={"scope": "out_of_scope", "match_count": 0}
                )
            return store, resolution, []
        if resolved_id:
            movie = store.get_by_id(resolved_id)
            results = [{"score": 1.0, "movie": movie}] if isinstance(movie, dict) else []
        else:
            results = store.search(question, limit=settings.rag_limit)
            if results and _score(results[0].get("score")) < settings.local_score_threshold:
                results = []
        if retrieval_observation is not None:
            retrieval_observation.update(
                output={
                    "scope": "movie",
                    "match_count": len(results),
                    "top_score": _score(results[0].get("score")) if results else 0.0,
                    "resolved_movie_id": str(resolved_id) if resolved_id else None,
                }
            )
    return store, resolution, results


def rag_node(state: AgentState) -> dict[str, Any]:
    """Retrieve local evidence, plan only Brief 2 tools, and execute local calls."""
    question = " ".join(str(state.get("question", "")).split())
    if not question:
        return {
            "rag_results": [],
            "local_context": "",
            "local_evidence_sufficient": False,
            "tool_results": {},
            "pending_tool_calls": [],
            "metadata": _copy_metadata(state),
        }
    history = state.get("history", [])
    history = history if isinstance(history, list) else []
    store, resolution, results = _retrieve_movie_evidence(question, history)
    resolved_id = resolution.get("movie_id")
    if not resolved_id and not _is_movie_question(question):
        metadata = _copy_metadata(state)
        metadata.update(
            {
                "source": "none",
                "index_size": store.count,
                "matches": [],
                "top_score": 0.0,
                "entity_resolution": resolution,
                "scope": "out_of_scope",
                "tools_used": [],
                "tool_calls": [],
                "tools": {},
            }
        )
        return {
            "rag_results": [],
            "local_context": "",
            "local_evidence_sufficient": True,
            "tool_results": {},
            "pending_tool_calls": [],
            "metadata": metadata,
        }
    local_context = _local_context(results)
    canonical_movie = _resolved_movie(results, resolved_id)
    usage_by_generation: dict[str, TokenUsage] = {}
    planned_calls = _call_tool_planner(
        question,
        local_context,
        resolution,
        usage_callback=_capture_token_usage(usage_by_generation, "plan-tool-calls"),
    ) or []
    tool_calls = _safe_tool_calls(planned_calls, canonical_movie)
    pending_tool_calls = [call for call in tool_calls if call["name"] == _WEB_TOOL_NAME]
    local_evidence_sufficient = bool(results and local_context)
    if pending_tool_calls:
        local_evidence_sufficient = False
    if not local_evidence_sufficient and canonical_movie:
        pending_tool_calls = [
            {
                "name": _WEB_TOOL_NAME,
                "arguments": {"movie_title": str(canonical_movie.get("title", ""))},
            }
        ]
        tool_calls = [
            call for call in tool_calls if call["name"] != _WEB_TOOL_NAME
        ] + pending_tool_calls
    tool_results: dict[str, Any] = {}
    executed_tools: list[str] = []
    for call in tool_calls:
        if call in pending_tool_calls:
            continue
        result = _execute_tool_call(call)
        if result is not None:
            tool_results[_TOOL_RESULT_KEYS[call["name"]]] = result
            executed_tools.append(call["name"])
    metadata = _copy_metadata(state)
    metadata.update(
        {
            "source": "faiss",
            "index_size": store.count,
            "matches": [
                {"id": movie.get("id", ""), "title": movie.get("title", ""), "score": float(hit.get("score", 0.0))}
                for hit in results if isinstance(hit, dict) and isinstance((movie := hit.get("movie")), dict)
            ],
            "top_score": float(results[0].get("score", 0.0)) if results else 0.0,
            "local_evidence_sufficient": local_evidence_sufficient,
            "entity_resolution": resolution,
            "tools_used": executed_tools + [call["name"] for call in pending_tool_calls],
            "tool_calls": tool_calls,
            "tools": _tool_metadata(tool_results),
        }
    )
    token_usage = _token_usage_summary(usage_by_generation)
    return {
        "resolved_query": str(canonical_movie.get("title", "")) if canonical_movie else "",
        "rag_results": results,
        "local_context": local_context,
        "local_evidence_sufficient": local_evidence_sufficient,
        "tool_results": tool_results,
        "pending_tool_calls": pending_tool_calls,
        "token_usage": token_usage or {},
        "metadata": metadata,
    }


def scraper_node(state: AgentState) -> dict[str, Any]:
    """Enrich the dossier with bounded web evidence before narration."""
    calls = state.get("pending_tool_calls", [])
    calls = calls if isinstance(calls, list) else []
    tool_results = dict(state.get("tool_results", {})) if isinstance(state.get("tool_results"), dict) else {}
    scraper_results: list[dict[str, Any]] = []
    for call in calls:
        if not isinstance(call, dict) or call.get("name") != _WEB_TOOL_NAME:
            continue
        result = _execute_tool_call(call)
        if isinstance(result, list):
            scraper_results.extend(item for item in result if isinstance(item, dict))
            tool_results["detailed_synopsis"] = result
    if not calls:
        query = " ".join(str(state.get("question", "")).split())
        if query:
            result = search_web(query)
            if isinstance(result, list):
                scraper_results.extend(item for item in result if isinstance(item, dict))
                tool_results["web_search"] = result
    metadata = _copy_metadata(state)
    metadata.update(
        {
            "source": "faiss+wikipedia" if scraper_results else "faiss",
            "scraper_results": len(scraper_results),
            "tools": _tool_metadata(tool_results),
        }
    )
    return {"scraper_results": scraper_results, "tool_results": tool_results, "pending_tool_calls": [], "route": "scraper", "metadata": metadata}


def _narration_context(state: AgentState) -> str:
    sections = [f"LOCAL EVIDENCE:\n{state.get('local_context', '') or 'none'}"]
    scraper_results = state.get("scraper_results", [])
    if isinstance(scraper_results, list) and scraper_results:
        web_evidence: list[str] = []
        for result in scraper_results:
            if not isinstance(result, dict):
                continue
            web_evidence.append(_clip(result.get("snippet", ""), 1200))
            wikipedia_sections = result.get("wikipedia_sections", {})
            if isinstance(wikipedia_sections, dict):
                web_evidence.extend(
                    f"{section}: {_clip(content, 700)}"
                    for section, content in wikipedia_sections.items()
                    if isinstance(content, str)
                )
        sections.append("WEB EVIDENCE:\n" + "\n".join(web_evidence))
    tools = state.get("tool_results", {})
    if isinstance(tools, dict) and tools:
        sections.append(f"TOOL RESULTS:\n{json.dumps(_tool_metadata(tools), ensure_ascii=True)}")
    return _clip("\n\n".join(sections), settings.max_context_chars)


def _fallback_narration(question: str, state: AgentState) -> str:
    context = _narration_context(state)
    return f"Evidence gathered for '{question}':\n{context}" if context else f"No reliable movie evidence was found for: {question}"


def narration_node(state: AgentState) -> dict[str, Any]:
    """Keep technical details out of the final narrator's prompt except as evidence."""
    question = " ".join(str(state.get("question", "")).split())
    metadata = _copy_metadata(state)
    if metadata.get("scope") == "out_of_scope":
        metadata.update(
            {
                "route": "narration",
                "llm_used": False,
                "narration_mode": "capabilities",
            }
        )
        return {
            "final_response": _CAPABILITIES_RESPONSE,
            "route": "narration",
            "metadata": metadata,
        }
    context = _narration_context(state)
    started_at = time.perf_counter()
    usage_by_generation = _token_usage_by_generation(state.get("token_usage"))
    response = _post_local_llm(
        [
            {"role": "system", "content": "You are HorRAGor, a concise gothic film narrator. Use only supplied evidence. Never invent facts. Return the final answer only."},
            {"role": "user", "content": f"USER QUESTION:\n{question}\n\nEVIDENCE:\n{context}"},
        ],
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
        observation_name="generate-narration",
        usage_callback=_capture_token_usage(usage_by_generation, "generate-narration"),
    )
    route = str(state.get("route", "")) or ("scraper" if state.get("scraper_results") else "narration")
    metadata.update(
        {
            "route": route,
            "llm_used": bool(response),
            "llm_model": settings.llm_model,
            "llm_latency_ms": round((time.perf_counter() - started_at) * 1000, 1) if settings.llm_base_url else None,
            "narration_mode": "local_llm" if response else "fallback",
        }
    )
    token_usage = _token_usage_summary(usage_by_generation)
    return {
        "final_response": response or _fallback_narration(question, state),
        "route": route,
        "token_usage": token_usage or {},
        "metadata": metadata,
    }