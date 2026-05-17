"""Typed application settings loaded from .env and process environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

from dotenv import dotenv_values

LLMProvider = Literal["anthropic", "openai", "gemini"]
WebSearchProvider = Literal["tavily", "serper", "duckduckgo"]

_DEFAULT_LLM_BY_PROVIDER: Final[dict[LLMProvider, str]] = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
}
_VALID_LOG_LEVELS: Final[set[str]] = {
    "CRITICAL",
    "ERROR",
    "WARNING",
    "INFO",
    "DEBUG",
}


class SettingsError(ValueError):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    llm_provider: LLMProvider
    llm_model: str
    web_search_provider: WebSearchProvider
    log_level: str
    cache_dir: Path
    cache_ttl_seconds: int
    per_source_timeout_seconds: float
    max_sources_per_query: int
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    google_api_key: str | None = None
    llm_api_key: str | None = None
    tavily_api_key: str | None = None
    serper_api_key: str | None = None

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> Settings:
        env_path = Path(env_file) if env_file is not None else Path(".env")
        file_values = dotenv_values(env_path)
        merged = _merge_env(file_values)

        llm_provider = _parse_choice(
            merged,
            "LLM_PROVIDER",
            ("anthropic", "openai", "gemini"),
            default="anthropic",
        )
        llm_model = _get_str(
            merged,
            "LLM_MODEL",
            default=_DEFAULT_LLM_BY_PROVIDER[llm_provider],
        )
        web_provider = _parse_choice(
            merged,
            "WEB_SEARCH_PROVIDER",
            ("tavily", "serper", "duckduckgo"),
            default="tavily",
        )
        log_level = _get_str(merged, "LOG_LEVEL", default="INFO").upper()
        if log_level not in _VALID_LOG_LEVELS:
            raise SettingsError(
                f"LOG_LEVEL must be one of {sorted(_VALID_LOG_LEVELS)}, got {log_level!r}."
            )

        cache_dir = Path(_get_str(merged, "CACHE_DIR", default="./.cache")).expanduser()
        cache_ttl = _get_int(merged, "CACHE_TTL_SECONDS", default=86_400, minimum=1)
        per_source_timeout = _get_float(
            merged,
            "PER_SOURCE_TIMEOUT_SECONDS",
            default=10.0,
            minimum=0.1,
        )
        max_sources = _get_int(merged, "MAX_SOURCES_PER_QUERY", default=3, minimum=1)

        settings = cls(
            llm_provider=llm_provider,
            llm_model=llm_model,
            web_search_provider=web_provider,
            log_level=log_level,
            cache_dir=cache_dir,
            cache_ttl_seconds=cache_ttl,
            per_source_timeout_seconds=per_source_timeout,
            max_sources_per_query=max_sources,
            anthropic_api_key=_get_optional(merged, "ANTHROPIC_API_KEY"),
            openai_api_key=_get_optional(merged, "OPENAI_API_KEY"),
            google_api_key=_get_optional(merged, "GOOGLE_API_KEY"),
            llm_api_key=_get_optional(merged, "LLM_API_KEY"),
            tavily_api_key=_get_optional(merged, "TAVILY_API_KEY"),
            serper_api_key=_get_optional(merged, "SERPER_API_KEY"),
        )
        settings._validate_provider_keys()
        return settings

    def _validate_provider_keys(self) -> None:
        if self.llm_provider == "anthropic" and not (
            self.anthropic_api_key or self.llm_api_key
        ):
            raise SettingsError(
                "LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY (or LLM_API_KEY)."
            )
        if self.llm_provider == "openai" and not (self.openai_api_key or self.llm_api_key):
            raise SettingsError(
                "LLM_PROVIDER=openai requires OPENAI_API_KEY (or LLM_API_KEY)."
            )
        if self.llm_provider == "gemini" and not (self.google_api_key or self.llm_api_key):
            raise SettingsError(
                "LLM_PROVIDER=gemini requires GOOGLE_API_KEY (or LLM_API_KEY)."
            )

        if self.web_search_provider == "tavily" and not self.tavily_api_key:
            raise SettingsError("WEB_SEARCH_PROVIDER=tavily requires TAVILY_API_KEY.")
        if self.web_search_provider == "serper" and not self.serper_api_key:
            raise SettingsError("WEB_SEARCH_PROVIDER=serper requires SERPER_API_KEY.")

    def as_env(self) -> dict[str, str]:
        env = {
            "LLM_PROVIDER": self.llm_provider,
            "LLM_MODEL": self.llm_model,
            "WEB_SEARCH_PROVIDER": self.web_search_provider,
            "LOG_LEVEL": self.log_level,
            "CACHE_DIR": str(self.cache_dir),
            "CACHE_TTL_SECONDS": str(self.cache_ttl_seconds),
            "PER_SOURCE_TIMEOUT_SECONDS": str(self.per_source_timeout_seconds),
            "MAX_SOURCES_PER_QUERY": str(self.max_sources_per_query),
        }
        optional_values = {
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "OPENAI_API_KEY": self.openai_api_key,
            "GOOGLE_API_KEY": self.google_api_key,
            "LLM_API_KEY": self.llm_api_key,
            "TAVILY_API_KEY": self.tavily_api_key,
            "SERPER_API_KEY": self.serper_api_key,
        }
        for key, value in optional_values.items():
            if value:
                env[key] = value
        return env


def _merge_env(file_values: dict[str, str | None]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for key, value in file_values.items():
        if value is not None:
            merged[key] = value
    for key, value in os.environ.items():
        merged[key] = value
    return merged


def _get_optional(values: dict[str, str], key: str) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    clean = value.strip()
    return clean or None


def _get_str(values: dict[str, str], key: str, *, default: str | None = None) -> str:
    value = _get_optional(values, key)
    if value is None:
        if default is None:
            raise SettingsError(f"Missing required setting: {key}.")
        return default
    return value


def _get_int(
    values: dict[str, str],
    key: str,
    *,
    default: int,
    minimum: int,
) -> int:
    raw = _get_str(values, key, default=str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError(f"{key} must be an integer, got {raw!r}.") from exc
    if value < minimum:
        raise SettingsError(f"{key} must be >= {minimum}, got {value}.")
    return value


def _get_float(
    values: dict[str, str],
    key: str,
    *,
    default: float,
    minimum: float,
) -> float:
    raw = _get_str(values, key, default=str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise SettingsError(f"{key} must be a number, got {raw!r}.") from exc
    if value < minimum:
        raise SettingsError(f"{key} must be >= {minimum}, got {value}.")
    return value


def _parse_choice(
    values: dict[str, str],
    key: str,
    allowed: tuple[str, ...],
    *,
    default: str,
) -> str:
    value = _get_str(values, key, default=default).strip().lower()
    if value not in allowed:
        raise SettingsError(f"{key} must be one of {allowed}, got {value!r}.")
    return value


@lru_cache(maxsize=1)
def get_settings(env_file: str | Path | None = None) -> Settings:
    return Settings.from_env(env_file=env_file)


def configure_environment(settings: Settings | None = None) -> Settings:
    loaded = settings or get_settings()
    for key, value in loaded.as_env().items():
        os.environ[key] = value
    return loaded
