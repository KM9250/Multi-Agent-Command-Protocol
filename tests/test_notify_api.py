from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from server.app import app
from server.event_bus import EventBus
from server.store import Store

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


def configure(tmp_path, token=None):
    app.state.store = Store(str(tmp_path / "macp.sqlite3"), str(tmp_path / "audit.jsonl"))
    app.state.bus = EventBus()
    app.state.settings = type("S", (), {"token": token})()
    return TestClient(app)


def test_notify_and_get_tasks(tmp_path):
    client = configure(tmp_path)
    r = client.post("/api/notify", json=load("notify_done.json"))
    assert r.status_code == 201
    body = r.json()
    assert body["mood_computed"] == "caution"
    listed = client.get("/api/tasks").json()["tasks"]
    assert len(listed) == 1
    detail = client.get(f"/api/tasks/{body['task_id']}").json()
    assert detail["task"]["task_id"] == body["task_id"]
    assert detail["events"][0]["payload"]["summary"] == load("notify_done.json")["summary"]


def test_same_task_upsert_and_events(tmp_path):
    client = configure(tmp_path)
    first = load("notify_done.json"); first["status"] = "running"
    second = load("notify_done.json"); second["status"] = "done"
    assert client.post("/api/notify", json=first).status_code == 201
    assert client.post("/api/notify", json=second).status_code == 201
    detail = client.get(f"/api/tasks/{second['task_id']}").json()
    assert detail["task"]["status"] == "done"
    assert len(detail["events"]) == 2


def test_invalid_packet_error_shape(tmp_path):
    client = configure(tmp_path)
    data = load("notify_done.json"); data["evaluation"]["confidence"] = 1.5
    r = client.post("/api/notify", json=data)
    assert r.status_code == 422
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["fields"]


def test_token_auth(tmp_path):
    client = configure(tmp_path, token="secret")
    assert client.post("/api/notify", json=load("notify_done.json")).status_code == 401
    assert client.get("/api/tasks").status_code == 401
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/notify", json=load("notify_done.json"), headers={"Authorization": "Bearer secret"}).status_code == 201
    assert client.get("/api/tasks", headers={"X-MACP-Token": "secret"}).status_code == 200


def test_handoff(tmp_path):
    client = configure(tmp_path)
    r = client.post("/api/handoff", json=load("handoff_agent.json"))
    assert r.status_code == 201
    detail = client.get(f"/api/tasks/{load('handoff_agent.json')['task_id']}").json()
    assert detail["handoffs"][0]["state"] == "pending"


def test_jsonl_raw_packet(tmp_path):
    client = configure(tmp_path)
    raw = load("notify_done.json")
    assert client.post("/api/notify", json=raw).status_code == 201
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == raw


def test_task_filters(tmp_path):
    client = configure(tmp_path)
    done = load("notify_done.json")
    failed = load("notify_failed.json")
    client.post("/api/notify", json=done)
    client.post("/api/notify", json=failed)
    tasks = client.get("/api/tasks?status=done&acknowledged=false").json()["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == done["task_id"]
