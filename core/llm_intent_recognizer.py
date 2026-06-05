from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.ai_client import AIClient
from core.pattern_types import IntentPrediction, TemporalContext


@dataclass(frozen=True)
class LLMIntentResult:
    intent: str
    confidence: float
    reasoning: str


_CONFIDENCE_WORDS: dict[str, float] = {
    "very_high": 0.95,
    "high": 0.85,
    "medium": 0.65,
    "moderate": 0.65,
    "low": 0.35,
    "very_low": 0.15,
}


def _parse_confidence(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _CONFIDENCE_WORDS:
            return _CONFIDENCE_WORDS[text]
        try:
            return float(text)
        except ValueError:
            return 0.0
    return 0.0


class LLMIntentRecognizer:
    def __init__(self, ai_client: AIClient) -> None:
        self.ai_client = ai_client

    def infer(
        self,
        apps: list[str] | tuple[str, ...],
        context: TemporalContext | None = None,
        retrieved_context: str = "",
    ) -> IntentPrediction | None:
        prompt = self._build_prompt(apps, context, retrieved_context)
        payload = json.loads(self.ai_client.generate_json(prompt))
        result = self._parse_result(payload)
        if result.confidence < 0.45:
            return None
        return IntentPrediction(
            intent=result.intent,
            confidence=min(max(result.confidence, 0.0), 1.0),
            context={
                "temporal_context": context.as_metadata() if context else {},
                "reasoning": result.reasoning,
                "source": "llm",
            },
            matched_rules=("llm-intent",),
        )

    def _build_prompt(
        self,
        apps: list[str] | tuple[str, ...],
        context: TemporalContext | None,
        retrieved_context: str,
    ) -> str:
        payload: dict[str, Any] = {
            "apps": list(apps),
            "temporal_context": context.as_metadata() if context else None,
            "retrieved_context": retrieved_context,
        }
        return (
            "Classify the user's PC workflow intent from apps and context.\n"
            "Return JSON only with: intent, confidence, reasoning.\n"
            "Use concise snake_case intent names.\n"
            "confidence must be a numeric value between 0.0 and 1.0, not a word.\n"
            f"Input:\n{json.dumps(payload, ensure_ascii=True, indent=2)}"
        )

    def _parse_result(self, payload: dict[str, Any]) -> LLMIntentResult:
        intent = str(payload.get("intent", "")).strip()
        if not intent:
            raise ValueError("Missing intent")
        confidence = _parse_confidence(payload.get("confidence", 0.0))
        reasoning = str(payload.get("reasoning", "")).strip()
        return LLMIntentResult(intent=intent, confidence=confidence, reasoning=reasoning)
