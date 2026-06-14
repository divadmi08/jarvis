from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger("planner")

from core.ai_client import AIClient
from core.app_registry import find_app, load_aliases, scan_installed_apps
from core.task_state import AgentPlan, AgentStep


ALLOWED_AGENT_ACTIONS = frozenset({
    "open_app",
    "close_app",
    "open_url",
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
        # Pre-risolvi eventuali app menzionate nel goal PRIMA di chiamare l'LLM.
        # Questo riduce drasticamente i token: invece di mandare 120 app al modello,
        # mandiamo solo quella rilevante trovata localmente.
        resolved_app = self._pre_resolve_app(goal)
        if resolved_app:
            context = f"Resolved application for this goal: {resolved_app['name']} -> {resolved_app['path']}\n{context}"

        raw = self.ai_client.generate_json(self._build_prompt(goal, context))
        cleaned = self._extract_json(raw)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise PlannerError(
                f"Planner returned invalid JSON: {exc}. Raw output: {raw!r}"
            ) from exc
        return self._parse_plan(goal, payload)

    def _pre_resolve_app(self, goal: str) -> dict | None:
        """
        Cerca nel goal il nome di un'app e la risolve localmente PRIMA dell'LLM.
        Evita di mandare l'intera lista app nel prompt.
        """
        try:
            from core.app_registry import scan_installed_apps, find_app, load_aliases
            cleaned = self._clean_target(goal)
            aliases = load_aliases()
            # Prima controlla alias
            for alias_name, alias_path in aliases.items():
                if alias_name in cleaned.lower() or cleaned.lower() in alias_name:
                    return {"name": alias_name, "path": alias_path}
            # Poi registry
            apps = scan_installed_apps()
            path = find_app(cleaned, apps=apps)
            if path:
                return {"name": cleaned, "path": path}
            # Prova parola per parola (min 5 char per evitare falsi positivi)
            for word in cleaned.lower().split():
                if len(word) >= 5:
                    path = find_app(word, apps=apps)
                    if path:
                        return {"name": word, "path": path}
        except Exception:
            pass
        return None

    @staticmethod
    def _extract_json(raw: str) -> str:
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
            "Each step must have action, target, reason, optional timeout.\n\n"
            "Available actions:\n"
            "- open_app: open an installed application. target = exe path or alias name\n"
            "- close_app: close a running app. target = process name (e.g. 'Discord', 'Steam')\n"
            "- open_url: open a URL in the configured browser. target = full URL\n"
            "- focus_window: bring a window to foreground. target = window title or process name\n"
            "- wait_for_window: wait for a window to appear. target = window title\n"
            "- run_command: run a shell command. target = command string\n"
            "- notify_user: show a notification. target = message text\n"
            "- sleep: pause. target = seconds as string\n\n"
            "Rules:\n"
            "- Use close_app (not run_command/taskkill) to close applications\n"
            "- Use open_url for websites, YouTube, searches, etc.\n"
            "- For web searches: use open_url with https://www.google.com/search?q=<query>\n"
            "- Use open_app only for installed applications\n"
            "- The context may include relevant memory and app aliases — use them\n"
            "- Only use notify_user if no action can fulfill the goal\n"
            "- Do NOT invent paths, credentials, or destructive commands\n"
            f"Input:\n{json.dumps(payload, ensure_ascii=True, indent=2)}"
        )

    _STRIP_PREFIXES = (
        "apri ", "avvia ", "lancia ", "apre ", "open ", "launch ", "start ",
        "esegui ", "eseguire ", "mostra ",
    )

    def _clean_target(self, target: str) -> str:
        t = target.strip()
        lower = t.lower()
        for prefix in self._STRIP_PREFIXES:
            if lower.startswith(prefix):
                t = t[len(prefix):].strip()
                lower = t.lower()
        return t

    def _resolve_open_app_target(self, target: str) -> str:
        """
        Risolve il target di open_app nell'ordine:
        1. URL (http/https) o URI Windows (ms-settings:, ms-windows-store:, ecc.) → accettato
        2. Alias manuale (data/app_aliases.json) → ha priorità assoluta
        3. Path assoluto esistente sul disco → accettato
        4. Registry app (Windows Registry + menu Start)
        5. Fallback: restituisce il target originale e lascia che l'executor fallisca
           in modo controllato (invece di far crashare il planner)
        """
        lowered = target.lower()

        # 1. URL e URI Windows
        uri_prefixes = ("http://", "https://", "ms-", "shell:")
        if any(lowered.startswith(p) for p in uri_prefixes):
            return target

        # 2. Alias manuali — priorità assoluta
        aliases = load_aliases()
        cleaned = self._clean_target(target)
        cleaned_lower = cleaned.lower()

        for check in [cleaned_lower, lowered]:
            if check in aliases:
                return aliases[check]

        for alias_name, alias_path in aliases.items():
            if cleaned_lower in alias_name or alias_name in cleaned_lower:
                return alias_path

        basename_lower = os.path.splitext(os.path.basename(target))[0].lower()
        if len(basename_lower) >= 4:
            if basename_lower in aliases:
                return aliases[basename_lower]
            for alias_name, alias_path in aliases.items():
                if basename_lower in alias_name or alias_name in basename_lower:
                    return alias_path

        # 3. Path assoluto esistente
        if os.path.isabs(target) and os.path.exists(target):
            return target

        # 4. Windows Registry / menu Start
        apps = scan_installed_apps()

        resolved = find_app(cleaned, apps=apps)
        if resolved:
            return resolved

        if os.path.basename(target) != target:
            candidate = os.path.splitext(os.path.basename(target))[0]
            if len(candidate) >= 4:
                resolved = find_app(candidate, apps=apps)
                if resolved:
                    return resolved

        # 5. Non trovato — non crashare, lascia che l'executor lo gestisca
        #    e riporti un errore controllato nel log invece di un traceback
        log.warning(f"open_app: applicazione '{target}' non trovata, il passo fallirà")
        return target

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
            elif action == "close_app":
                # Normalizza: rimuovi path, tieni solo il nome processo
                target = os.path.basename(target).replace(".exe", "").strip()
                if not target:
                    raise PlannerError("close_app: target non valido")
            elif action == "open_url":
                # Assicurati che sia un URL valido
                if not target.startswith("http://") and not target.startswith("https://"):
                    target = "https://" + target

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