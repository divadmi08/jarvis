from __future__ import annotations

import hashlib
import math
import os
import re
from abc import ABC, abstractmethod
from typing import Any


DEFAULT_GEMINI_EMBEDDING_MODEL = "text-embedding-004"


class EmbeddingClientError(RuntimeError):
    pass


class EmbeddingClientConfigurationError(EmbeddingClientError):
    pass


class EmbeddingClient(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class GeminiEmbeddingClient(EmbeddingClient):
    """Embedding Gemini tramite google-genai o google-generativeai."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_GEMINI_EMBEDDING_MODEL,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise EmbeddingClientConfigurationError("Missing GEMINI_API_KEY environment variable")
        self.model = model
        self._backend = self._load_backend()

    def embed(self, text: str) -> list[float]:
        return self._backend.embed(self.api_key, self.model, text)

    def _load_backend(self) -> "_GeminiEmbeddingBackend":
        try:
            from google import genai  # type: ignore

            return _GoogleGenAIEmbeddingBackend(genai)
        except ImportError:
            pass

        try:
            import google.generativeai as google_generativeai  # type: ignore

            return _GoogleGenerativeAIEmbeddingBackend(google_generativeai)
        except ImportError as exc:
            raise EmbeddingClientConfigurationError(
                "Gemini SDK not installed. Install `google-genai` or `google-generativeai`."
            ) from exc


class LocalEmbeddingClient(EmbeddingClient):
    """Embedding offline stabile basato su hashing, senza dipendenze native."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = max(32, int(dimensions))

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = _tokenize(text)
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


class _GeminiEmbeddingBackend(ABC):
    @abstractmethod
    def embed(self, api_key: str, model: str, text: str) -> list[float]:
        raise NotImplementedError


class _GoogleGenAIEmbeddingBackend(_GeminiEmbeddingBackend):
    def __init__(self, module: Any) -> None:
        self.module = module

    def embed(self, api_key: str, model: str, text: str) -> list[float]:
        client = self.module.Client(api_key=api_key)
        response = client.models.embed_content(model=model, contents=text)
        embeddings = getattr(response, "embeddings", None)
        if embeddings:
            values = getattr(embeddings[0], "values", None)
            if values is not None:
                return [float(value) for value in values]
        raise EmbeddingClientError(f"Empty embedding response from Gemini model {model}")


class _GoogleGenerativeAIEmbeddingBackend(_GeminiEmbeddingBackend):
    def __init__(self, module: Any) -> None:
        self.module = module

    def embed(self, api_key: str, model: str, text: str) -> list[float]:
        self.module.configure(api_key=api_key)
        response = self.module.embed_content(model=f"models/{model}", content=text)
        values = response.get("embedding") if isinstance(response, dict) else None
        if values is None:
            raise EmbeddingClientError(f"Empty embedding response from Gemini model {model}")
        return [float(value) for value in values]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_./+-]+", text.lower())
