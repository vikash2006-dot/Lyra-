# LYRA Architecture

LYRA is one backend application and one frontend application. They run, build and test independently and
communicate only through the HTTP API and three WebSocket channels.

```
 Browser (frontend/)                         Backend (backend/)
 ┌───────────────────────┐                  ┌──────────────────────────────────────────────────────────┐
 │ pages/  components/   │                  │ app/api/routes/*    REST endpoints (standard envelope)   │
 │ context/ (App, Chat)  │  REST  /api/*    │ app/api/websocket/* /ws/chat  /ws/voice  /ws/events      │
 │ hooks/ (useVoice …)   │ ───────────────▶ │            │                                             │
 │ services/ api.js      │                  │ app/services/                                            │
 │   chatApi, taskApi …  │ ◀─────────────── │   chat_service ─ session_service ─ store (lyra_api.db)   │
 │   websocket.js        │  WS events       │   task_service (ObservedPlanner / ObservedToolExecutor)  │
 │ utils/audio.js (mic → │                  │   voice_service · document_service · events (bus)        │
 │   16 kHz WAV, playback)│                 │            │                                             │
 └───────────────────────┘                  │ lyra/  (core, unchanged behaviour)                       │
                                            │   companion/orchestrator ─▶ planner ─▶ tools/executor     │
                                            │        │                     (permissions, validation)    │
                                            │        ▼                                                  │
                                            │   routing/router ─▶ providers/ (Gemini, Grok, Groq,       │
                                            │        health + fallback       Cerebras, OpenRouter,      │
                                            │                                Anakin, Ollama)            │
                                            │   tools/: browser, computer (macOS), filesystem, notes,   │
                                            │           media, system, search, weather, news, maps,     │
                                            │           memory, learning, anakin workflows …            │
                                            │   voice/ (STT/TTS) · memory/ · learning/ · auth/ ·        │
                                            │   automation/ (scheduler) · bootstrap.py (wiring)         │
                                            │            │                                             │
                                            │ storage/data/*.db · macOS · the web                       │
                                            └──────────────────────────────────────────────────────────┘
```

## Backend

* **`lyra/`** — the original LYRA core, moved intact. `lyra/bootstrap.py` is the single place that wires
  providers, router, memory, learning, tools, automation, auth and the orchestrator. Both the CLI
  (`lyra/interfaces/cli.py`) and the API use it, so there is one implementation of every behaviour.
* **`app/core/`** — server config (`config.py`), error envelope + exception mapping (`errors.py`), optional
  access token / WebSocket origin check / rate limiter (`security.py`), legacy data migration (`migration.py`).
* **`app/services/`**
  * `container.py` builds one `LyraRuntime` and the API services around it.
  * `chat_service.py` runs turns through `CompanionOrchestrator.process_turn` (REST) or `stream_turn`
    (WebSocket). One turn per conversation at a time (`SESSION_BUSY` otherwise); turns are cancellable.
  * `task_service.py` turns planning and tool execution into tracked *tasks*. It wraps the orchestrator's
    planner and tool executor with observers (the executor still validates arguments and enforces
    permissions exactly as before) and reads the current turn from a `ContextVar`. After a tool succeeds,
    a read-only post-check verifies the effect (e.g. the created folder exists); a failed check fails the step.
  * `session_service.py` + `store.py` persist conversations, messages, tasks and documents in
    `storage/data/lyra_api.db`. Live `Session` objects are rebuilt from history after a restart.
  * `voice_service.py` uses the configured STT/TTS providers (Free STT, macOS `say`, ElevenLabs). macOS
    speech is produced as WAV so browsers can play it. Duplicate clips are rejected.
  * `document_service.py` stores uploads under `storage/uploads/<id>/`, validated with LYRA's own
    `FilePart` safety checks (extension allow-list, executable block-list, size limit).
* **Data** — all SQLite databases live in `backend/storage/data/` (`LYRA_DATA_DIR`). Relative DB paths in
  `.env` are anchored there by `resolve_data_paths`.

## Screen awareness (`lyra/vision/`)

SEE → UNDERSTAND → PLAN → ACT → VERIFY → ADAPT, built on existing infrastructure:

* `capture.py` — `screencapture` per display/window, Retina scale + display origin for coordinate mapping, Screen
  Recording permission check (never bypassed), screenshots kept in memory only; `sips` downscaling for AI.
* `apps.py` — frontmost app (NSWorkspace), windows (Quartz), focused window title (Accessibility).
* `ocr.py` — on-device Apple Vision OCR with bounding boxes (~0.1 s warm; warmed at startup).
* `elements.py` — UI elements from Accessibility (exact) + OCR (text) + vision model (semantic); `locate()` resolves
  "the Login button" in that priority order.
* `analyzer.py` — vision requests only to explicitly vision-capable models (provider defaults are often text-only),
  provider fallback with per-model rate-limit handling; structured JSON (summary, elements, errors, answer, next step).
* `service.py` — `ScreenAwareness`: observe → `ScreenContext` (per conversation, 10 min TTL), actions through the
  existing `ComputerController` policy (fresh coordinates only, sensitive targets need confirmation, never types
  secrets), OCR/vision verification, opt-in `ScreenMonitor` (app/window switches, new errors, big changes; no AI).
* `agent.py` — `VisualAgent`: contextual routing of screen requests (incl. follow-ups like "fix it", "check again"),
  direct local commands ("click the Login button") and a bounded multi-step loop (6 steps, retries, verification).
* `lyra/tools/screen_tool.py` — every visual step runs through `ToolExecutor`, so it is permission-checked and shown
  live as task steps. Cloud vision needs the user's consent (Settings / Screen page); otherwise on-device only.

## Frontend

* `services/api.js` is the only place that calls `fetch`: base URL from `VITE_API_URL`, optional bearer
  token, timeouts and envelope/error parsing. Domain modules (`chatApi`, `taskApi`, `memoryApi`, …) build on it.
* `services/websocket.js` — `LyraSocket` with exponential-backoff reconnection and heartbeats.
* `context/AppContext` — backend health polling, the `/ws/events` feed, live task map, toasts.
* `context/ChatContext` — conversations, streaming chat over `/ws/chat` (falls back to `POST /api/chat`), stop.
* `hooks/useVoice` — idle → listening → processing → speaking state machine over `/ws/voice`, with silence
  detection, interrupt and optional hands-free mode.
* Pages: Chat, Dashboard, Learning, Memory, Documents, Settings. Everything shown comes from the backend.

## Extending LYRA

**Add an API endpoint** — create or extend a module in `backend/app/api/routes/`, add a request model to
`app/schemas.py`, return `ok(data, message)` and raise `APIError(code, message, status)` for client errors.
New router modules are registered in `app/main.py`. Add a test in `backend/tests/api/`.

**Add a frontend component/page** — put API calls in a `src/services/*Api.js` function using `apiData`,
build the component under `src/components/<area>/`, add pages to `src/App.jsx` routes and the sidebar `NAV`.

**Add an AI provider** — implement `lyra/providers/base.AIProvider` (`name`, `is_configured`, `generate`,
optionally `stream`), add it to `build_providers` in `lyra/bootstrap.py`, and add its name to
`PROVIDER_PRIORITY`. It appears automatically in `/api/settings/providers` and the UI. Never return keys.

**Add a tool** — subclass `lyra/tools/base.Tool` (name, description, `input_schema`, `permission_level`,
`can_handle`, `execute`, `format_result`), register it in `build_runtime` in `lyra/bootstrap.py`.
Execution goes through `ToolExecutor`, so validation, permissions, offline blocking and task tracking
apply automatically. Return `"verified": True/False` in the output if the tool checks its own effect.
