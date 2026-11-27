"""Personality, preferences and audio-event behaviour through the API."""

from tests.unit.test_personality_layer import _clip


def test_greeting_gets_greeting_without_ai_call(client, mock_provider):
    before = len(mock_provider.requests)
    body = client.post("/api/chat", json={"message": "Hello, Lyra."}).json()
    assert body["response"].startswith(("Hello", "Hi", "Hey"))
    assert "see you" not in body["response"].lower()
    assert len(mock_provider.requests) == before  # answered by the personality layer
    bye = client.post("/api/chat", json={"message": "Goodbye Lyra", "session_id": body["session_id"]}).json()
    assert any(w in bye["response"].lower() for w in ("see you", "goodbye", "good night"))


def test_emotional_guidance_reaches_every_provider(client, mock_provider):
    client.post("/api/chat", json={"message": "Today was a terrible day."})
    system_prompt = mock_provider.requests[-1].system_prompt
    assert "sadness" in system_prompt and "not certain" in system_prompt
    assert "female" in system_prompt  # centralized personality


def test_emotional_awareness_can_be_disabled_and_persists(client, mock_provider):
    data = client.put("/api/settings", json={"emotional_awareness": False, "cough_detection": False}).json()["data"]
    assert data["assistant"]["emotional_awareness"] is False and data["assistant"]["cough_detection"] is False
    client.post("/api/chat", json={"message": "Today was a terrible day."})
    assert "sadness" not in mock_provider.requests[-1].system_prompt
    assert client.app.state.services.store.get_preferences()["emotional_awareness"] is False


def test_rejects_unknown_voice(client):
    r = client.put("/api/settings", json={"voice": "Definitely Not A Voice"})
    assert r.status_code == 422


def test_voice_list_puts_female_voices_first(client):
    voices = client.get("/api/voice/voices").json()["data"]
    if voices:  # macOS only
        assert voices[0]["female"] is True


def test_cough_only_clip_gets_gentle_check_once(client):
    services = client.app.state.services
    services.voice.stt.set_transcription_text("")  # mock STT hears no words, only the cough
    clip = _clip([("silence", 0.5), ("cough", 0.3), ("silence", 0.5)])
    with client.websocket_connect("/ws/voice") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "speak": False})
        ws.receive_json()
        ws.send_bytes(clip)
        events = []
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] == "voice_status" and ev["state"] == "idle":
                break
    transcript = next(e for e in events if e["type"] == "transcript")
    assert transcript["audio_events"][0]["type"] == "cough"
    response = next(e for e in events if e["type"] == "response")
    text = response["text"].lower()
    assert "cough" in text and ("okay" in text or "alright" in text)
    assert "sick" not in text and "ill" not in text.split()
    # Cooldown: a second cough soon after is not asked about again.
    assert services.voice.analyze_audio(clip, None) == []
