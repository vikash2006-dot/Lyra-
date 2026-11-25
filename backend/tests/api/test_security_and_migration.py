"""Access token enforcement, WebSocket origin checks and legacy data migration."""

from dataclasses import replace
import sqlite3

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.migration import migrate_legacy_data
from app.main import create_app


def test_token_protects_api_but_not_health(server_config, client):
    factory_runtime = client.app.state.services.runtime
    app = create_app(replace(server_config, api_token="s3cret"),
                     runtime_factory=lambda c, n: factory_runtime, start_scheduler=False)
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
        r = c.get("/api/sessions")
        assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"
        assert c.get("/api/sessions", headers={"Authorization": "Bearer s3cret"}).status_code == 200
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/chat") as ws:
                ws.receive_json()
        with c.websocket_connect("/ws/chat?token=s3cret") as ws:
            assert ws.receive_json()["type"] == "connected"


def test_websocket_rejects_foreign_origin(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/chat", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()
    with client.websocket_connect("/ws/chat", headers={"origin": "http://localhost:5173"}) as ws:
        assert ws.receive_json()["type"] == "connected"


def test_cors_allows_frontend_origin_only(client):
    ok = client.options("/api/health", headers={"Origin": "http://localhost:5173",
                                                "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/api/health", headers={"Origin": "https://evil.example",
                                                 "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE memories (id TEXT, content TEXT)")
    conn.executemany("INSERT INTO memories VALUES (?, ?)", rows)
    conn.commit()
    conn.close()


def test_legacy_migration_is_verified_backed_up_and_repeatable(tmp_path):
    root, backend = tmp_path / "root", tmp_path / "root" / "backend"
    data = backend / "storage" / "data"
    backend.mkdir(parents=True)
    _make_db(root / "lyra_memory.db", [("1", "a"), ("2", "b")])
    (root / ".env").write_text("GEMINI_API_KEY=x\n")

    report = migrate_legacy_data(root, backend, data)
    assert set(report.migrated) == {"lyra_memory.db", ".env"} and not report.failed
    conn = sqlite3.connect(data / "lyra_memory.db")
    assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 2
    conn.close()
    assert not (root / "lyra_memory.db").exists()
    backups = list((backend / "storage" / "backups").glob("*/lyra_memory.db"))
    assert len(backups) == 1
    assert (backend / ".env").read_text() == "GEMINI_API_KEY=x\n"

    # Re-running is a no-op, and never overwrites existing backend data.
    _make_db(root / "lyra_memory.db", [("3", "c")])
    again = migrate_legacy_data(root, backend, data)
    assert again.skipped == ["lyra_memory.db"] and not again.migrated
    assert (root / "lyra_memory.db").exists()
