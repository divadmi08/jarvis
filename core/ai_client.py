from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from typing import Any


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"
FALLBACK_GEMINI_MODEL = "gemini-2.5-flash"

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
FALLBACK_GROQ_MODEL = "llama-3.1-8b-instant"
JARVIS_USER_AGENT = "Jarvis"


class AIClientError(RuntimeError):
    pass


class AIClientConfigurationError(AIClientError):
    pass


class AIClient(ABC):
    @abstractmethod
    def generate_text(self, prompt: str) -> str:
        raise NotImplementedError

    def generate_json(self, prompt: str) -> str:
        return self.generate_text(prompt)


# ── Gemini ────────────────────────────────────────────────────────────────────

class GeminiAIClient(AIClient):
    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_GEMINI_MODEL,
        fallback_model: str = FALLBACK_GEMINI_MODEL,
        timeout_seconds: float = 20.0,
        max_attempts: int = 2,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise AIClientConfigurationError("Missing GEMINI_API_KEY environment variable")
        self.model = model
        self.fallback_model = fallback_model
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, int(max_attempts))
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds))
        self._backend = self._load_backend()

    def generate_text(self, prompt: str) -> str:
        errors: list[str] = []
        for model_name in self._models_to_try():
            for attempt in range(1, self.max_attempts + 1):
                try:
                    return self._backend.generate(
                        api_key=self.api_key,
                        model=model_name,
                        prompt=prompt,
                        timeout_seconds=self.timeout_seconds,
                    )
                except Exception as exc:
                    errors.append(f"{model_name} attempt {attempt}/{self.max_attempts}: {exc}")
                    if attempt < self.max_attempts and self._is_retryable_exception(exc):
                        time.sleep(self.retry_delay_seconds * attempt)
                        continue
                    break
        raise AIClientError("Gemini request failed. " + " | ".join(errors))

    def _models_to_try(self) -> list[str]:
        models = [self.model]
        if self.fallback_model and self.fallback_model != self.model:
            models.append(self.fallback_model)
        return models

    def _load_backend(self) -> "_GeminiBackend":
        try:
            from google import genai  # type: ignore
            return _GoogleGenAIBackend(genai)
        except ImportError:
            pass
        try:
            import google.generativeai as google_generativeai  # type: ignore
            return _GoogleGenerativeAIBackend(google_generativeai)
        except ImportError as exc:
            raise AIClientConfigurationError(
                "Gemini SDK not installed. Install `google-genai` or `google-generativeai`."
            ) from exc

    def _is_retryable_exception(self, exc: Exception) -> bool:
        message = str(exc).lower()
        retry_markers = (
            "timed out", "timeout", "temporarily unavailable",
            "connection reset", "connection aborted", "connection refused",
            "server disconnected", "ssl", "tls",
            "429", "500", "502", "503", "504",
        )
        return any(marker in message for marker in retry_markers)


class _GeminiBackend(ABC):
    @abstractmethod
    def generate(self, api_key: str, model: str, prompt: str, timeout_seconds: float) -> str:
        raise NotImplementedError


class _GoogleGenAIBackend(_GeminiBackend):
    def __init__(self, module: Any) -> None:
        self.module = module

    def generate(self, api_key: str, model: str, prompt: str, timeout_seconds: float) -> str:
        client = self.module.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.1,
                "max_output_tokens": 1200,
                "http_options": {"timeout": self._timeout_millis(timeout_seconds)},
            },
        )
        text = getattr(response, "text", None)
        if not text:
            raise AIClientError(f"Empty response from Gemini model {model}")
        return str(text).strip()

    def _timeout_millis(self, timeout_seconds: float) -> int:
        return max(1, int(timeout_seconds * 1000))


class _GoogleGenerativeAIBackend(_GeminiBackend):
    def __init__(self, module: Any) -> None:
        self.module = module

    def generate(self, api_key: str, model: str, prompt: str, timeout_seconds: float) -> str:
        self.module.configure(api_key=api_key)
        generation_model = self.module.GenerativeModel(model)
        response = generation_model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.1,
                "max_output_tokens": 1200,
                "response_mime_type": "application/json",
            },
            request_options={"timeout": timeout_seconds},
        )
        text = getattr(response, "text", None)
        if not text:
            raise AIClientError(f"Empty response from Gemini model {model}")
        return str(text).strip()


# ── Groq ──────────────────────────────────────────────────────────────────────

class GroqAIClient(AIClient):
    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_GROQ_MODEL,
        fallback_model: str = FALLBACK_GROQ_MODEL,
        timeout_seconds: float = 20.0,
        max_attempts: int = 2,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise AIClientConfigurationError("Missing GROQ_API_KEY environment variable")
        self.model = model
        self.fallback_model = fallback_model
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, int(max_attempts))
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds))

    def generate_text(self, prompt: str) -> str:
        try:
            from groq import Groq  # type: ignore
        except ImportError as exc:
            raise AIClientConfigurationError(
                "Groq SDK not installed. Run: pip install groq"
            ) from exc

        client = Groq(api_key=self.api_key)
        errors: list[str] = []

        for model_name in self._models_to_try():
            for attempt in range(1, self.max_attempts + 1):
                try:
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.1,
                        max_tokens=1200,
                        timeout=self.timeout_seconds,
                    )
                    text = response.choices[0].message.content
                    if not text:
                        raise AIClientError(f"Empty response from Groq model {model_name}")
                    return str(text).strip()
                except Exception as exc:
                    errors.append(f"{model_name} attempt {attempt}/{self.max_attempts}: {exc}")
                    if attempt < self.max_attempts:
                        time.sleep(self.retry_delay_seconds * attempt)
                        continue
                    break

        raise AIClientError("Groq request failed. " + " | ".join(errors))

    def _models_to_try(self) -> list[str]:
        models = [self.model]
        if self.fallback_model and self.fallback_model != self.model:
            models.append(self.fallback_model)
        return models


# ── Factory ───────────────────────────────────────────────────────────────────

def default_model_for_provider(provider: str) -> str:
    if provider == "groq":
        return DEFAULT_GROQ_MODEL
    return DEFAULT_GEMINI_MODEL


def build_ai_client(provider: str | None = None, model: str | None = None) -> AIClient:
    """
    Crea il client AI giusto in base al provider.
    Ordine di priorità se provider non specificato:
      1. GROQ_API_KEY presente → Groq
      2. GEMINI_API_KEY presente → Gemini
      3. Errore
    """
    if provider is None:
        if os.getenv("GEMINI_API_KEY"):
            provider = "gemini"
        elif os.getenv("GROQ_API_KEY"):
            provider = "groq"
        else:
            raise AIClientConfigurationError(
                "Nessuna API key trovata. Imposta GROQ_API_KEY o GEMINI_API_KEY nel file .env"
            )

    if provider == "groq":
        return GroqAIClient(model=model or DEFAULT_GROQ_MODEL)
    elif provider == "gemini":
        return GeminiAIClient(model=model or DEFAULT_GEMINI_MODEL)
    else:
        raise AIClientConfigurationError(f"Provider sconosciuto: '{provider}'. Usa 'groq' o 'gemini'.")