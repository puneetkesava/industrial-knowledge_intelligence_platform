"""Embedding provider abstraction (Milestone 2.4).

Default production path: local FastEmbed (BGE ONNX) — no API key required.
OpenAI remains an optional fallback when ``embedding_provider=openai``.
Tests (``app_env=test``) always resolve to ``HashEmbeddingProvider``.
"""

from __future__ import annotations

from typing import Any, ClassVar, Protocol

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, ErrorCode
from app.observability import get_logger

_logger = get_logger(__name__)


class EmbeddingProvider(Protocol):
    model_name: str
    model_version: str
    dimensions: int
    provider: str

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedProvider:
    """Local ONNX embeddings via Qdrant's fastembed — no API key, CPU-friendly."""

    provider = "fastembed"
    _model_cache: ClassVar[dict[str, Any]] = {}

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        model_name: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self.model_name = model_name or self._settings.embedding_model
        self.dimensions = int(self._settings.embedding_dimensions)
        self.model_version = f"{self.provider}:{self.model_name}"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        # fastembed yields numpy arrays (or lists); normalize to list[float]
        vectors = [list(map(float, vec)) for vec in model.embed(texts)]
        _logger.info(
            "fastembed embeddings created",
            extra={"count": len(texts), "model": self.model_name},
        )
        return vectors

    def _get_model(self) -> Any:
        cached = FastEmbedProvider._model_cache.get(self.model_name)
        if cached is not None:
            return cached
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover
            raise AppError(
                "fastembed package is not installed — "
                "pip install 'fastembed>=0.4.0'",
                error_code=ErrorCode.SERVICE_UNAVAILABLE,
                status_code=503,
            ) from exc
        try:
            model = TextEmbedding(model_name=self.model_name)
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                f"Failed to load FastEmbed model '{self.model_name}': {exc}",
                error_code=ErrorCode.SERVICE_UNAVAILABLE,
                status_code=503,
            ) from exc
        FastEmbedProvider._model_cache[self.model_name] = model
        _logger.info(
            "fastembed model loaded",
            extra={"model": self.model_name, "dimensions": self.dimensions},
        )
        return model


class OpenAIEmbeddingProvider:
    """Optional cloud embedding provider — text-embedding-3-small (1536-d)."""

    provider = "openai"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        model_name: str | None = None,
        client: object | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self.model_name = model_name or self._settings.embedding_model
        self.dimensions = int(self._settings.embedding_dimensions)
        self.model_version = f"{self.provider}:{self.model_name}"
        self._client = client

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        client = self._get_client()
        vectors: list[list[float]] = []
        batch_size = 64
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            response = client.embeddings.create(
                model=self.model_name,
                input=batch,
            )
            ordered = sorted(response.data, key=lambda d: d.index)
            vectors.extend([list(item.embedding) for item in ordered])
        _logger.info(
            "openai embeddings created",
            extra={"count": len(texts), "model": self.model_name},
        )
        return vectors

    def _get_client(self):
        if self._client is not None:
            return self._client
        api_key = (self._settings.openai_api_key or "").strip()
        if not api_key:
            raise AppError(
                "OPENAI_API_KEY is not configured",
                error_code=ErrorCode.SERVICE_UNAVAILABLE,
                status_code=503,
            )
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise AppError(
                "openai package is not installed",
                error_code=ErrorCode.SERVICE_UNAVAILABLE,
                status_code=503,
            ) from exc
        self._client = OpenAI(api_key=api_key)
        return self._client


class HashEmbeddingProvider:
    """Deterministic local embedder for unit tests (no API calls)."""

    provider = "hash"
    model_name = "hash-embed-v1"
    model_version = "hash:hash-embed-v1"
    dimensions = 32

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dimensions
            for i, ch in enumerate(text.encode("utf-8")):
                vec[i % self.dimensions] += (ch % 31) / 31.0
            # L2 normalize
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    cfg = settings or get_settings()
    if cfg.app_env == "test":
        return HashEmbeddingProvider()

    provider = (cfg.embedding_provider or "fastembed").strip().lower()
    if provider == "openai":
        return OpenAIEmbeddingProvider(cfg)
    if provider in {"fastembed", "local", "bge"}:
        return FastEmbedProvider(cfg)

    _logger.warning(
        "unknown embedding_provider; defaulting to fastembed",
        extra={"embedding_provider": provider},
    )
    return FastEmbedProvider(cfg)
