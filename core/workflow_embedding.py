from __future__ import annotations

from math import sqrt


def build_workflow_embedding(app_weights: dict[str, float]) -> dict[str, float]:
    norm = sqrt(sum(weight * weight for weight in app_weights.values())) or 1.0
    return {app: round(weight / norm, 6) for app, weight in app_weights.items()}
