from __future__ import annotations

import json
import os
from typing import Any

from core.ai_client import AIClient
from core.app_registry import find_app, scan_installed_apps
from core.task_state import AgentPlan, AgentStep


ALLOWED_AGENT_ACTIONS = frozenset({
    "open_app",
    "focus_window",
    "wait_for_window",
    "notify_user",
    "sleep",
    "run_command",
})


class PlannerError(ValueError):
    pass


class LLMPlanner:
    def __init__(
        self,
        ai_client: AIClient,
        max_steps: int = 5,
        allowed_actions: frozenset[str] = ALLOWED_AGENT_ACTIONS,
    ) -> None:
        self.ai_client = ai_client
        self.max_steps = max(1, int(max_steps))
        self.allowed_actions = allowed_actions

    def plan(self, goal: str, context: str = "") -> AgentPlan:
        raw = self.ai_client.generate_json(self._build_prompt(goal, context))
        cleaned = self._extract_json(raw)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise PlannerError(
                f"Planner returned invalid JSON: {exc}. Raw output: {raw!r}"
            ) from exc
        return self._parse_plan(goal, payload)

    @staticmethod
    def _extract_json(raw: str) -> str:
        """
        Pulisce l'output del modello prima del parsing JSON.
        Gestisce casi comuni come fence markdown (```json ... ```)
        o testo extra prima/dopo l'oggetto JSON.
        """
        text = raw.strip()

        if text.startswith("```"):
            text = text.strip("`")
            stripped = text.lstrip()
            if stripped.lower().startswith("json"):
                text = stripped[4:]
            text = text.strip()

        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                text = text[start:end + 1]

        return text

    def _build_prompt(self, goal: str, context: str) -> str:
        payload = {
            "goal": goal,
            "context": context,
            "allowed_actions": sorted(self.allowed_actions),
            "max_steps": self.max_steps,
        }
        return (
            "You are Jarvis, a local-first Windows PC agent planner.\n"
            "Create a minimal, safe plan for the user goal.\n"
            "Return JSON only with: steps, stop_condition, reasoning.\n"
            "Each step must have action, target, reason, optional timeout.\n"
            "The context includes a list of installed applications as 'name -> path'.\n"
            "If the goal is to open/launch/focus an application, find the matching entry\n"
            "in that list (case-insensitive, partial match allowed) and use its exact path\n"
            "as the target for an open_app step.\n"
            "Only use notify_user if no matching application is found in the list.\n"
            "Do not invent destructive commands, private file paths, credentials, or admin actions.\n"
            f"Input:\n{json.dumps(payload, ensure_ascii=True, indent=2)}"
        )

    # Prefissi/verbi da ignorare nel target quando l'LLM li include nel testo
    _STRIP_PREFIXES = (
        "apri ", "avvia ", "lancia ", "apre ", "open ", "launch ", "start ",
        "esegui ", "eseguire ", "mostra ",
    )

    def _clean_target(self, target: str) -> str:
        """Rimuove verbi/prefissi di comando dal target se presenti."""
        t = target.strip()
        lower = t.lower()
        for prefix in self._STRIP_PREFIXES:
            if lower.startswith(prefix):
                t = t[len(prefix):].strip()
                lower = t.lower()
        return t

    def _resolve_open_app_target(self, target: str) -> str:
        """
        Valida il target di uno step open_app.

        - URL (http/https): accettato senza modifiche.
        - Path assoluto esistente sul filesystem: accettato senza modifiche.
        - Altrimenti: si tenta di risolverlo tramite l'app registry con
          più strategie (nome esatto, nome ripulito da verbi, basename).
          Se non si trova nulla, PlannerError (niente path inventati).
        """
        lowered = target.lower()
        if lowered.startswith("http://") or lowered.startswith("https://"):
            return target

        if os.path.isabs(target) and os.path.exists(target):
            return target

        apps = scan_installed_apps()

        # Strategia 1: target così com'è
        resolved = find_app(target, apps=apps)
        if resolved:
            return resolved

        # Strategia 2: rimuovi verbi/prefissi di comando (es. "apri cursor" → "cursor")
        cleaned = self._clean_target(target)
        if cleaned != target:
            resolved = find_app(cleaned, apps=apps)
            if resolved:
                return resolved

        # Strategia 3: basename senza estensione (es. path inventato → nome exe)
        candidate = os.path.splitext(os.path.basename(target))[0]
        if len(candidate) >= 3 and candidate.lower() != cleaned.lower():
            resolved = find_app(candidate, apps=apps)
            if resolved:
                return resolved

        # Strategia 4: cerca ogni parola del target pulito separatamente
        # (es. "epic games launcher" → prova "epic", "games", "launcher")
        words = [w for w in cleaned.lower().split() if len(w) >= 4]
        for word in words:
            resolved = find_app(word, apps=apps)
            if resolved:
                return resolved

        raise PlannerError(
            f"open_app target '{target}' does not exist on disk and no matching "
            "installed application was found in the registry"
        )

    def _parse_plan(self, goal: str, payload: dict[str, Any]) -> AgentPlan:
        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise PlannerError("plan.steps must be a non-empty list")
        steps = []
        for raw_step in raw_steps[: self.max_steps]:
            if not isinstance(raw_step, dict):
                raise PlannerError("each plan step must be an object")
            action = str(raw_step.get("action", "")).strip()
            target = str(raw_step.get("target", "")).strip()
            reason = str(raw_step.get("reason", "")).strip()
            if action not in self.allowed_actions:
                raise PlannerError(f"Unsupported planner action: {action}")
            if not target:
                raise PlannerError(f"Missing target for planner action: {action}")

            if action == "open_app":
                target = self._resolve_open_app_target(target)

            timeout = raw_step.get("timeout")
            steps.append(
                AgentStep(
                    action=action,
                    target=target,
                    reason=reason,
                    timeout=int(timeout) if isinstance(timeout, (int, float)) else None,
                )
            )
        return AgentPlan(
            goal=goal,
            steps=tuple(steps),
            stop_condition=str(payload.get("stop_condition", "")).strip() or "first step executed",
            reasoning=str(payload.get("reasoning", "")).strip(),
        )