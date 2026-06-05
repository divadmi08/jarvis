# Jarvis - Stato Software Attuale

Aggiornato al 2026-06-05.

## Visione

Jarvis e un AI Personal PC Agent per Windows, scritto in Python, local-first e pensato per osservare l'uso del PC, riconoscere abitudini, ricordare contesto, proporre automazioni e prepararsi a eseguire workflow autonomi in modo controllato.

## Stato Generale

Il progetto ha gia una pipeline funzionante:

1. osserva le finestre attive;
2. salva eventi raw in SQLite;
3. costruisce sessioni di lavoro;
4. estrae pattern ricorrenti;
5. inferisce intenti tramite regole;
6. consolida memoria long-term in SQLite e ChromaDB;
7. genera reflection sintetiche sulle abitudini;
8. recupera contesto storico per migliorare le routine proposte;
9. propone routine sicure usando Gemini;
10. puo eseguire step controllati tramite Executor e Permission System.

## Funzionalita Attuali

### Observer System

Modulo principale: `core/observer.py`

- Monitora l'app/finestra attiva su Windows.
- Tiene traccia dei cambi di focus.
- Salva attivita in `activity_log`.
- Filtra e persiste durata, app e titolo finestra.

### SQLite Database

Modulo principale: `data/database.py`

Tabelle principali:

- `activity_log`
- `sessions`
- `patterns`
- `routine_proposals`
- `system_state`
- `memory_events`
- `reflections`
- `intent_predictions`

Il DB supporta osservazione, sessioni, pattern, proposte routine, stato incrementale, memoria long-term e reflection.

### Session Builder

Modulo principale: `session_builder.py`

- Raggruppa eventi raw in sessioni.
- Filtra rumore e processi di sistema.
- Calcola app dominanti, durata e focus.
- Supporta sync incrementale.

### Pattern Engine

Modulo principale: `core/pattern_engine.py`

- Carica sessioni recenti.
- Costruisce rappresentazioni strutturate delle sessioni.
- Estrae pattern di co-occorrenza, temporali e sequenziali.
- Applica scoring, recency, compression e similarity.
- Salva pattern in SQLite.
- Ora consolida memoria e reflection a ogni run.

### Intent Inference

Modulo principale: `core/intent_inference.py`

- Classifica intenti tramite regole locali.
- Riconosce casi come sviluppo backend, ricerca, comunicazione, design e lavoro admin.

Modulo opzionale: `core/llm_intent_recognizer.py`

- Usa Gemini per classificare intenti da app, contesto temporale e contesto recuperato.
- E progettato come fallback/upgrade opzionale rispetto alle regole.

### Semantic Memory

Moduli principali:

- `core/semantic_memory.py`
- `core/embedding_client.py`
- `core/memory_consolidator.py`
- `core/memory_types.py`

Funzionalita:

- Salva sessioni e pattern in ChromaDB.
- Usa embedding locali offline tramite `LocalEmbeddingClient`.
- Supporta embedding Gemini tramite `GeminiEmbeddingClient`.
- Salva eventi long-term in SQLite nella tabella `memory_events`.
- Recupera sessioni simili per app e periodo.
- Produce contesto utile per prompt e decisioni.

### Reflection System

Modulo principale: `core/reflection_engine.py`

- Genera insight sintetici dalle sessioni e dai pattern.
- Salva reflection in SQLite.
- Esempi:
  - focus dominante recente;
  - workflow piu forte appreso;
  - intenti/app ricorrenti.

### Context Retrieval

Modulo principale: `core/context_builder.py`

- Recupera sessioni semanticamente simili.
- Recupera proposte routine passate.
- Recupera memory events pertinenti.
- Recupera reflection recenti.
- Serializza tutto in un blocco leggibile per il prompt Gemini.

### Routine Proposal Service

Moduli principali:

- `core/routine_proposer.py`
- `core/routine_proposal_service.py`
- `core/routine_proposal_types.py`
- `propose_routines.py`

Funzionalita:

- Trova pattern candidati.
- Evita app non gestite.
- Costruisce prompt sicuri per Gemini.
- Include contesto storico quando disponibile.
- Valida JSON e azioni consentite.
- Salva routine proposte in SQLite.

### Permission System

Modulo principale: `system/permissions.py`

- Classifica azioni per livello di rischio.
- Richiede approvazione per azioni sensibili.
- Memorizza permessi medi gia approvati.

### Executor

Modulo principale: `core/executor.py`

- Esegue step controllati.
- Supporta azioni come apertura/focus app, sleep, notify e comandi con vincoli.
- Evita shell implicita per comandi con operatori shell.

## Flusso Architetturale Attuale

```text
Observer
  -> SQLite activity_log
  -> SessionBuilder
  -> SQLite sessions
  -> PatternEngine
  -> SQLite patterns
  -> MemoryConsolidator
     -> SQLite memory_events
     -> ChromaDB sessions/patterns
     -> ReflectionEngine
        -> SQLite reflections
  -> ContextBuilder
     -> SemanticMemory retrieval
     -> memory_events/reflections/proposals retrieval
  -> RoutineProposer
     -> Gemini
     -> SQLite routine_proposals
  -> Executor + PermissionSystem
```

## Cosa Funziona Ora

- Osservazione PC.
- Persistenza eventi.
- Costruzione sessioni incrementale.
- Mining pattern.
- Intenti rule-based.
- Proposte routine via Gemini.
- Validazione di sicurezza delle routine.
- Executor con permission layer.
- Memoria semantica con ChromaDB.
- Memoria long-term in SQLite.
- Reflection locali.
- Retrieval contestuale per prompt routine.
- Embedding offline a costo zero.

## Limiti Attuali

- L'intent recognition LLM e presente come modulo, ma non e ancora il path default.
- Non esiste ancora un vero agent loop autonomo goal-driven.
- Non esiste ancora screen understanding visivo.
- Computer Use avanzato non e ancora implementato.
- Il LocalEmbeddingClient e economico e stabile, ma meno accurato di embedding Gemini o modelli sentence-transformers.
- Le reflection sono deterministiche e semplici: utili per MVP, non ancora ragionamento profondo multi-step.

## Prossimo Upgrade Naturale

Il prossimo passo consigliato e collegare `LLMIntentRecognizer` come fallback controllato quando le regole locali hanno bassa confidenza. Dopo questo, ha senso costruire un piccolo `AgentLoop` con:

- goal;
- retrieved context;
- plan JSON;
- permission check;
- execute one step;
- observe result;
- stop/replan.
