"""Shared generation LLM helpers (OpenAI or Gemini).

Embeddings are handled separately via ``app.indexing.embeddings``.
Generation degrades to ``None`` when neither API key is configured —
callers must fall back to template / rule-based answers.
"""

from __future__ import annotations

from typing import Literal

from app.core.config import Settings
from app.observability import get_logger

_logger = get_logger(__name__)

ProviderName = Literal["openai", "google"]


def generation_available(settings: Settings) -> bool:
    """True when a generation API key is present and not in test mode."""
    if settings.app_env == "test":
        return False
    return bool(
        (settings.openai_api_key or "").strip()
        or (settings.google_api_key or "").strip()
    )


def resolve_generation_provider(
    settings: Settings,
) -> tuple[ProviderName, str] | None:
    """Pick provider + model for primary generation (summary / copilot).

    Preference: OpenAI when ``openai_api_key`` is set, else Gemini when
    ``google_api_key`` is set. Returns ``None`` if neither key is present.
    """
    if (settings.openai_api_key or "").strip():
        model = (settings.llm_primary_model or "gpt-4o-mini").strip()
        if model.startswith("gemini"):
            model = "gpt-4o-mini"
        return "openai", model
    if (settings.google_api_key or "").strip():
        model = (settings.llm_primary_model or "").strip()
        if not model or model.startswith("gpt"):
            router = (settings.llm_router_model or "").strip()
            model = (
                router
                if router.startswith("gemini")
                else "gemini-2.0-flash"
            )
        return "google", model
    return None


def resolve_router_provider(
    settings: Settings,
) -> tuple[ProviderName, str] | None:
    """Pick provider + model for fast intent classification."""
    if (settings.openai_api_key or "").strip():
        model = (settings.llm_router_model or "").strip()
        if not model or model.startswith("gemini"):
            model = "gpt-4o-mini"
        return "openai", model
    if (settings.google_api_key or "").strip():
        model = (settings.llm_router_model or "gemini-2.0-flash").strip()
        if model.startswith("gpt"):
            model = "gemini-2.0-flash"
        return "google", model
    return None


def chat_complete(
    settings: Settings,
    *,
    prompt: str,
    role: Literal["primary", "router"] = "primary",
    temperature: float = 0.2,
    max_tokens: int = 800,
    json_mode: bool = False,
) -> str | None:
    """Run a single-turn chat completion. Returns ``None`` on any failure."""
    resolved = (
        resolve_generation_provider(settings)
        if role == "primary"
        else resolve_router_provider(settings)
    )
    if resolved is None:
        return None
    provider, model = resolved
    try:
        if provider == "openai":
            return _openai_complete(
                settings,
                model=model,
                prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
            )
        return _gemini_complete(
            settings,
            model=model,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            "llm_chat_complete_failed",
            extra={"provider": provider, "model": model, "error": str(exc)},
        )
        return None


def _openai_complete(
    settings: Settings,
    *,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> str | None:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key.strip())
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip() or None


def _gemini_complete(
    settings: Settings,
    *,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
) -> str | None:
    import google.generativeai as genai

    genai.configure(api_key=settings.google_api_key.strip())
    gm = genai.GenerativeModel(model)
    resp = gm.generate_content(
        prompt,
        generation_config={
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        },
    )
    text = (getattr(resp, "text", None) or "").strip()
    return text or None
