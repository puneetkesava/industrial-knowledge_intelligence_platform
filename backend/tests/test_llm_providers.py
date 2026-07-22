"""Tests for shared generation LLM provider resolution."""

from __future__ import annotations

from app.core.config import Settings, clear_settings_cache
from app.core.llm import (
    generation_available,
    resolve_generation_provider,
    resolve_router_provider,
)


def test_generation_unavailable_in_test_env() -> None:
    clear_settings_cache()
    settings = Settings(
        app_env="test",
        openai_api_key="sk-test",
        google_api_key="g-test",
    )
    assert generation_available(settings) is False


def test_prefer_openai_when_both_keys_present() -> None:
    clear_settings_cache()
    settings = Settings(
        app_env="development",
        openai_api_key="sk-test",
        google_api_key="g-test",
        llm_primary_model="gpt-4o",
        llm_router_model="gemini-2.0-flash",
    )
    assert resolve_generation_provider(settings) == ("openai", "gpt-4o")
    assert resolve_router_provider(settings) == ("openai", "gpt-4o-mini")


def test_gemini_when_only_google_key() -> None:
    clear_settings_cache()
    settings = Settings(
        app_env="development",
        openai_api_key="",
        google_api_key="g-test",
        llm_primary_model="gpt-4o",
        llm_router_model="gemini-2.0-flash",
    )
    assert resolve_generation_provider(settings) == ("google", "gemini-2.0-flash")
    assert resolve_router_provider(settings) == ("google", "gemini-2.0-flash")


def test_neither_key_returns_none() -> None:
    clear_settings_cache()
    settings = Settings(
        app_env="development",
        openai_api_key="",
        google_api_key="",
    )
    assert resolve_generation_provider(settings) is None
    assert resolve_router_provider(settings) is None
    assert generation_available(settings) is False
