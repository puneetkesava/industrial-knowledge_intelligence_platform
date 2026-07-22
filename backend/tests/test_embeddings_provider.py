"""Tests for embedding provider selection and local FastEmbed wiring."""

from __future__ import annotations

from app.core.config import Settings, clear_settings_cache
from app.indexing.embeddings import (
    FastEmbedProvider,
    HashEmbeddingProvider,
    OpenAIEmbeddingProvider,
    get_embedding_provider,
)


def test_get_embedding_provider_uses_hash_in_test_env() -> None:
    clear_settings_cache()
    settings = Settings(
        app_env="test",
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
    )
    provider = get_embedding_provider(settings)
    assert isinstance(provider, HashEmbeddingProvider)
    assert provider.dimensions == 32


def test_get_embedding_provider_defaults_to_fastembed() -> None:
    clear_settings_cache()
    settings = Settings(
        app_env="development",
        embedding_provider="fastembed",
        embedding_model="BAAI/bge-base-en-v1.5",
        embedding_dimensions=768,
    )
    provider = get_embedding_provider(settings)
    assert isinstance(provider, FastEmbedProvider)
    assert provider.model_name == "BAAI/bge-base-en-v1.5"
    assert provider.dimensions == 768
    assert provider.provider == "fastembed"


def test_get_embedding_provider_openai_fallback() -> None:
    clear_settings_cache()
    settings = Settings(
        app_env="development",
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        openai_api_key="sk-test",
    )
    provider = get_embedding_provider(settings)
    assert isinstance(provider, OpenAIEmbeddingProvider)
    assert provider.dimensions == 1536


def test_hash_embed_deterministic() -> None:
    provider = HashEmbeddingProvider()
    a = provider.embed_texts(["motor efficiency"])
    b = provider.embed_texts(["motor efficiency"])
    assert a == b
    assert len(a[0]) == 32
