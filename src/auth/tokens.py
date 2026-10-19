"""Signed access tokens and persisted one-time refresh-token rotation."""

from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ..config import Settings, settings

logger = logging.getLogger(__name__)


class AuthConfigurationError(RuntimeError):
    """Raised when authentication is enabled without required secrets."""


class AuthenticationError(ValueError):
    """Raised when supplied account credentials are invalid."""


class InvalidTokenError(ValueError):
    """Raised for invalid, expired, revoked, or replayed tokens."""


@dataclass(frozen=True)
class TokenPair:
    """Bearer access token and its rotating refresh token."""

    access_token: str
    refresh_token: str
    access_expires_in: int
    refresh_expires_in: int
    token_type: str = "bearer"


class RefreshTokenStore:
    """SQLite-backed hashed token store supporting atomic one-time consumption."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._lock = RLock()

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                token_hash TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                consumed_at INTEGER
            )
            """
        )
        return connection

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def store(self, token: str, subject: str, expires_at: datetime) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO refresh_tokens(token_hash, subject, expires_at) VALUES (?, ?, ?)",
                (self._hash(token), subject, int(expires_at.timestamp())),
            )
            connection.execute(
                "DELETE FROM refresh_tokens WHERE expires_at < ?",
                (int(datetime.now(UTC).timestamp()),),
            )

    def consume(self, token: str, subject: str) -> bool:
        now = int(datetime.now(UTC).timestamp())
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE refresh_tokens
                SET consumed_at = ?
                WHERE token_hash = ?
                  AND subject = ?
                  AND consumed_at IS NULL
                  AND expires_at >= ?
                """,
                (now, self._hash(token), subject, now),
            )
            return cursor.rowcount == 1

    def revoke(self, token: str) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE refresh_tokens SET consumed_at = ? WHERE token_hash = ?",
                (int(datetime.now(UTC).timestamp()), self._hash(token)),
            )


class TokenService:
    """Authenticate the configured account and manage a rotating JWT token pair."""

    _algorithm = "HS256"

    def __init__(
        self,
        configuration: Settings = settings,
        *,
        refresh_store: RefreshTokenStore | None = None,
    ) -> None:
        self.configuration = configuration
        self._password_hasher = PasswordHasher()
        self._refresh_store = refresh_store or RefreshTokenStore(
            configuration.refresh_token_db_path
        )

    def validate_configuration(self) -> None:
        missing = []
        if not self.configuration.jwt_secret or len(self.configuration.jwt_secret) < 32:
            missing.append("HORRAGOR_JWT_SECRET")
        if not self.configuration.auth_password_hash:
            missing.append("HORRAGOR_AUTH_PASSWORD_HASH")
        if not self.configuration.auth_username:
            missing.append("HORRAGOR_AUTH_USERNAME")
        if self.configuration.auth_password_hash:
            try:
                self._password_hasher.check_needs_rehash(
                    self.configuration.auth_password_hash
                )
            except InvalidHashError:
                missing.append("valid HORRAGOR_AUTH_PASSWORD_HASH")
        if missing:
            raise AuthConfigurationError(
                "Authentication is enabled but required settings are missing: "
                + ", ".join(missing)
            )

    def authenticate(self, username: str, password: str) -> str:
        self.validate_configuration()
        configured_hash = self.configuration.auth_password_hash or ""
        username_matches = secrets.compare_digest(
            username,
            self.configuration.auth_username,
        )
        password_matches: bool
        try:
            password_matches = self._password_hasher.verify(configured_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            password_matches = False
        if not username_matches or not password_matches:
            raise AuthenticationError("Invalid username or password")
        return self.configuration.auth_username

    def _encode(self, subject: str, token_type: str, expires_at: datetime) -> str:
        now = datetime.now(UTC)
        secret = self.configuration.jwt_secret
        if not secret:
            raise AuthConfigurationError("HORRAGOR_JWT_SECRET is required")
        claims: dict[str, Any] = {
            "sub": subject,
            "type": token_type,
            "jti": uuid4().hex,
            "iat": now,
            "nbf": now,
            "exp": expires_at,
            "iss": self.configuration.jwt_issuer,
            "aud": self.configuration.jwt_audience,
        }
        return jwt.encode(claims, secret, algorithm=self._algorithm)

    def _decode(self, token: str, expected_type: str) -> dict[str, Any]:
        secret = self.configuration.jwt_secret
        if not secret:
            raise AuthConfigurationError("HORRAGOR_JWT_SECRET is required")
        try:
            claims = jwt.decode(
                token,
                secret,
                algorithms=[self._algorithm],
                audience=self.configuration.jwt_audience,
                issuer=self.configuration.jwt_issuer,
                options={"require": ["sub", "type", "jti", "iat", "nbf", "exp"]},
            )
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("Token is invalid or expired") from exc
        if claims.get("type") != expected_type or not isinstance(claims.get("sub"), str):
            raise InvalidTokenError(f"Expected a {expected_type} token")
        return claims

    def issue_pair(self, subject: str) -> TokenPair:
        self.validate_configuration()
        now = datetime.now(UTC)
        access_delta = timedelta(minutes=self.configuration.jwt_access_minutes)
        refresh_delta = timedelta(days=self.configuration.jwt_refresh_days)
        access_token = self._encode(subject, "access", now + access_delta)
        refresh_expiry = now + refresh_delta
        refresh_token = self._encode(subject, "refresh", refresh_expiry)
        self._refresh_store.store(refresh_token, subject, refresh_expiry)
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_in=int(access_delta.total_seconds()),
            refresh_expires_in=int(refresh_delta.total_seconds()),
        )

    def verify_access_token(self, token: str) -> str:
        return str(self._decode(token, "access")["sub"])

    def rotate_refresh_token(self, token: str) -> TokenPair:
        claims = self._decode(token, "refresh")
        subject = str(claims["sub"])
        if not self._refresh_store.consume(token, subject):
            logger.warning("Rejected refresh-token replay or expired token for %s", subject)
            raise InvalidTokenError("Refresh token is revoked, expired, or already used")
        logger.info("Rotated refresh token for %s", subject)
        return self.issue_pair(subject)

    def revoke_refresh_token(self, token: str) -> None:
        subject = str(self._decode(token, "refresh")["sub"])
        self._refresh_store.revoke(token)
        logger.info("Revoked refresh token for %s", subject)


_token_service: TokenService | None = None
_token_service_lock = RLock()


def get_token_service() -> TokenService:
    """Return the process-wide token service."""
    global _token_service
    with _token_service_lock:
        if _token_service is None:
            _token_service = TokenService()
        return _token_service