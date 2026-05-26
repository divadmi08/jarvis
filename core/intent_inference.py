from __future__ import annotations

from dataclasses import dataclass

from core.pattern_types import IntentPrediction, TemporalContext


@dataclass(frozen=True)
class IntentRule:
    name: str
    intent: str
    apps_any: frozenset[str]
    apps_all: frozenset[str]
    base_confidence: float

    def score(self, apps: set[str]) -> float:
        if self.apps_all and not self.apps_all.issubset(apps):
            return 0.0
        overlap = len(apps & self.apps_any) if self.apps_any else 0
        denominator = max(len(self.apps_any), 1)
        return self.base_confidence + (0.2 * overlap / denominator)


class IntentInferenceEngine:
    def __init__(self, rules: list[IntentRule] | None = None):
        self.rules = rules or self.default_rules()

    @staticmethod
    def default_rules() -> list[IntentRule]:
        return [
            IntentRule("admin-triad", "admin_work", frozenset({"slack", "gmail", "calendar", "outlook"}), frozenset({"slack"}), 0.58),
            IntentRule("backend-stack", "backend_development", frozenset({"vscode", "terminal", "docker", "postman"}), frozenset({"terminal"}), 0.62),
            IntentRule("research-stack", "research", frozenset({"chrome", "chatgpt", "docs", "notion", "obsidian"}), frozenset({"chrome"}), 0.56),
            IntentRule("design-stack", "design", frozenset({"figma", "slack", "chrome", "photoshop"}), frozenset({"figma"}), 0.6),
            IntentRule("communication-stack", "communication", frozenset({"slack", "discord", "teams", "telegram"}), frozenset(), 0.45),
        ]

    def infer(self, apps: list[str] | tuple[str, ...], context: TemporalContext | None = None) -> IntentPrediction | None:
        app_set = set(apps)
        best_rule: IntentRule | None = None
        best_score = 0.0

        for rule in self.rules:
            score = rule.score(app_set)
            if context and context.weekday and context.workday_probability > 0.7:
                score += 0.05
            if context and context.period in {"morning", "early_morning", "afternoon"}:
                score += 0.03
            if score > best_score:
                best_score = score
                best_rule = rule

        if best_rule is None or best_score < 0.5:
            return None

        confidence = min(best_score, 0.95)
        return IntentPrediction(
            intent=best_rule.intent,
            confidence=confidence,
            context=context.as_metadata() if context else {},
            matched_rules=(best_rule.name,),
        )
