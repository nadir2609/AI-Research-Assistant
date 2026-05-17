from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.config import Settings, SettingsError, configure_environment


def _write_env(path: Path, content: str) -> None:
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_settings_loads_typed_values_from_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)

    env_file = tmp_path / ".env"
    _write_env(
        env_file,
        """
        LLM_PROVIDER=openai
        OPENAI_API_KEY=file-key
        WEB_SEARCH_PROVIDER=duckduckgo
        LOG_LEVEL=debug
        CACHE_DIR=./tmp-cache
        CACHE_TTL_SECONDS=900
        PER_SOURCE_TIMEOUT_SECONDS=4.5
        MAX_SOURCES_PER_QUERY=7
        """,
    )

    settings = Settings.from_env(env_file)

    assert settings.llm_provider == "openai"
    assert settings.openai_api_key == "file-key"
    assert settings.web_search_provider == "duckduckgo"
    assert settings.log_level == "DEBUG"
    assert settings.cache_dir == Path("./tmp-cache")
    assert settings.cache_ttl_seconds == 900
    assert settings.per_source_timeout_seconds == 4.5
    assert settings.max_sources_per_query == 7


def test_process_environment_overrides_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env_file = tmp_path / ".env"
    _write_env(
        env_file,
        """
        LLM_PROVIDER=openai
        OPENAI_API_KEY=file-key
        WEB_SEARCH_PROVIDER=duckduckgo
        """,
    )
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    settings = Settings.from_env(env_file)
    assert settings.openai_api_key == "env-key"


def test_missing_llm_provider_key_raises(tmp_path: Path):
    env_file = tmp_path / ".env"
    _write_env(
        env_file,
        """
        LLM_PROVIDER=gemini
        WEB_SEARCH_PROVIDER=duckduckgo
        """,
    )

    with pytest.raises(SettingsError, match="GOOGLE_API_KEY"):
        Settings.from_env(env_file)


def test_tavily_requires_api_key(tmp_path: Path):
    env_file = tmp_path / ".env"
    _write_env(
        env_file,
        """
        LLM_PROVIDER=anthropic
        ANTHROPIC_API_KEY=abc
        WEB_SEARCH_PROVIDER=tavily
        """,
    )

    with pytest.raises(SettingsError, match="TAVILY_API_KEY"):
        Settings.from_env(env_file)


def test_configure_environment_exports_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)

    env_file = tmp_path / ".env"
    _write_env(
        env_file,
        """
        LLM_PROVIDER=anthropic
        ANTHROPIC_API_KEY=anthropic-key
        WEB_SEARCH_PROVIDER=duckduckgo
        """,
    )
    settings = Settings.from_env(env_file)

    configure_environment(settings)

    assert os.environ["LLM_PROVIDER"] == "anthropic"
    assert os.environ["WEB_SEARCH_PROVIDER"] == "duckduckgo"
