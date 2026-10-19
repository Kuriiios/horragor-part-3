"""FastAPI dependencies for optional local and mandatory production auth."""

from __future__ import annotations

from typing import Annotated

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import settings
from .tokens import AuthConfigurationError, InvalidTokenError, get_token_service

bearer_scheme = HTTPBearer(auto_error=False)


def require_authenticated_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ] = None,
) -> str:
    """Return the token subject, or an anonymous local-development identity."""
    if not settings.auth_enabled:
        return "anonymous"
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return get_token_service().verify_access_token(credentials.credentials)
    except (AuthConfigurationError, InvalidTokenError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The access token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc