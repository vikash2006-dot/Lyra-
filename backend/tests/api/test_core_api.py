"""Health, system, settings, chat and sessions APIs."""

import json


def test_health_reports_real_service_state(client):
    body = client.get("/api/health").json()
    assert body["success"] is True
    data = body["data"]
    assert data["status"] == "ok"
    assert data["services"]["memory"] is True
    assert data["services"]["api_store"] is True
    assert data["configured_providers"] == ["mock"]


def test_system_status_lists_tools_and_never_exposes_secrets(client, monkeypatch):
    data = client.get("/api/system/status").json()["data"]
    names = {t["name"] for t in data["tools"]}
    assert {"filesystem", "browser", "computer", "system", "time"} <= names
    providers = client.get("/api/settings/providers").json()["data"]
    settings = client.get("/api/settings").json()["data"]
    dump = json.dumps([data, providers, settings]).lower()
    assert "api_key" not in dump
    assert providers["providers"][0]["name"] == "mock"


def test_settings_offline_toggle_propagates(client):
    r = client.put("/api/settings", json={"offline_mode": True})
    assert r.json()["data"]["general"]["offline_mode"] is True
    assert client.get("/api/health").json()["data"]["offline_mode"] is True
    client.put("/api/settings", json={"offline_mode": False})


def test_chat_returns_reply_and_persists_session(client):
    r = client.post("/api/chat", json={"message": "Tell me something interesting"})
    body = r.json()
    assert r.status_code == 200 and body["success"]
    assert body["response"] == "Hello from mock LYRA."
    sid = body["session_id"]
    msgs = client.get(f"/api/sessions/{sid}/messages").json()["data"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "Tell me something interesting"
    session = client.get(f"/api/sessions/{sid}").json()["data"]
    assert session["title"].startswith("Tell me something")

    # Context is maintained across turns in the same session.
    client.post("/api/chat", json={"message": "And another thing", "session_id": sid})
    assert len(client.get(f"/api/sessions/{sid}/messages").json()["data"]) == 4


def test_chat_validation_errors_use_standard_envelope(client):
    r = client.post("/api/chat", json={"message": ""})
    assert r.status_code == 422
    assert r.json()["success"] is False
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = client.post("/api/chat", json={"message": "hi", "session_id": "does-not-exist"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_provider_failure_is_reported_without_internal_details(client, mock_provider):
    mock_provider.fail = True
    body = client.post("/api/chat", json={"message": "Explain quantum computing"}).json()
    assert body["success"] is True
    assert "mock failure" not in body["response"]
    assert "provider" in body["response"].lower()


def test_session_crud(client):
    created = client.post("/api/sessions", json={"title": "Planning"}).json()["data"]
    sid = created["id"]
    assert any(s["id"] == sid for s in client.get("/api/sessions").json()["data"])
    renamed = client.patch(f"/api/sessions/{sid}", json={"title": "Trip planning"}).json()["data"]
    assert renamed["title"] == "Trip planning"
    assert client.delete(f"/api/sessions/{sid}").json()["success"]
    assert client.get(f"/api/sessions/{sid}").status_code == 404


def test_sessions_survive_restart_of_live_cache(client):
    sid = client.post("/api/chat", json={"message": "Remember this conversation"}).json()["session_id"]
    services = client.app.state.services
    services.sessions._live.clear()  # simulate a backend restart
    session = services.sessions.resolve(sid)
    assert [m.content for m in session.messages][0] == "Remember this conversation"


def test_unknown_route_and_method_errors(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
