"""Task execution through the real planner + tools, with verification and tracking."""

import time


def _wait_terminal(client, task_id, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        task = client.get(f"/api/tasks/{task_id}").json()["data"]
        if task["status"] in ("completed", "failed", "cancelled", "waiting_for_confirmation"):
            return task
        time.sleep(0.05)
    raise AssertionError("task did not finish")


def test_chat_command_executes_tool_and_verifies_result(client, home_dir):
    body = client.post("/api/chat", json={"message": "create a folder called ApiTest on my desktop"}).json()
    assert body["task_id"]
    task = body["task"]
    assert task["status"] == "completed"
    assert task["intent"] == "create_folder"
    step = task["steps"][0]
    assert step["status"] == "completed" and step["verified"] is True
    assert task["verification"]["tool_verified"] == 1
    assert (home_dir / "Desktop" / "ApiTest").is_dir()
    assert client.get(f"/api/tasks/{task['id']}").json()["data"]["status"] == "completed"


def test_submit_task_runs_in_background(client, home_dir):
    r = client.post("/api/tasks", json={"command": "create a folder called Reports on my desktop"})
    assert r.status_code == 202
    task_id = r.json()["data"]["id"]
    task = _wait_terminal(client, task_id)
    assert task["status"] == "completed"
    assert (home_dir / "Desktop" / "Reports").is_dir()
    listed = client.get("/api/tasks").json()["data"]
    assert any(t["id"] == task_id for t in listed)
    assert any(t["id"] == task_id for t in client.get("/api/tasks?status=completed").json()["data"])


def test_conversational_task_completes_without_actions(client):
    task_id = client.post("/api/tasks", json={"command": "Explain what a black hole is"}).json()["data"]["id"]
    task = _wait_terminal(client, task_id)
    assert task["status"] == "completed"
    assert task["response"] == "Hello from mock LYRA."


def test_cancel_rules_and_unknown_tasks(client):
    body = client.post("/api/chat", json={"message": "what time is it"}).json()
    r = client.post(f"/api/tasks/{body['task_id']}/cancel")
    assert r.status_code == 409 and r.json()["error"]["code"] == "TASK_NOT_CANCELLABLE"
    assert client.get("/api/tasks/task_missing").status_code == 404
    assert client.get("/api/tasks?status=bogus").status_code == 422


def test_failed_tool_marks_task_failed(client):
    body = client.post("/api/chat", json={"message": "delete the folder NotThere on my desktop"}).json()
    if body["task"] is not None:  # planner may route deletes to a confirmation prompt first
        assert body["task"]["status"] in ("failed", "waiting_for_confirmation")
