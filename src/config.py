"""Environment-driven settings for the HorRAGor agent graph."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)


def _secret_setting(name: str) -> str | None:
	value = os.getenv(name, "").strip()
	if value:
		return value
	secret_file = os.getenv(f"{name}_FILE", "").strip()
	if not secret_file:
		return None
	try:
		return Path(secret_file).read_text(encoding="utf-8").strip() or None
	except OSError as exc:
		logger.warning("Unable to read secret file for %s: %s", name, exc)
		return None


def _bool_setting(name: str, default: bool = False) -> bool:
	raw_value = os.getenv(name)
	if raw_value is None:
		return default
	normalized = raw_value.strip().casefold()
	if normalized in {"1", "true", "yes", "on"}:
		return True
	if normalized in {"0", "false", "no", "off"}:
		return False
	logger.warning("Ignoring invalid boolean setting %s=%r", name, raw_value)
	return default


def _int_setting(name: str, default: int, minimum: int, maximum: int) -> int:
	raw_value = os.getenv(name, str(default))
	try:
		value = int(raw_value)
	except ValueError:
		logger.warning("Ignoring invalid integer setting %s=%r", name, raw_value)
		return default
	bounded = max(minimum, min(maximum, value))
	if bounded != value:
		logger.warning("Clamped %s from %s to %s", name, value, bounded)
	return bounded


def _float_setting(name: str, default: float, minimum: float, maximum: float) -> float:
	raw_value = os.getenv(name, str(default))
	try:
		value = float(raw_value)
	except ValueError:
		logger.warning("Ignoring invalid numeric setting %s=%r", name, raw_value)
		return default
	bounded = max(minimum, min(maximum, value))
	if bounded != value:
		logger.warning("Clamped %s from %s to %s", name, value, bounded)
	return bounded


@dataclass(frozen=True)
class Settings:
	"""Runtime settings shared by graph nodes and the conditional router."""

	rag_limit: int
	local_score_threshold: float
	scraper_limit: int
	scraper_timeout_seconds: float
	max_context_chars: int
	llm_base_url: str | None
	llm_model: str
	llm_model_path: str
	llm_device: str
	llm_api_key: str
	llm_timeout_seconds: float
	llm_max_tokens: int
	llm_temperature: float
	wikipedia_api_url: str
	data_api_url: str | None
	data_api_key: str | None
	data_api_timeout_seconds: float
	environment: str
	allowed_origins: tuple[str, ...]
	auth_enabled: bool
	auth_username: str
	auth_password_hash: str | None
	jwt_secret: str | None
	jwt_issuer: str
	jwt_audience: str
	jwt_access_minutes: int
	jwt_refresh_days: int
	refresh_token_db_path: Path
	max_request_body_bytes: int

	@classmethod
	def from_environment(cls) -> Settings:
		base_url = os.getenv(
			"HORRAGOR_LLM_BASE_URL",
			"http://127.0.0.1:8001/v1",
		).strip() or None
		if os.getenv("HORRAGOR_DISABLE_LLM", "").casefold() in {"1", "true", "yes"}:
			base_url = None
		data_api_url = os.getenv("HORRAGOR_DATA_API_URL", "").strip() or None
		data_api_key = _secret_setting("HORRAGOR_DATA_API_KEY")
		environment = os.getenv("HORRAGOR_ENVIRONMENT", "development").strip().casefold()
		allowed_origins = tuple(
			origin.strip()
			for origin in os.getenv(
				"HORRAGOR_ALLOWED_ORIGINS",
				"http://localhost:8501,http://127.0.0.1:8501",
			).split(",")
			if origin.strip()
		)
		return cls(
			rag_limit=_int_setting("HORRAGOR_RAG_LIMIT", 5, 1, 20),
			local_score_threshold=_float_setting(
				"HORRAGOR_LOCAL_SCORE_THRESHOLD", 0.65, 0.0, 1.0
			),
			scraper_limit=_int_setting("HORRAGOR_SCRAPER_LIMIT", 3, 1, 5),
			scraper_timeout_seconds=_float_setting(
				"HORRAGOR_SCRAPER_TIMEOUT_SECONDS", 6.0, 1.0, 20.0
			),
			max_context_chars=_int_setting(
				"HORRAGOR_MAX_CONTEXT_CHARS", 6000, 1000, 20000
			),
			llm_base_url=base_url,
			llm_model=os.getenv("HORRAGOR_LLM_MODEL", "qwen3-8b-npu"),
			llm_model_path=os.getenv(
				"HORRAGOR_LLM_MODEL_PATH",
				str(PROJECT_ROOT / "models" / "Qwen3-8B-int4-cw-ov"),
			),
			llm_device=os.getenv("HORRAGOR_LLM_DEVICE", "AUTO"),
			llm_api_key=os.getenv("HORRAGOR_LLM_API_KEY", "not-needed"),
			llm_timeout_seconds=_float_setting(
				"HORRAGOR_LLM_TIMEOUT_SECONDS", 120.0, 1.0, 180.0
			),
			llm_max_tokens=_int_setting("HORRAGOR_LLM_MAX_TOKENS", 240, 64, 2000),
			llm_temperature=_float_setting(
				"HORRAGOR_LLM_TEMPERATURE", 0.0, 0.0, 1.0
			),
			wikipedia_api_url=os.getenv(
				"HORRAGOR_WIKIPEDIA_API_URL",
				"https://en.wikipedia.org/w/api.php",
			),
			data_api_url=data_api_url,
			data_api_key=data_api_key,
			data_api_timeout_seconds=_float_setting(
				"HORRAGOR_DATA_API_TIMEOUT_SECONDS", 5.0, 0.5, 30.0
			),
			environment=environment,
			allowed_origins=allowed_origins,
			auth_enabled=_bool_setting(
				"HORRAGOR_AUTH_ENABLED",
				default=environment in {"production", "staging"},
			),
			auth_username=os.getenv("HORRAGOR_AUTH_USERNAME", "horragor").strip(),
			auth_password_hash=_secret_setting("HORRAGOR_AUTH_PASSWORD_HASH"),
			jwt_secret=_secret_setting("HORRAGOR_JWT_SECRET"),
			jwt_issuer=os.getenv("HORRAGOR_JWT_ISSUER", "horragor-api").strip(),
			jwt_audience=os.getenv("HORRAGOR_JWT_AUDIENCE", "horragor-ui").strip(),
			jwt_access_minutes=_int_setting(
				"HORRAGOR_ACCESS_TOKEN_MINUTES", 15, 1, 60
			),
			jwt_refresh_days=_int_setting("HORRAGOR_REFRESH_TOKEN_DAYS", 7, 1, 30),
			refresh_token_db_path=Path(
				os.getenv(
					"HORRAGOR_REFRESH_TOKEN_DB",
					str(PROJECT_ROOT / "data" / "auth" / "refresh_tokens.db"),
				)
			),
			max_request_body_bytes=_int_setting(
				"HORRAGOR_MAX_REQUEST_BODY_BYTES", 131_072, 16_384, 1_048_576
			),
		)


settings = Settings.from_environment()
