"""Voice endpoints and WebSocket channels."""

import base64

from tests.api.helpers import make_wav


def test_voice_status_and_speak(client):
    status = client.get("/api/voice/status").json()["data"]
    assert status["stt_ready"] and status["tts_ready"]
    audio = client.post("/api/voice/speak", json={"text": "Hello there"}).json()["data"]
    assert audio["bytes"] > 0 and base64.b64decode(audio["audio_base64"])


def test_transcribe_and_reject_bad_audio(client):
    r = client.post("/api/voice/transcribe", files={"audio": ("a.wav", make_wav(seed=1), "audio/wav")})
    assert r.json()["data"]["text"] == "Hello LYRA, what time is it?"  # mock STT
    r = client.post("/api/voice/transcribe", files={"audio": ("a.webm", b"\x1aE\xdf\xa3notwav", "audio/webm")})
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_AUDIO"


def test_voice_command_full_pipeline_and_duplicate_guard(client):
    wav = make_wav(seed=2)
    r = client.post("/api/voice/command", files={"audio": ("a.wav", wav, "audio/wav")})
    data = r.json()["data"]
    assert data["transcript"] == "Hello LYRA, what time is it?"
    assert data["task"]["steps"][0]["tool"] == "time"  # tool executed through the backend
    assert data["audio"]["bytes"] > 0
    dup = client.post("/api/voice/command", files={"audio": ("a.wav", wav, "audio/wav")})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_AUDIO"


def _collect(ws, until):
    events = []
    while True:
        ev = ws.receive_json()
        events.append(ev)
        if ev["type"] in until:
            return events


def test_ws_chat_streams_response(client):
    with client.websocket_connect("/ws/chat") as ws:
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({"type": "message", "message": "Tell me a story"})
        events = _collect(ws, {"completed", "error"})
    types = [e["type"] for e in events]
    assert types[0] == "message_received"
    assert "thinking" in types and "response_delta" in types
    final = events[-1]
    assert final["type"] == "completed" and final["response"].strip() == "Hello from mock LYRA."
    assert all("timestamp" in e for e in events)


def test_ws_chat_reports_task_progress(client, home_dir):
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()
        ws.send_json({"type": "message", "message": "create a folder called WsDemo on my desktop"})
        events = _collect(ws, {"completed", "error"})
    types = [e["type"] for e in events]
    for expected in ("task_started", "tool_selected", "tool_executing", "tool_result", "verifying", "completed"):
        assert expected in types, expected
    assert events[-1]["task"]["status"] == "completed"
    assert (home_dir / "Desktop" / "WsDemo").is_dir()


def test_ws_chat_rejects_bad_frames(client):
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()
        ws.send_text("not json")
        assert ws.receive_json()["error"]["code"] == "BAD_MESSAGE"
        ws.send_json({"type": "message", "message": "   "})
        assert ws.receive_json()["error"]["code"] == "VALIDATION_ERROR"


def test_ws_events_broadcasts_task_updates(client):
    with client.websocket_connect("/ws/events") as ws:
        assert ws.receive_json()["type"] == "connected"
        client.post("/api/chat", json={"message": "what time is it"})
        statuses = []
        while "completed" not in statuses:
            ev = ws.receive_json()
            assert ev["type"] == "task_update"
            statuses.append(ev["status"])
    assert statuses[-1] == "completed" and "running" in statuses


def test_ws_voice_round_trip(client):
    with client.websocket_connect("/ws/voice") as ws:
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({"type": "start", "speak": True})
        ws.receive_json()  # voice_status idle
        ws.send_bytes(make_wav(seed=3))
        events = _collect(ws, {"audio", "error"})
    types = [e["type"] for e in events]
    assert "transcript" in types and "response" in types and types[-1] == "audio"
    assert any(e.get("state") == "thinking" for e in events if e["type"] == "voice_status")


def test_ws_chat_cancel_stops_response(client, mock_provider):
    mock_provider.delay = 0.3
    with client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()
        ws.send_json({"type": "message", "message": "Write a long essay"})
        seen = []
        while True:
            ev = ws.receive_json()
            seen.append(ev["type"])
            if ev["type"] in ("thinking", "response_start"):
                ws.send_json({"type": "cancel"})
            if ev["type"] in ("cancelled", "completed"):
                break
    assert seen[-1] == "cancelled"


def test_cancel_running_background_task(client, mock_provider):
    import time
    mock_provider.delay = 0.3  # generate() sleeps ~3s
    task_id = client.post("/api/tasks", json={"command": "Summarise the history of Rome"}).json()["data"]["id"]
    for _ in range(100):
        if client.get(f"/api/tasks/{task_id}").json()["data"]["status"] == "planning":
            break
        time.sleep(0.02)
    r = client.post(f"/api/tasks/{task_id}/cancel")
    assert r.status_code == 200 and r.json()["data"]["status"] == "cancelled"
    time.sleep(0.1)
    assert client.get(f"/api/tasks/{task_id}").json()["data"]["status"] == "cancelled"
