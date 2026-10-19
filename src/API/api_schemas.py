from typing import Any, Literal

from pydantic import BaseModel, Field


class ConversationMessage(BaseModel):
    """A bounded prior turn used for deterministic reference resolution."""

    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class LoginRequest(BaseModel):
    """Credentials for the single deployment-managed HorRAGor account."""

    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=8, max_length=1024)


class RefreshTokenRequest(BaseModel):
    """A refresh token to rotate or revoke."""

    refresh_token: str = Field(..., min_length=32, max_length=4096)


class TokenResponse(BaseModel):
    """Short-lived access token and one-time refresh token."""

    access_token: str
    refresh_token: str
    access_expires_in: int = Field(gt=0)
    refresh_expires_in: int = Field(gt=0)
    token_type: str = "bearer"


class ChatRequest(BaseModel):
    """Structure de la requête entrante."""
    question: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Question posée au HorRAGor BOT",
    )
    session_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Identifiant stable de la conversation pour le suivi Langfuse",
    )
    history: list[ConversationMessage] = Field(
        default_factory=list,
        max_length=20,
        description="Tours précédents de la conversation, sans logique métier côté UI",
    )

class JudgeVerdict(BaseModel):
    """Structure du verdict du nœud d'évaluation (Juge)."""
    is_valid: bool = Field(..., description="Indique si la réponse de l'agent est validée par le juge")
    score: int = Field(..., ge=0, le=10, description="Note de pertinence attribuée par le juge de 0 à 10")
    justification: str = Field(..., description="Explication du verdict par le juge")


class TokenUsage(BaseModel):
    """Token counts returned by one local model generation."""

    input: int = Field(0, ge=0, description="Input tokens")
    output: int = Field(0, ge=0, description="Output tokens")
    total: int = Field(0, ge=0, description="Total tokens")


class TokenUsageSummary(TokenUsage):
    """Aggregated token counts for all model generations in one chat turn."""

    by_generation: dict[str, TokenUsage] = Field(
        default_factory=dict,
        description="Token counts grouped by generation name",
    )


class ChatResponse(BaseModel):
    """Structure de la réponse sortante renvoyée au Front-End."""
    response: str = Field(..., description="Réponse finale générée et validée")
    verdict: JudgeVerdict = Field(..., description="Détails du verdict du Juge")
    token_usage: TokenUsageSummary | None = Field(
        default=None,
        description="Token counts for local model generations in this response",
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Données optionnelles de tracking/debug"
    )


class MovieHit(BaseModel):
    """A movie row and its cosine similarity score."""

    score: float = Field(..., description="Cosine similarity returned by FAISS")
    movie: dict[str, str] = Field(..., description="Original cleaned CSV row")


class MovieSearchResponse(BaseModel):
    """Response returned by the direct FAISS search endpoint."""

    query: str
    results: list[MovieHit]
    index_size: int