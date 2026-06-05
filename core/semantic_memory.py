# core/semantic_memory.py

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.embedding_client import EmbeddingClient
from core.pattern_types import SessionRepresentation, WorkflowPattern

try:
    import chromadb
    from chromadb.config import Settings
except ImportError as exc:
    chromadb = None
    Settings = None
    _CHROMADB_IMPORT_ERROR = exc
else:
    _CHROMADB_IMPORT_ERROR = None


def _session_to_text(session: SessionRepresentation) -> str:
    """
    Converte una sessione in testo leggibile per l'embedding.
    Il formato conta: più è descrittivo, meglio l'embedding cattura il significato.
    """
    apps = ", ".join(session.ordered_apps[:8])
    ctx = session.temporal_context
    duration_min = int(session.total_duration_seconds / 60)
    return (
        f"Work session on {ctx.period} {'weekday' if ctx.weekday else 'weekend'}. "
        f"Apps used in order: {apps}. "
        f"Duration: {duration_min} minutes. "
        f"Dominant apps: {', '.join(session.dominant_apps)}."
    )


def _pattern_to_text(pattern: WorkflowPattern) -> str:
    apps = ", ".join(pattern.apps)
    intent = pattern.semantic_intent.intent if pattern.semantic_intent else "unknown"
    ctx = pattern.temporal_context
    period = ctx.period if ctx else "any time"
    return (
        f"Workflow pattern: {intent}. "
        f"Apps: {apps}. "
        f"Occurs during {period}, {pattern.frequency} times. "
        f"Pattern type: {pattern.pattern_type}."
    )


@dataclass(frozen=True)
class SimilarSession:
    session_id: str
    similarity: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ActivityContext:
    similar_sessions: list[SimilarSession]
    dominant_intent: str | None
    typical_duration_minutes: float
    common_followup_apps: list[str]


class SemanticMemory:
    def __init__(
        self,
        embedder: EmbeddingClient,
        persist_dir: str = "data/chroma_db",
    ) -> None:
        if chromadb is None or Settings is None:
            raise RuntimeError(
                "chromadb is required for SemanticMemory. Install dependencies from requirements.txt."
            ) from _CHROMADB_IMPORT_ERROR
        self._embedder = embedder
        self._chroma = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        self._sessions = self._chroma.get_or_create_collection(
            name="sessions",
            metadata={"hnsw:space": "cosine"},
        )
        self._patterns = self._chroma.get_or_create_collection(
            name="patterns",
            metadata={"hnsw:space": "cosine"},
        )

    def store_session(self, session: SessionRepresentation) -> None:
        if session.session_id is None:
            return
        doc_id = f"session_{session.session_id}"
        text = _session_to_text(session)
        embedding = self._embedder.embed(text)
        metadata = {
            "session_id": session.session_id,
            "start": session.start.isoformat(),
            "end": session.end.isoformat(),
            "apps": json.dumps(list(session.ordered_apps)),
            "period": session.temporal_context.period,
            "weekday": int(session.temporal_context.weekday),
            "duration_seconds": session.total_duration_seconds,
            "dominant_apps": json.dumps(session.dominant_apps),
            "label": session.label or "",
        }
        # upsert: se esiste già lo aggiorna
        self._sessions.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata],
        )

    def store_pattern(self, pattern: WorkflowPattern) -> None:
        doc_id = f"pattern_{pattern.pattern_type}_{'_'.join(pattern.apps)}"
        text = _pattern_to_text(pattern)
        embedding = self._embedder.embed(text)
        intent = pattern.semantic_intent.intent if pattern.semantic_intent else None
        metadata = {
            "pattern_type": pattern.pattern_type,
            "apps": json.dumps(list(pattern.apps)),
            "frequency": pattern.frequency,
            "score": pattern.score.final_score,
            "intent": intent or "",
            "last_seen": pattern.last_seen.isoformat(),
        }
        self._patterns.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata],
        )

    def find_similar_sessions(
        self,
        apps: list[str],
        period: str,
        n: int = 5,
    ) -> list[SimilarSession]:
        total_sessions = self._sessions.count()
        if total_sessions == 0:
            return []
        query_text = (
            f"Work session during {period} with apps: {', '.join(apps[:6])}."
        )
        query_embedding = self._embedder.embed(query_text)
        results = self._sessions.query(
            query_embeddings=[query_embedding],
            n_results=min(n, total_sessions),
            include=["metadatas", "distances"],
        )
        sessions = []
        metadatas = results.get("metadatas") or [[]]
        distances = results.get("distances") or [[]]
        for meta, dist in zip(metadatas[0], distances[0]):
            sessions.append(
                SimilarSession(
                    session_id=str(meta.get("session_id", "")),
                    similarity=round(1.0 - dist, 4),  # cosine distance → similarity
                    metadata=meta,
                )
            )
        return sessions

    def get_activity_context(
        self,
        apps: list[str],
        period: str,
        n: int = 5,
    ) -> ActivityContext:
        similar = self.find_similar_sessions(apps, period, n=n)

        # calcola intent dominante e durata media dalle sessioni simili
        intents: dict[str, int] = {}
        durations: list[float] = []
        followup_counter: dict[str, int] = {}

        for s in similar:
            dur = s.metadata.get("duration_seconds", 0)
            if dur:
                durations.append(float(dur) / 60.0)
            label = str(s.metadata.get("label", "")).strip()
            if label:
                intents[label] = intents.get(label, 0) + 1
            dom = _load_json_list(s.metadata.get("dominant_apps", "[]"))
            for app in dom:
                followup_counter[app] = followup_counter.get(app, 0) + 1

        dominant_intent = max(intents, key=lambda k: intents[k]) if intents else None
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        common_followups = sorted(
            followup_counter, key=lambda k: followup_counter[k], reverse=True
        )[:4]

        return ActivityContext(
            similar_sessions=similar,
            dominant_intent=dominant_intent,
            typical_duration_minutes=avg_duration,
            common_followup_apps=common_followups,
        )


def _load_json_list(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload]
