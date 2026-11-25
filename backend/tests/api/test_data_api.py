"""Memory, documents and learning APIs."""


def test_memory_crud_and_search(client):
    created = client.post("/api/memory", json={"content": "My favourite editor is VS Code", "type": "preference"})
    assert created.status_code == 201
    mem = created.json()["data"]
    assert mem["type"] == "preference"
    mid = mem["id"]
    assert client.get(f"/api/memory/{mid}").json()["data"]["content"] == "My favourite editor is VS Code"
    found = client.get("/api/memory", params={"q": "editor"}).json()["data"]
    assert [m["id"] for m in found] == [mid]
    upd = client.put(f"/api/memory/{mid}", json={"content": "My favourite editor is Neovim"}).json()["data"]
    assert upd["content"].endswith("Neovim")
    assert "preference" in client.get("/api/memory/types").json()["data"]
    assert client.delete(f"/api/memory/{mid}").json()["success"]
    assert client.get(f"/api/memory/{mid}").status_code == 404


def test_memory_policy_rejections_are_clean(client):
    r = client.post("/api/memory", json={"content": "my password is hunter2", "type": "fact"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "MEMORY_REJECTED"
    r = client.post("/api/memory", json={"content": "Something", "type": "not_a_type"})
    assert r.status_code == 422


def test_document_upload_analyze_delete(client):
    resume = b"Built a REST API project in Python with FastAPI and PostgreSQL. Uses git and docker daily."
    r = client.post("/api/documents/upload", files={"file": ("../../etc/resume.txt", resume, "text/plain")})
    assert r.status_code == 201
    doc = r.json()["data"]
    assert doc["filename"] == "resume.txt" and "stored_path" not in doc
    did = doc["id"]
    assert any(d["id"] == did for d in client.get("/api/documents").json()["data"])

    analysis = client.post(f"/api/documents/{did}/analyze", json={"mode": "resume"}).json()["data"]["analysis"]
    assert analysis["mode"] == "resume"
    summary = client.post(f"/api/documents/{did}/analyze", json={"mode": "summary"}).json()["data"]["analysis"]
    assert summary["summary"] == "Hello from mock LYRA."
    assert client.get(f"/api/documents/{did}").json()["data"]["analysis"]["mode"] == "summary"

    assert client.delete(f"/api/documents/{did}").json()["success"]
    assert client.get(f"/api/documents/{did}").status_code == 404


def test_document_validation(client):
    r = client.post("/api/documents/upload", files={"file": ("run.sh", b"rm -rf /", "text/x-sh")})
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    r = client.post("/api/documents/upload", files={"file": ("big.txt", b"a" * (1024 * 1024 + 10), "text/plain")})
    assert r.status_code == 413
    r = client.post("/api/documents/upload", files={"file": ("empty.txt", b"", "text/plain")})
    assert r.status_code == 422


def test_learning_profile_skills_plan_progress(client):
    profile = client.get("/api/learning/profile").json()["data"]
    assert profile["learner_id"] == "default_user"
    r = client.post("/api/learning/plan", json={"duration_weeks": 4})
    assert r.status_code == 422 and r.json()["error"]["code"] == "TARGET_ROLE_REQUIRED"

    upd = client.put("/api/learning/profile", json={"target_role": "Backend Developer", "weekly_learning_hours": 6})
    assert upd.json()["data"]["target_role"] == "Backend Developer"
    assert client.post("/api/learning/skills", json={"skill": "Python", "level": "intermediate"}).status_code == 201
    skills = client.get("/api/learning/skills").json()["data"]
    assert any(s["skill"] == "Python" for s in skills["skills"])

    plan = client.post("/api/learning/plan", json={"duration_weeks": 2})
    assert plan.status_code == 201
    got = client.get("/api/learning/plan").json()["data"]
    assert got["plan"] is not None and got["plan"]["target_role"] == "Backend Developer"
    assert client.get("/api/learning/progress").json()["success"]
    assert isinstance(client.get("/api/learning/gaps").json()["data"], list)
    assert client.post("/api/learning/practice", json={}).status_code == 201
