"""The five safe, model-visible tools required by HorRAGor Brief 2."""

from __future__ import annotations

import ast
import hashlib
import re
from datetime import date
from typing import Any

from ..data_gateway import get_movie_data_gateway
from .brief2_scraper import scrape_detailed_synopsis

_YEAR_PATTERN = re.compile(r"\b(\d{4})\b")
_OVERVIEW_ELEMENTS = (
    ("family themes", ("family", "families", "mother", "father", "daughter", "son", "child", "children")),
    ("demonic or cursed elements", ("demon", "demonic", "possession", "devil", "curse")),
    ("ghostly or supernatural elements", ("ghost", "haunt", "spirit", "supernatural", "paranormal", "poltergeist")),
    ("a killer or human threat", ("killer", "murder", "slasher", "stalker")),
    ("a monster or creature", ("monster", "creature", "beast", "alien", "vampire", "werewolf", "zombie")),
    ("an isolated or threatening setting", ("house", "home", "cabin", "woods", "forest", "island", "hotel", "hospital", "village")),
    ("a fight for survival", ("survive", "survival", "trapped", "escape", "rescue", "fight", "flee")),
    ("a nightmare-like atmosphere", ("nightmare", "terror", "fear", "dark", "evil")),
)


def _number(value: Any) -> float | None:
    try:
        text = str(value or "").replace(",", "").strip()
        if not text or text.casefold() in {"nan", "none", "null", "na"}:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _people(value: Any, *, role: str | None = None, limit: int = 8) -> list[str]:
    if isinstance(value, list):
        entries = value
    elif isinstance(value, str) and value.strip():
        try:
            entries = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            entries = []
    else:
        entries = []
    if not isinstance(entries, list):
        return []
    return [
        str(entry["name"]).strip()
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("name")
        and (role is None or str(entry.get("job", "")).casefold() == role)
    ][:limit]


def _release_year(value: Any) -> int | None:
    match = _YEAR_PATTERN.search(str(value or ""))
    return int(match.group(1)) if match else None


def _overview_elements(overview: Any) -> list[str]:
    text = " ".join(str(overview or "").casefold().split())
    return [
        label
        for label, keywords in _OVERVIEW_ELEMENTS
        if any(re.search(rf"\b{re.escape(keyword)}\w*\b", text) for keyword in keywords)
    ]


def _join_elements(elements: list[str]) -> str:
    if len(elements) == 1:
        return elements[0]
    if len(elements) == 2:
        return f"{elements[0]} and {elements[1]}"
    return f"{', '.join(elements[:-1])}, and {elements[-1]}"


def _recommendation_reason(reference_overview: Any, candidate_overview: Any, score: float | None) -> str:
    reference_elements = set(_overview_elements(reference_overview))
    candidate_elements = _overview_elements(candidate_overview)
    shared_elements = [element for element in candidate_elements if element in reference_elements][:3]
    if shared_elements:
        return f"because both synopses feature {_join_elements(shared_elements)}"
    if candidate_elements:
        reason = f"because its synopsis features {_join_elements(candidate_elements[:3])}"
    else:
        reason = "because its synopsis is a close thematic match"
    if score is not None:
        reason += f" (similarity score: {score:.2f})"
    return reason


def _recommendation_summary(reference_title: str, recommendations: list[dict[str, Any]]) -> str:
    if not recommendations:
        return f"I could not find a similar horror movie for {reference_title}."
    details = [
        f"{recommendation['title']} {recommendation['reason']}"
        for recommendation in recommendations
        if recommendation.get("title") and recommendation.get("reason")
    ]
    if not details:
        return f"I could not find a similar horror movie for {reference_title}."
    if len(details) == 1:
        recommendations_text = details[0]
    elif len(details) == 2:
        recommendations_text = " and ".join(details)
    else:
        recommendations_text = f"{'; '.join(details[:-1])}; and {details[-1]}"
    return f"Based on the synopsis of {reference_title}, I recommend {recommendations_text}."


def _movie_by_id(movie_id: str | int) -> dict[str, str] | None:
    if isinstance(movie_id, bool) or not str(movie_id).strip():
        return None
    try:
        movie = get_movie_data_gateway().get_by_id(movie_id)
    except (AttributeError, TypeError, ValueError):
        return None
    return dict(movie) if isinstance(movie, dict) else None


def query_movie_metadata(movie_id: str | int) -> dict[str, Any] | None:
    """Return safe structured facts for one movie resolved by the RAG node."""
    movie = _movie_by_id(movie_id)
    if movie is None:
        return None
    rating = _number(movie.get("vote_average"))
    runtime = _number(movie.get("runtime"))
    directors = _people(movie.get("crew"), role="director", limit=3)
    return {
        "movie_id": str(movie.get("id", movie_id)),
        "title": str(movie.get("title", "")),
        "release_date": str(movie.get("release_date", "")),
        "release_year": _release_year(movie.get("release_date")),
        "genres": [genre.strip() for genre in str(movie.get("genre_names", "")).split(",") if genre.strip()],
        "director": directors[0] if directors else None,
        "cast": _people(movie.get("cast")),
        "average_rating": round(rating, 1) if rating is not None else None,
        "runtime_minutes": int(runtime) if runtime is not None else None,
        "overview": str(movie.get("overview", "")),
    }


def find_similar_horror_movies(movie_id: str | int, k: int = 5) -> dict[str, Any] | None:
    """Return up to ``k`` nearest movies by synopsis similarity only."""
    movie = _movie_by_id(movie_id)
    if movie is None:
        return None
    try:
        limit = max(1, min(int(k), 10))
        matches = get_movie_data_gateway().find_similar_by_overview(
            movie_id,
            limit=limit,
        )
    except (AttributeError, TypeError, ValueError):
        return None
    recommendations: list[dict[str, Any]] = []
    for match in matches:
        if not isinstance(match, dict) or not isinstance(match.get("movie"), dict):
            continue
        candidate = match["movie"]
        score = _number(match.get("score"))
        reason = _recommendation_reason(movie.get("overview", ""), candidate.get("overview", ""), score)
        recommendations.append(
            {
                "movie_id": str(candidate.get("id", "")),
                "title": str(candidate.get("title", "")),
                "release_year": _release_year(candidate.get("release_date")),
                "genres": [genre.strip() for genre in str(candidate.get("genre_names", "")).split(",") if genre.strip()],
                "similarity_score": round(score, 4) if score is not None else None,
                "overview": str(candidate.get("overview", "")),
                "reason": reason,
            }
        )
    reference_title = str(movie.get("title", ""))
    return {
        "reference_movie": {"movie_id": str(movie.get("id", movie_id)), "title": reference_title},
        "recommendations": recommendations,
        "summary": _recommendation_summary(reference_title, recommendations),
    }


def calculate_movie_age(release_year: int | str, *, as_of: date | None = None) -> dict[str, int]:
    """Calculate a film's age from its release year and the current year."""
    if isinstance(release_year, bool):
        raise ValueError("release_year must be a four-digit year")
    try:
        year = int(str(release_year).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("release_year must be a four-digit year") from exc
    reference_date = as_of or date.today()
    if year < 1888 or year > reference_date.year:
        raise ValueError(f"release_year must be between 1888 and {reference_date.year}")
    return {"release_year": year, "reference_year": reference_date.year, "age_years": reference_date.year - year}


def horror_survival_simulator(detailed_synopsis: str, skill_level: int = 5) -> dict[str, Any]:
    """Create a deterministic, explicitly fictional survival assessment."""
    synopsis = " ".join(str(detailed_synopsis or "").split())
    if len(synopsis) < 20:
        raise ValueError("detailed_synopsis must contain at least 20 characters")
    try:
        skill = max(0, min(int(skill_level), 10))
    except (TypeError, ValueError) as exc:
        raise ValueError("skill_level must be an integer between 0 and 10") from exc
    text = synopsis.casefold()
    threat_rules = (
        ("Supernatural entity", ("ghost", "haunted", "spirit", "poltergeist"), 16),
        ("Human predator", ("killer", "murder", "stalk", "slasher"), 14),
        ("Undead horde", ("zombie", "undead", "infected"), 18),
        ("Demonic force", ("demon", "possession", "devil", "curse"), 20),
        ("Unknown creature", ("alien", "monster", "creature", "beast"), 15),
    )
    threats = [label for label, keywords, _ in threat_rules if any(keyword in text for keyword in keywords)]
    danger = sum(penalty for _, keywords, penalty in threat_rules if any(keyword in text for keyword in keywords))
    if not threats:
        threats, danger = ["Unclassified threat"], 10
    variation = int(hashlib.blake2b(text.encode("utf-8"), digest_size=2).hexdigest(), 16) % 9 - 4
    probability = max(5, min(95, 72 + skill * 2 - danger + variation))
    threat_level = "EXTREME" if probability < 20 else "HIGH" if probability < 45 else "MODERATE" if probability < 65 else "LOW"
    return {
        "fictional": True,
        "survival_probability": probability,
        "threat_level": threat_level,
        "primary_threats": threats,
        "evidence_excerpt": synopsis[:400],
        "advice": "Leave at the first warning, stay with others, and avoid the source of the threat.",
    }


ALL_TOOLS = [query_movie_metadata, find_similar_horror_movies, scrape_detailed_synopsis, calculate_movie_age, horror_survival_simulator]

MODEL_TOOL_SPECS = [
    {"name": "query_movie_metadata", "description": "Return the director, release year, genres, average rating, cast, runtime, and synopsis for a RAG-resolved movie ID.", "parameters": {"type": "object", "properties": {"movie_id": {"type": "string"}}, "required": ["movie_id"], "additionalProperties": False}},
    {"name": "find_similar_horror_movies", "description": "Recommend up to k horror films whose overviews are nearest to the overview of a RAG-resolved movie ID, with grounded reasons based on shared synopsis elements. Titles are not used for similarity.", "parameters": {"type": "object", "properties": {"movie_id": {"type": "string"}, "k": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["movie_id"], "additionalProperties": False}},
    {"name": "scrape_detailed_synopsis", "description": "Retrieve a detailed Wikipedia synopsis only for a named movie when the user explicitly asks for deep plot or anecdotal detail unavailable locally.", "parameters": {"type": "object", "properties": {"movie_title": {"type": "string"}}, "required": ["movie_title"], "additionalProperties": False}},
    {"name": "calculate_movie_age", "description": "Calculate a movie age from its known four-digit release year.", "parameters": {"type": "object", "properties": {"release_year": {"type": "integer", "minimum": 1888}}, "required": ["release_year"], "additionalProperties": False}},
    {"name": "horror_survival_simulator", "description": "Create a fictional survival assessment using supplied detailed synopsis text.", "parameters": {"type": "object", "properties": {"detailed_synopsis": {"type": "string"}, "skill_level": {"type": "integer", "minimum": 0, "maximum": 10}}, "required": ["detailed_synopsis"], "additionalProperties": False}},
]

MODEL_TOOL_REGISTRY = {tool.__name__: tool for tool in ALL_TOOLS}