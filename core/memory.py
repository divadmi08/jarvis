"""
core/memory.py — Jarvis Semantic Memory

Gestisce la memoria semantica di Jarvis tramite ChromaDB.
Permette di:
- Salvare eventi (task completati, sessioni, osservazioni)
- Cercare per similarità semantica dato un goal/query
- Recuperare pattern comportamentali rilevanti

ChromaDB usa embeddings locali (sentence-transformers via onnxruntime)
senza bisogno di API esterne.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("memory")

CHROMA_PATH = str(Path(__file__).resolve().parent.parent / "data" / "chroma_db")

# Nome della collection per i task di Jarvis
TASKS_COLLECTION = "jarvis_tasks"
# Collection esistenti (sola lettura, per context retrieval)
SESSIONS_COLLECTION = "sessions"
PATTERNS_COLLECTION = "patterns"


class SemanticMemory:
    """
    Interfaccia alla memoria semantica di Jarvis.
    Usa ChromaDB persistente in data/chroma_db/.
    """

    def __init__(self, chroma_path: str = CHROMA_PATH) -> None:
        import chromadb
        self._client = chromadb.PersistentClient(path=chroma_path)
        self._tasks = self._client.get_or_create_collection(
            name=TASKS_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        # Collection esistenti (read-only per noi)
        try:
            self._sessions = self._client.get_collection(SESSIONS_COLLECTION)
        except Exception:
            self._sessions = None
        try:
            self._patterns = self._client.get_collection(PATTERNS_COLLECTION)
        except Exception:
            self._patterns = None

    # ── Scrittura ─────────────────────────────────────────────────────────────

    def save_task(
        self,
        task_id: int,
        goal: str,
        action: str,
        target: str,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Salva un task completato nella memoria semantica.
        Il documento è una descrizione testuale naturale per facilitare
        la ricerca per similarità.
        """
        now = datetime.now().isoformat()
        hour = datetime.now().hour
        period = (
            "morning" if 6 <= hour < 12
            else "afternoon" if 12 <= hour < 18
            else "evening" if 18 <= hour < 23
            else "night"
        )

        # Documento testuale — usato per l'embedding
        doc = (
            f"User asked to: {goal}. "
            f"Action taken: {action} on {target}. "
            f"Result: {status}. "
            f"Time: {period}."
        )

        meta = {
            "task_id": task_id,
            "goal": goal,
            "action": action,
            "target": target,
            "status": status,
            "period": period,
            "weekday": datetime.now().weekday(),
            "timestamp": now,
            **(metadata or {}),
        }

        try:
            self._tasks.upsert(
                ids=[f"task_{task_id}"],
                documents=[doc],
                metadatas=[meta],
            )
            log.debug(f"Memory: saved task {task_id} — '{goal}'")
        except Exception as e:
            log.warning(f"Memory: failed to save task {task_id}: {e}")

    # ── Lettura ───────────────────────────────────────────────────────────────

    def search(self, query: str, n_results: int = 5) -> list[dict[str, Any]]:
        """
        Cerca nella memoria per similarità semantica.
        Combina risultati da tasks, sessions e patterns.
        Ritorna lista di {document, metadata, distance, source}.
        """
        results: list[dict[str, Any]] = []

        # Cerca nei task di Jarvis
        if self._tasks.count() > 0:
            try:
                r = self._tasks.query(
                    query_texts=[query],
                    n_results=min(n_results, self._tasks.count()),
                    include=["documents", "metadatas", "distances"],
                )
                for doc, meta, dist in zip(
                    r["documents"][0], r["metadatas"][0], r["distances"][0]
                ):
                    results.append({
                        "document": doc,
                        "metadata": meta,
                        "distance": dist,
                        "source": "tasks",
                    })
            except Exception as e:
                log.warning(f"Memory search (tasks) failed: {e}")

        # Cerca nelle sessioni storiche
        if self._sessions and self._sessions.count() > 0:
            try:
                r = self._sessions.query(
                    query_texts=[query],
                    n_results=min(3, self._sessions.count()),
                    include=["documents", "metadatas", "distances"],
                )
                for doc, meta, dist in zip(
                    r["documents"][0], r["metadatas"][0], r["distances"][0]
                ):
                    results.append({
                        "document": doc,
                        "metadata": meta,
                        "distance": dist,
                        "source": "sessions",
                    })
            except Exception as e:
                log.warning(f"Memory search (sessions) failed: {e}")

        # Cerca nei pattern comportamentali
        if self._patterns and self._patterns.count() > 0:
            try:
                r = self._patterns.query(
                    query_texts=[query],
                    n_results=min(3, self._patterns.count()),
                    include=["documents", "metadatas", "distances"],
                )
                for doc, meta, dist in zip(
                    r["documents"][0], r["metadatas"][0], r["distances"][0]
                ):
                    results.append({
                        "document": doc,
                        "metadata": meta,
                        "distance": dist,
                        "source": "patterns",
                    })
            except Exception as e:
                log.warning(f"Memory search (patterns) failed: {e}")

        # Ordina per rilevanza (distanza minore = più simile)
        results.sort(key=lambda x: x["distance"])
        return results[:n_results]

    def format_for_prompt(self, query: str, n_results: int = 4) -> str:
        """
        Cerca in memoria e formatta i risultati per il prompt del planner.
        Ritorna una stringa compatta con i ricordi più rilevanti.
        """
        results = self.search(query, n_results=n_results)
        if not results:
            return ""

        lines = ["Relevant memory context:"]
        for r in results:
            meta = r["metadata"]
            source = r["source"]

            if source == "tasks":
                goal = meta.get("goal", "")
                target = meta.get("target", "")
                period = meta.get("period", "")
                lines.append(f"- Past task: '{goal}' → opened {target} ({period})")

            elif source == "sessions":
                apps = meta.get("dominant_apps", "[]")
                try:
                    apps_list = json.loads(apps)
                    apps_str = ", ".join(apps_list[:4])
                except Exception:
                    apps_str = str(apps)
                period = meta.get("period", "")
                label = meta.get("label", "")
                lines.append(f"- Past session ({label}, {period}): used {apps_str}")

            elif source == "patterns":
                apps = meta.get("apps", "[]")
                try:
                    apps_list = json.loads(apps)
                    apps_str = ", ".join(apps_list[:4])
                except Exception:
                    apps_str = str(apps)
                intent = meta.get("intent", "")
                freq = meta.get("frequency", 0)
                lines.append(f"- Behavior pattern ({intent}, {freq}x): {apps_str}")

        return "\n".join(lines)

    def recent_tasks(self, limit: int = 5) -> list[dict[str, Any]]:
        """Ritorna i task più recenti dalla memoria."""
        if self._tasks.count() == 0:
            return []
        try:
            r = self._tasks.get(
                limit=limit,
                include=["documents", "metadatas"],
            )
            results = []
            for doc, meta in zip(r["documents"], r["metadatas"]):
                results.append({"document": doc, "metadata": meta})
            # Ordina per timestamp decrescente
            results.sort(
                key=lambda x: x["metadata"].get("timestamp", ""),
                reverse=True,
            )
            return results[:limit]
        except Exception as e:
            log.warning(f"Memory recent_tasks failed: {e}")
            return []


# Singleton globale — inizializzato lazy
_memory: SemanticMemory | None = None


def get_memory() -> SemanticMemory:
    """Ritorna l'istanza singleton della memoria semantica."""
    global _memory
    if _memory is None:
        _memory = SemanticMemory()
    return _memory
