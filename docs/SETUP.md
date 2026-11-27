# Setup & Troubleshooting

## Install

```bash
# Python backend (uses the project-root .venv; create it first if missing: python3.14 -m venv .venv)
.venv/bin/pip install -e "backend[dev]"
cp backend/.env.example backend/.env      # skip if you already migrated an existing .env

# Frontend
cd frontend && npm install && cp .env.example .env
```

`frontend/.env` only holds `VITE_API_URL` (and `VITE_API_TOKEN` if the backend requires one). Never put provider
keys there — anything in it is shipped to the browser. Provider keys belong in `backend/.env` only.

## Run

| What | Command |
|---|---|
| Both apps | `npm run dev` (from the project root) |
| Backend only | `cd backend && python main.py` (`--reload` for auto-reload) → http://127.0.0.1:8000/docs |
| Frontend only | `cd frontend && npm run dev` → http://localhost:5173 |
| Terminal voice assistant | `python main.py` (project root) or `cd backend && python cli.py` |
| Terminal text chat | `cd backend && python cli.py chat` |
| Provider diagnostics | `cd backend && python cli.py doctor` |
| Tests | `npm test` |
| Production frontend build | `cd frontend && npm run build` (output in `frontend/dist`) |

`backend/main.py` and `backend/cli.py` re-launch themselves inside `.venv` automatically.

## Data

* Databases: `backend/storage/data/` (`lyra_memory.db`, `lyra_learning.db`, `lyra_auth.db`, `lyra_automation.db`,
  `lyra_api.db` for conversations/tasks/documents).
* Uploads: `backend/storage/uploads/`. Backups from the one-time migration: `backend/storage/backups/`.
* Manual migration (safe to repeat): `cd backend && python scripts/migrate_data.py`.

## Troubleshooting

* **Frontend shows "Backend offline"** — start the backend; check `VITE_API_URL` matches `HOST`/`PORT`.
* **CORS / WebSocket rejected** — add the frontend origin to `CORS_ORIGINS` in `backend/.env` and restart.
* **401 Unauthorized** — `LYRA_API_TOKEN` is set in the backend; set the same value as `VITE_API_TOKEN`.
* **"Port 8000 is already in use"** — LYRA is already running (check `/api/health`) or change `PORT`.
* **Provider shows Auth Failed** — the key in `backend/.env` was rejected; LYRA falls back to the next provider.
* **Microphone does nothing** — allow microphone access for `localhost` in the browser; the voice button is
  disabled until `/ws/voice` is connected.
* **No spoken reply** — "Speak replies" in Settings; on macOS the `say` command must exist.
* **Mac automation fails** — grant Accessibility / Automation permissions to the app running the backend
  (Terminal, iTerm or VS Code) in System Settings → Privacy & Security.

## Deploy the backend on Render

`render.yaml` (project root) is a Render Blueprint for the backend.

1. Push the repository to GitHub.
2. Render Dashboard → **New → Blueprint** → pick the repository → Render reads `render.yaml`.
3. Fill in the secret values it asks for (provider API keys, `CORS_ORIGINS` = your frontend URL). `LYRA_API_TOKEN`
   is generated automatically — copy it from the service's Environment tab.
4. After the deploy, check `https://<service>.onrender.com/api/health` and `/docs`.
5. Point the frontend at it: `VITE_API_URL=https://<service>.onrender.com` and `VITE_API_TOKEN=<token>`.

What runs on the server: chat with all cloud providers and fallback, personality/emotion layer, memory, sessions,
tasks, documents, learning, web search/news/weather/maps, speech-to-text, and speech output via ElevenLabs
(`ELEVENLABS_API_KEY`). Mac-only features — macOS voices, screen awareness, file/app/browser automation — are
disabled by `LYRA_SERVER_MODE=true` and keep working when you run LYRA locally on your Mac.

Data: the free plan has no persistent disk, so memories/conversations reset on every deploy or restart. For
persistence use a paid plan and uncomment the `disk` block (+ `LYRA_DATA_DIR=/var/data`) in `render.yaml`.
Note: a token baked into a public frontend build is visible to anyone who loads that frontend.
