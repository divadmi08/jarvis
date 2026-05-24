# Jarvis — AI Personal PC Agent

### Documento Tecnico di Progetto — v2.0

---

## Cos'è Jarvis

Jarvis è un **AI agent personale che vive nel tuo PC**.

Non è un assistente vocale generico. Non è un chatbot. Non è uno scheduler.

È un sistema che **osserva come usi il computer**, impara i tuoi pattern di comportamento, e nel tempo comincia ad automatizzare il tuo lavoro — prima suggerendo, poi eseguendo, infine anticipando.

La differenza fondamentale rispetto a qualsiasi altro strumento di automazione esistente è questa: Jarvis non ti chiede di configurare nulla. Impara guardandoti lavorare.

---

## Il Problema che Risolve

Ogni giorno, un utente tecnico ripete centinaia di micro-azioni identiche:

- apre sempre le stesse app nello stesso ordine
- switcha tra gli stessi tool ogni volta che inizia a lavorare
- esegue sequenze di comandi che non cambiano mai
- perde tempo a ricordare dove aveva lasciato un progetto

Questi pattern esistono, sono stabili, e sono automatizzabili. Il problema è che nessun tool attuale li rileva da solo — bisogna sempre configurare, scrivere script, impostare regole a mano.

Jarvis risolve questo invertendo il paradigma: **è lui che osserva e propone, non l'utente che configura**.

---

## Cosa Diventerà

Nella sua forma finale, Jarvis è un **AI Operating Layer** sopra Windows.

Un sistema che:

**Osserva** — registra ogni app aperta, ogni finestra attiva, ogni sequenza di azioni, costruendo una mappa precisa di come lavori e giochi.

**Impara** — identifica pattern ripetitivi, li trasforma in routine nominate, e li propone all'utente per conferma. Senza supervisione manuale.

**Agisce** — su comando vocale o testuale, esegue workflow completi: apre ambienti di lavoro, installa software, gestisce file, naviga interfacce grafiche.

**Migliora** — ogni esecuzione, ogni correzione, ogni feedback dell'utente diventa dato di apprendimento. Il sistema diventa più preciso nel tempo.

La visione a 12 mesi è un agente semi-autonomo che conosce le tue abitudini meglio di te, automatizza il tuo setup quotidiano senza che tu debba chiederglielo, e riesce a portare a termine task nuovi pianificando i passi da solo e chiedendo conferma prima di eseguire.

---

## Principi di Design

**Local-first** — tutti i dati (log, sessioni, pattern, routine) vivono sul PC dell'utente. Nessun dato personale esce mai dalla macchina. L'unica comunicazione esterna è la chiamata API al LLM, che riceve solo il testo del comando — mai i log o le sessioni.

**Budget zero** — nessun costo fisso, nessun abbonamento. Il LLM è Gemini API con tier gratuito permanente. Tutto il resto è open source o built-in Python.

**Peso minimo** — Jarvis non deve mai farsi sentire. L'Observer gira silenzioso in background con un impatto inferiore a quello di un antivirus. Il LLM viene chiamato solo quando l'utente parla attivamente con Jarvis, poi torna a zero consumo. Durante il gaming o sessioni intensive, il sistema non pesa nulla.

**Sicurezza a livelli** — nessuna azione viene eseguita senza un sistema di permessi esplicito. Le azioni rischiose richiedono sempre conferma.

**Valore incrementale** — ogni fase di sviluppo produce qualcosa di usabile realmente, non solo un prototipo. L'utente riceve valore già dal primo mese.

**Modularità** — ogni componente è indipendente, testabile e sostituibile. Il sistema cresce per aggiunta, non per riscrittura.

---

## Stack Tecnologico Definitivo

|Componente|Tecnologia|Costo|Motivazione|
|---|---|---|---|
|Linguaggio|Python 3.11+|Gratuito|Basi avanzate, ecosistema AI maturo|
|Storage persistente|SQLite|Gratuito|Locale, zero dipendenze, perfetto per log e sessioni|
|Similarità semantica|ChromaDB (locale)|Gratuito|Vector DB embedded per pattern matching semantico|
|Comunicazione interna|`queue` built-in|Gratuito|Sufficiente per architettura single-process|
|Interazione OS|pywin32, pyautogui|Gratuito|API Windows native per osservazione e controllo UI|
|**LLM**|**Gemini API (free tier)**|**Gratuito**|**15 req/min, 1500 req/giorno — più che sufficiente**|
|Riconoscimento vocale|Whisper (locale)|Gratuito|STT offline, nessun audio inviato fuori|
|Sintesi vocale|pyttsx3 (locale)|Gratuito|TTS offline, zero dipendenze cloud|
|UI|HTML/JS locale|Gratuito|Chat-style, aperta nel browser, nessun framework|
|Platform|Windows 10/11 only|—|API OS consistenti, espansione futura|

### Perché Gemini API e non altro

**Gemini API (Google)** ha un tier gratuito reale e permanente:

- 15 richieste al minuto
- 1.500 richieste al giorno
- 1 milione di token al giorno

Per un agent personale, questi limiti non vengono mai raggiunti. Una conversazione con Jarvis è 3-5 richieste al giorno in media.

**Peso sul PC: zero.** La chiamata API dura 1-2 secondi solo quando parli con Jarvis. Tra una chiamata e l'altra non gira nulla di aggiuntivo. Durante il gaming, durante sessioni intensive, durante qualsiasi cosa — Jarvis non consuma né CPU né GPU né RAM per il LLM.

> ❌ **Claude API (Anthropic): rimossa** — non ha tier gratuito per uso programmatico. ❌ **Ollama: rimosso** — modelli locali occupano 4-8GB di VRAM anche in standby. Incompatibile con l'obiettivo di peso minimo, specialmente durante il gaming.

---

## Architettura del Sistema

```
┌─────────────────────────────────────────────────────┐
│                    UI Layer                         │
│         Chat HTML/JS  ·  Voce (Whisper locale)      │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│                  Agent Core                         │
│   Intent Recognizer → Task Planner → Verifier       │
│              (chiamate Gemini API)                  │
└──────┬─────────────────┬───────────────┬────────────┘
       │                 │               │
┌──────▼──────┐  ┌───────▼───────┐  ┌───▼──────────┐
│  Observer   │  │   Executor    │  │  Permission  │
│  Module     │  │   Engine      │  │  System      │
│ (sempre on) │  │ (on demand)   │  │              │
└──────┬──────┘  └───────┬───────┘  └──────────────┘
       │                 │
┌──────▼─────────────────▼───────────────────────────┐
│                   Data Layer                        │
│         SQLite (jarvis.db)  ·  ChromaDB (locale)   │
└─────────────────────────────────────────────────────┘
                         │
                    (solo su richiesta)
                         │
┌────────────────────────▼───────────────────────────┐
│              Gemini API (Google)                   │
│           Free tier · chiamata 1-2s               │
│        poi torna a zero consumo                    │
└────────────────────────────────────────────────────┘
```

### Moduli Principali

**Observer Module** — monitora in tempo reale l'app in foreground, il titolo della finestra attiva e il tempo di utilizzo. Polling ogni 5 secondi. Impatto CPU trascurabile (< 0.5%). Sempre attivo, silenzioso.

**Session Builder** — aggrega i record dell'Observer in sessioni coerenti. Una nuova sessione parte se c'è inattività superiore a 10 minuti. Ogni sessione viene etichettata con le app predominanti.

**Pattern Engine** — analizza le sessioni storiche e identifica sequenze di app usate insieme con frequenza. Soglia minima: pattern visto almeno 5 volte. Propone routine nominate.

**Execution Engine** — esegue azioni reali sul sistema operativo: apre applicazioni, porta finestre in foreground, simula input, esegue comandi shell. Ogni azione passa prima dal Permission System.

**Intent Recognizer** — riceve input testuale o vocale e lo trasforma in un intent strutturato via Gemini API. Viene chiamato solo su input utente esplicito.

**Task Planner** — per task non coperti da routine esistenti, genera un piano step-by-step via Gemini API. Il piano viene mostrato all'utente prima di qualsiasi esecuzione.

**Permission System** — valuta ogni azione proposta e ne determina il livello di rischio. Gestisce il flusso di conferma utente.

**Verifier** — dopo ogni step eseguito, verifica che l'azione abbia prodotto il risultato atteso. Gestisce i retry con limite massimo di 3 tentativi.

---

## Schema Database (SQLite)

```sql
-- Attività raw registrate dall'Observer
CREATE TABLE activity_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    app_name        TEXT NOT NULL,
    window_title    TEXT,
    duration_sec    INTEGER NOT NULL
);

-- Sessioni aggregate dal Session Builder
CREATE TABLE sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time      DATETIME NOT NULL,
    end_time        DATETIME,
    label           TEXT,
    apps_used       TEXT,         -- JSON array: ["IntelliJ", "Chrome", "Terminal"]
    pattern_score   REAL          -- confidenza del pattern (0.0–1.0)
);

-- Routine nominate (salvate o proposte dal sistema)
CREATE TABLE routines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT,
    trigger_type    TEXT,         -- "voice", "schedule", "manual", "auto"
    trigger_value   TEXT,         -- es. "hey jarvis coding mode", "09:00"
    steps           TEXT,         -- JSON array di azioni
    permission_lvl  TEXT NOT NULL DEFAULT 'safe',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_run        DATETIME,
    run_count       INTEGER DEFAULT 0,
    auto_learned    INTEGER DEFAULT 0  -- 1 se suggerita dal sistema
);

-- Log di ogni esecuzione
CREATE TABLE execution_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    routine_id      INTEGER REFERENCES routines(id),
    started_at      DATETIME NOT NULL,
    completed_at    DATETIME,
    status          TEXT,         -- success / failed / partial / cancelled
    steps_done      INTEGER DEFAULT 0,
    steps_total     INTEGER DEFAULT 0,
    error_msg       TEXT,
    retry_count     INTEGER DEFAULT 0
);

-- Pattern identificati dal Pattern Engine
CREATE TABLE patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    apps_sequence   TEXT NOT NULL, -- JSON array ordinato
    occurrences     INTEGER DEFAULT 1,
    first_seen      DATETIME,
    last_seen       DATETIME,
    proposed        INTEGER DEFAULT 0,  -- 1 se già proposto all'utente
    accepted        INTEGER DEFAULT 0   -- 1 se l'utente ha creato la routine
);
```

---

## Sistema di Permessi

```
Azione richiesta
      │
      ▼
  Valutazione livello
      │
      ├── 🟢 SAFE ──────► Esecuzione diretta
      │   (apri app, porta in foreground,
      │    avvia routine già approvata)
      │
      ├── 🟡 MEDIUM ────► Conferma la prima volta → ricorda la scelta
      │   (installa software, scarica file,
      │    modifica impostazioni non critiche)
      │
      └── 🔴 RISKY ─────► Conferma SEMPRE, senza eccezioni
          (elimina file, modifica registro,
           azioni irreversibili di sistema)
```

---

## Verification Loop

```python
MAX_RETRIES = 3

for step in plan:
    for attempt in range(MAX_RETRIES):
        execute(step)
        if verify(step):
            break
        if attempt == MAX_RETRIES - 1:
            notify_user(f"Step '{step}' fallito dopo {MAX_RETRIES} tentativi")
            log_error(step)
            return Status.PARTIAL_FAILURE
```

Il sistema non continua oltre il terzo tentativo fallito. Notifica e si ferma. Non si inceppa su se stesso.

---

## Struttura del Progetto

```
jarvis/
│
├── core/
│   ├── observer.py           # Monitora app attiva (polling 5s)
│   ├── session_builder.py    # Aggrega attività in sessioni
│   ├── pattern_engine.py     # Identifica routine ricorrenti
│   └── executor.py           # Esegue azioni sul sistema
│
├── agent/
│   ├── intent_recognizer.py  # Testo/voce → intent JSON (Gemini API)
│   ├── task_planner.py       # Intent → piano step-by-step (Gemini API)
│   └── verifier.py           # Verifica esecuzione + retry
│
├── system/
│   ├── permissions.py        # Valutazione e gestione permessi
│   ├── voice.py              # STT con Whisper locale
│   ├── tts.py                # TTS con pyttsx3 locale
│   └── notifier.py           # Notifiche Windows
│
├── data/
│   ├── jarvis.db             # SQLite database
│   └── chroma/               # ChromaDB vector store (locale)
│
├── ui/
│   ├── chat.html             # Interfaccia chat principale
│   ├── dashboard.html        # Statistiche e routine
│   └── static/               # CSS, JS, assets
│
├── config/
│   ├── settings.json         # Configurazione generale
│   └── permissions.json      # Mappatura azioni → livelli di rischio
│
├── tests/
│   ├── test_observer.py
│   ├── test_pattern_engine.py
│   └── test_executor.py
│
├── main.py                   # Entry point
└── requirements.txt
```

---

## 🗓 Roadmap MVP — Dettaglio Completo

---

### 📦 FASE 1 — Observer System

**Durata: 4 settimane | Obiettivo: il sistema vede e ricorda cosa fai**

---

#### Settimana 1 — Fondamenta e primo log

**Obiettivo**: il sistema gira in background e salva ogni app usata.

Attività:

- Setup ambiente Python (venv, `.gitignore`, struttura cartelle)
- Creazione database SQLite con schema completo
- Scrittura `observer.py`:
    - polling ogni 5 secondi con `win32gui.GetForegroundWindow()`
    - estrazione `app_name` e `window_title`
    - calcolo `duration_sec` per ogni app
    - salvataggio su `activity_log`
- Script di avvio in background con tray icon minimale (`pystray`)

**Deliverable**: Jarvis gira in background. Apri il DB dopo un'ora e vedi ogni app che hai usato con i relativi tempi.

---

#### Settimana 2 — Session Builder

**Obiettivo**: le attività raw diventano sessioni significative.

Attività:

- Scrittura `session_builder.py`:
    - legge `activity_log` ogni 15 minuti
    - raggruppa record in sessione se gap < 10 minuti
    - calcola `apps_used` (JSON array ordinato per tempo di utilizzo)
    - assegna `label` automatica (es. "coding" se IntelliJ è dominante)
    - salva su `sessions`
- File di configurazione per le regole di labeling

**Deliverable**: ogni sera vedi le tue sessioni della giornata con label, durata totale e app usate.

---

#### Settimana 3 — Pattern Engine base

**Obiettivo**: il sistema identifica cosa fai sempre insieme.

Attività:

- Scrittura `pattern_engine.py`:
    - analisi sequenze di app per sessione (sliding window)
    - conteggio co-occorrenze: quali app apri sempre insieme?
    - soglia minima: pattern visto 5+ volte nelle ultime 4 settimane
    - salvataggio su tabella `patterns`

**Deliverable**: lista di pattern identificati. Es: `["IntelliJ", "Chrome", "Terminal"]` → 12 occorrenze rilevate.

---

#### Settimana 4 — UI minimale e validazione

**Obiettivo**: visualizzare i dati raccolti e validare il sistema su uso reale.

Attività:

- UI HTML/JS locale:
    - tabella sessioni recenti con label e durata
    - lista pattern identificati con conteggio occorrenze
    - grafico utilizzo app ultimi 7 giorni (Chart.js)
- Modalità "dry run": mostra cosa farebbe il sistema senza eseguire nulla
- Test reale: usa il PC normalmente per 5 giorni e verifica la qualità dei pattern rilevati

**Deliverable**: dashboard funzionante. Observer validato su uso reale end-to-end.

---

### ⚙️ FASE 2 — Automation Engine

**Durata: 4 settimane | Obiettivo: il sistema esegue azioni reali**

---

#### Settimana 5 — Execution Engine base

**Obiettivo**: Jarvis apre app e gestisce finestre su comando.

Attività:

- Scrittura `executor.py`:
    - `open_app(path)` via `subprocess.Popen`
    - `focus_window(title)` via `win32gui`
    - `run_command(cmd)` via `subprocess` con timeout
    - `type_text(text)` e `click(x, y)` via `pyautogui`
- Struttura dati JSON per descrivere una routine:

```json
{
  "name": "Java Dev Mode",
  "steps": [
    {"action": "open_app", "target": "C:/IntelliJ/bin/idea64.exe"},
    {"action": "open_app", "target": "C:/Chrome/chrome.exe"},
    {"action": "focus_window", "target": "IntelliJ IDEA"}
  ]
}
```

**Deliverable**: da terminale, lanci una routine JSON e Jarvis apre tutto il tuo ambiente di sviluppo.

---

#### Settimana 6 — Permission System

**Obiettivo**: nessuna azione rischiosa senza consenso esplicito.

Attività:

- Scrittura `permissions.py`:
    - mappa ogni tipo di azione → livello (safe / medium / risky)
    - flusso di conferma: popup Windows per medium e risky
    - memoria: se l'utente approva un'azione medium, la ricorda per le volte successive
- File `permissions.json` con mappatura configurabile
- Integrazione con `executor.py`: ogni azione viene valutata prima di essere eseguita

**Deliverable**: prova a eseguire un'azione risky senza averla approvata. Il sistema si ferma e chiede conferma esplicita.

---

#### Settimana 7 — Routine Manager

**Obiettivo**: creare, modificare e lanciare routine in modo strutturato.

Attività:

- CRUD completo routine su SQLite
- Interfaccia UI per gestione routine (lista, dettaglio, modifica, elimina)
- Trigger manuale da UI e da linea di comando
- Integrazione pattern → routine: se un pattern confermato dall'utente diventa routine salvata
- Primo comando testuale base: "avvia [nome routine]"

**Deliverable**: dalla dashboard puoi vedere le routine, crearne di nuove, modificarle e avviarle con un click.

---

#### Settimana 8 — Stabilità e test

**Obiettivo**: il sistema è affidabile su uso quotidiano reale.

Attività:

- Gestione errori robusta in `executor.py` (app non trovata, finestra non risponde, timeout)
- Logging completo su `execution_log`
- Test su almeno 5 routine reali usate ogni giorno per una settimana intera
- Fix dei bug emersi dall'uso reale

**Deliverable**: Automation Engine usato quotidianamente senza crash o comportamenti inattesi.

---

### 🤖 FASE 3 — Autonomous Agent

**Durata: 8 settimane | Obiettivo: il sistema capisce e pianifica task nuovi**

---

#### Settimana 9–10 — Intent Recognition con Gemini API

**Obiettivo**: Jarvis capisce cosa vuoi in linguaggio naturale. Zero peso sul PC.

Attività:

- Setup Gemini API (Google AI Studio → API key gratuita)
- Scrittura `intent_recognizer.py`:
    - system prompt con lista routine disponibili e azioni supportate
    - input: testo libero dell'utente
    - output: JSON strutturato con `intent_type` e `parameters`
    - chiamata API solo su input utente esplicito (non in background)
- Esempi di intent riconosciuti:

```json
{"intent": "run_routine", "routine_name": "Java Dev Mode"}
{"intent": "new_task", "description": "installa Node.js"}
{"intent": "query", "question": "quanto ho usato Chrome oggi?"}
{"intent": "unknown", "raw": "testo non capito"}
```

- Gestione intent non riconosciuti: risposta con richiesta di chiarimento

**Deliverable**: scrivi "metti su l'ambiente java" → Jarvis riconosce l'intent e avvia la routine corretta.

**Nota tecnica**: la chiamata Gemini dura 1-2 secondi, poi il processo torna a consumo zero. Durante gaming o sessioni intensive, se non parli con Jarvis non viene fatta nessuna chiamata.

---

#### Settimana 11–12 — Task Planner

**Obiettivo**: per task nuovi, Jarvis crea un piano e lo mostra prima di eseguire.

Attività:

- Scrittura `task_planner.py`:
    - input: intent di tipo `new_task`
    - prompt a Gemini API con lista azioni disponibili nell'executor
    - output: array JSON di step ordinati e validati
    - validazione: ogni step deve corrispondere a un'azione implementata
- UI: mostra il piano step-by-step con tre opzioni: Approva / Modifica / Annulla

**Esempio piano generato:**

```json
{
  "task": "Installa Node.js",
  "steps": [
    {"action": "open_url", "target": "https://nodejs.org/en/download"},
    {"action": "notify_user", "msg": "Scarica il Windows Installer e avvialo"},
    {"action": "wait_for_window", "title": "Node.js Setup"}
  ]
}
```

**Deliverable**: scrivi un task nuovo → Jarvis propone un piano → tu approvi → esegue.

---

#### Settimana 13–14 — Execution + Verification completa

**Obiettivo**: il sistema esegue piani multi-step e gestisce gli errori.

Attività:

- Collegamento Task Planner → Execution Engine
- Implementazione Verification Loop completo (max 3 retry per step)
- Gestione casi intermedi: step fallito → chiedi all'utente se saltare o interrompere
- Feedback in real-time in UI: step in corso, step completati, step falliti

**Deliverable**: Jarvis esegue un task di 5 step, uno fallisce, chiede cosa fare, riprende dalla scelta dell'utente.

---

#### Settimana 15–16 — Controllo vocale

**Obiettivo**: puoi dare comandi a Jarvis senza toccare la tastiera.

Attività:

- Integrazione Whisper locale (`openai-whisper`): STT completamente offline
- Wake word detection per attivare l'ascolto: "Hey Jarvis"
- Pipeline completa: audio → Whisper → testo → Intent Recognizer → Planner/Executor
- Canale voce separato dal canale chat nel codice (stessa logica, input diverso)
- Feedback audio con `pyttsx3` locale: Jarvis risponde a voce

**Deliverable**: dici "Hey Jarvis, avvia coding mode" → il sistema risponde e agisce senza toccare il PC.

---

### 🧠 FASE 4 — Learning System

**Durata: 8 settimane | Obiettivo: il sistema impara da solo**

---

#### Settimana 17–18 — ChromaDB Integration

**Obiettivo**: il sistema trova pattern simili usando similarità semantica.

Attività:

- Setup ChromaDB embedded locale (zero server, zero costi)
- Vettorizzazione sessioni: ogni sessione → embedding testuale → ChromaDB
- Query: "trova sessioni simili a questa" → suggerisce routine applicabile
- Integrazione con Pattern Engine: pattern confermati entrano nel vector store

**Deliverable**: inizi una sessione con le solite app → Jarvis suggerisce automaticamente "Vuoi avviare Java Dev Mode?"

---

#### Settimana 19–20 — Auto-learning Routine

**Obiettivo**: il sistema propone nuove routine senza che tu debba chiederglielo.

Attività:

- Trigger automatico: pattern con 5+ occorrenze non ancora routine → notifica
- Notifica Windows: "Ho notato che ogni mattina apri IntelliJ, Chrome e Terminal. Vuoi che lo automatizzi?"
- Flusso di approvazione: utente accetta → routine creata e salvata → `auto_learned = 1`
- Dashboard: sezione "Suggeriti dal sistema" separata dalle routine manuali

**Deliverable**: usa il PC normalmente per una settimana. Jarvis propone 2–3 routine senza che tu abbia fatto nulla.

---

#### Settimana 21–22 — Dashboard completa

**Obiettivo**: visibilità totale su cosa fa il sistema.

Attività:

- Dashboard `dashboard.html` completa:
    - tempo per app (oggi / settimana / mese)
    - sessioni recenti con label e durata
    - routine: esecuzioni totali, tasso di successo, ultima esecuzione
    - pattern in apprendimento: occorrenze e stato
- Grafici con Chart.js (locale)
- Export dati in JSON e CSV

**Deliverable**: apri la dashboard e hai una vista completa su come usi il PC e su tutto quello che Jarvis ha imparato.

---

#### Settimana 23–24 — Rifinitura finale

**Obiettivo**: sistema installabile, stabile e documentato.

Attività:

- Avvio automatico con Windows (Task Scheduler)
- Tray icon con menu: pausa, apri dashboard, esci
- Backup automatico database (copia giornaliera compressa)
- Import/export routine in JSON
- Documentazione interna completa (docstring)
- `README.md` con guida installazione passo-passo

**Deliverable**: installabile da zero in meno di 10 minuti. Stabile. Documentato. Usabile ogni giorno.

---

## Milestone di Progetto

|#|Milestone|Fine|Cosa funziona concretamente|
|---|---|---|---|
|M1|Observer completo|Mese 1|Jarvis registra tutto, mostra sessioni e pattern|
|M2|Automation stabile|Mese 2|Routine eseguite, permessi attivi, log completo|
|M3|Agent base|Mese 3|Comandi linguaggio naturale via Gemini API|
|M4|Voce attiva|Mese 4|Wake word + esecuzione completa senza tastiera|
|M5|Learning attivo|Mese 5–6|Routine suggerite, ChromaDB, dashboard completa|

---

## Rischi e Mitigazioni

|Rischio|Probabilità|Mitigazione|
|---|---|---|
|Gemini API rate limit superato|Molto bassa|1500 req/giorno è ~300 conversazioni. Impossibile da superare in uso personale|
|Gemini API non disponibile (offline)|Bassa|Jarvis funziona normalmente senza LLM: Observer, routine manuali e Execution Engine non dipendono dall'API|
|Falsi positivi nei pattern|Media|Soglia minima 5 occorrenze + conferma utente sempre richiesta|
|Executor che rompe UI dell'app target|Media|Timeout su ogni azione + max 3 retry|
|Consumo CPU Observer|Molto bassa|Polling 5s è < 0.5% CPU. Verificabile con Task Manager|
|Conflitti pyautogui con input utente|Media|Pausa esecuzione se rilevato input umano durante uno step|

---

## Dipendenze Python

```txt
# Sistema operativo Windows
pywin32>=306
pyautogui>=0.9.54
psutil>=5.9.0
pystray>=0.19.0
pillow>=10.0.0

# Database
# sqlite3 → built-in Python, nessuna installazione
chromadb>=0.4.0

# LLM — Gemini API (gratuita)
google-generativeai>=0.5.0

# Voce — tutto locale, nessun cloud
openai-whisper>=20231117
pyttsx3>=2.90

# Utility
schedule>=1.2.0
```

**Costo totale dipendenze: €0.**

---

## Note Finali

Jarvis non è un prodotto da consegnare a una scadenza. È un sistema personale che cresce con chi lo costruisce.

Ogni settimana della roadmap produce qualcosa di concreto e usabile. Non ci sono settimane di architettura astratta o ricerca teorica.

Il sistema è progettato per essere invisibile quando non serve e utile quando lo chiami. Non pesa, non distrae, non costa nulla.

---

_Jarvis PC Agent — Documento Tecnico v2.0_ _Budget: €0 | Platform: Windows 10/11 | Linguaggio: Python 3.11+_
