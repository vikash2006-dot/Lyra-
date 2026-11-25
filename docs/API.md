# LYRA Backend API

Base URL `http://127.0.0.1:8000`. Interactive docs: `/docs` (Swagger) and `/redoc`.

All REST responses use one envelope:

```json
{ "success": true,  "data": { }, "message": "Request completed" }
{ "success": false, "error": { "code": "PROVIDER_UNAVAILABLE", "message": "AI provider is currently unavailable." } }
```

If `LYRA_API_TOKEN` is set, send `Authorization: Bearer <token>` (WebSockets: `?token=<token>`).
`/api/health` is always public.

## REST endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Real readiness of orchestrator, providers, memory, learning, store, voice, scheduler |
| POST | `/api/chat` | `{message, session_id?}` → `{response, session_id, task_id, task, model}` (also top-level) |
| POST | `/api/tasks` | `{command, session_id?}` → 202, task runs in background |
| GET | `/api/tasks?status=&limit=` | List tasks (newest first) |
| GET | `/api/tasks/{id}` | Task with steps, verification, response |
| POST | `/api/tasks/{id}/cancel` | Cancel a running task (409 if already finished) |
| POST/GET | `/api/sessions` | Create (`{title?}`) / list conversations |
| GET/PATCH/DELETE | `/api/sessions/{id}` | Get / rename (`{title}`) / delete |
| GET | `/api/sessions/{id}/messages` | Conversation history |
| GET | `/api/memory?q=&type=&limit=` | List or search memories |
| POST | `/api/memory` | `{content, type, importance?, confidence?}` (memory policy enforced) |
| GET/PUT/DELETE | `/api/memory/{id}` | Read / update / delete |
| GET | `/api/memory/types` | Memory categories |
| GET | `/api/voice/status` · `/api/voice/voices` | STT/TTS readiness · macOS voices |
| POST | `/api/voice/transcribe` | multipart `audio` (16-bit PCM WAV, AIFF or FLAC) → `{text}` |
| POST | `/api/voice/speak` | `{text, voice?}` → `{mime_type, audio_base64}` |
| POST | `/api/voice/command` | multipart `audio`, `session_id?`, `speak?`, `voice?` → transcript + LYRA turn + audio |
| POST | `/api/documents/upload` | multipart `file` (allowed text/code/pdf types, ≤ `MAX_UPLOAD_BYTES`) |
| GET | `/api/documents` · `/api/documents/supported-types` | List · allowed extensions |
| GET/DELETE | `/api/documents/{id}` | Read / delete |
| POST | `/api/documents/{id}/analyze` | `{mode: "summary"\|"resume", question?, session_id?}` |
| GET/PUT | `/api/learning/profile` | Learner profile |
| GET/POST | `/api/learning/skills` | Skills (+ mastery, gaps, target roles) / add skill `{skill, level?}` |
| GET | `/api/learning/gaps` | Skill gaps for the target role |
| GET/POST | `/api/learning/plan` | Active plan + today / generate `{duration_weeks, target_role?}` |
| GET | `/api/learning/progress` | Progress report + recent activities |
| GET | `/api/learning/resources?skill=` | Recommended resources |
| POST | `/api/learning/practice` · GET `/api/learning/project` | Practice task · project recommendation |
| POST | `/api/learning/activity` | `{action: "complete_task", task_id}` or `{action: "intake", text}` |
| GET/PUT | `/api/settings` | Safe settings view / `{offline_mode}` at runtime |
| GET | `/api/settings/providers` | Provider name, configured, health status, model, priority (no keys) |
| GET | `/api/system/status` | Uptime, providers, tools, voice, storage counts, active tasks |

Common error codes: `VALIDATION_ERROR`, `SESSION_NOT_FOUND`, `SESSION_BUSY`, `TASK_NOT_FOUND`,
`TASK_NOT_CANCELLABLE`, `MEMORY_REJECTED`, `UNSUPPORTED_AUDIO`, `DUPLICATE_AUDIO`, `UNSUPPORTED_FILE_TYPE`,
`PAYLOAD_TOO_LARGE`, `TARGET_ROLE_REQUIRED`, `PROVIDER_UNAVAILABLE`, `RATE_LIMITED`, `UNAUTHORIZED`, `INTERNAL_ERROR`.

## Task model

```json
{
  "id": "task_1a2b3c", "session_id": "…", "command": "Create a folder called AI Projects on my Desktop",
  "status": "completed", "intent": "create_folder",
  "steps": [{ "index": 0, "tool": "filesystem.create_directory", "description": "Create folder 'AI Projects' on Desktop",
              "status": "completed", "summary": "…", "verified": true,
              "verification_note": "Confirmed /Users/me/Desktop/AI Projects" }],
  "verification": { "summary": "1/1 steps succeeded; 1 independently verified", "checked_steps": 1, "failed": 0 },
  "confirmation_prompt": null, "response": "Done…", "error": null, "created_at": "…", "updated_at": "…"
}
```

Statuses: `pending`, `planning`, `running`, `waiting_for_confirmation`, `verifying`, `completed`, `failed`, `cancelled`.
A task waiting for confirmation is answered by sending "yes"/"no" in the same conversation.

## WebSockets

Every event: `{"type": "...", "timestamp": "ISO-8601", ...}`. Browser connections must come from an allowed
CORS origin.

**`/ws/chat`** — send `{"type":"message","message":"…","session_id":"…"}`, `{"type":"cancel"}`, `{"type":"ping"}`.
Receive: `connected`, `message_received`, `thinking`, `task_started`, `task_update`, `tool_selected`,
`tool_executing`, `tool_result`, `verifying`, `response_start`, `response_delta`, `completed`, `cancelled`, `error`.

**`/ws/voice`** — send `{"type":"start","session_id":"…","speak":true,"voice":"…"}`, then one binary frame per
utterance (WAV), `{"type":"interrupt"}` to stop. Receive: `voice_status` (`transcribing|thinking|synthesizing|idle`),
`transcript`, task/tool events, `response`, `audio` (`mime_type`, `audio_base64`), `cancelled`, `error`.

**`/ws/events`** — receive-only feed of `task_update` (all tasks) and `notification` (scheduled reminders).
