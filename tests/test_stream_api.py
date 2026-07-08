from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from server.app import app, format_sse, parse_last_event_id
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


def read_sse_event(response, wanted_event="packet", max_lines=100):
    current = {}
    data_lines = []
    for raw_line in response.iter_lines():
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        if line == "":
            if current or data_lines:
                current["data"] = "\n".join(data_lines)
                if current.get("event") == wanted_event:
                    return current
                current = {}
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("id:"):
            current["id"] = line.removeprefix("id:").strip()
        elif line.startswith("event:"):
            current["event"] = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
        max_lines -= 1
        if max_lines <= 0:
            break
    raise AssertionError(f"SSE event not found: {wanted_event}")


def test_notify_publishes_sse_event_row_shape(tmp_path):
    client = configure(tmp_path)
    queue = app.state.bus.subscribe()
    try:
        packet = load("notify_done.json")
        response = client.post("/api/notify", json=packet)
        assert response.status_code == 201
        event = queue.get_nowait()
        assert event["event_id"] == response.json()["event_id"]
        assert event["event_type"] == "packet"
        assert event["task_id"] == packet["task_id"]
        assert event["payload"]["event_id"] == response.json()["event_id"]
    finally:
        app.state.bus.unsubscribe(queue)


def test_stream_backlog_replays_packet_event(tmp_path):
    client = configure(tmp_path)
    packet = load("notify_done.json")
    assert client.post("/api/notify", json=packet).status_code == 201
    with client.stream("GET", "/api/stream?last_event_id=0") as response:
        assert response.status_code == 200
        event = read_sse_event(response)
    data = json.loads(event["data"])
    assert event["id"] == "1"
    assert event["event"] == "packet"
    assert data["task_id"] == packet["task_id"]
    assert data["event_id"] == 1


def test_initial_connection_uses_max_event_id_cursor(tmp_path):
    client = configure(tmp_path)
    assert client.post("/api/notify", json=load("notify_done.json")).status_code == 201
    assert app.state.store.get_max_event_id() == 1
    assert parse_last_event_id(None, None) is None


def test_last_event_id_header_takes_precedence(tmp_path):
    client = configure(tmp_path)
    first = load("notify_done.json")
    second = load("notify_failed.json")
    assert client.post("/api/notify", json=first).status_code == 201
    assert client.post("/api/notify", json=second).status_code == 201
    with client.stream("GET", "/api/stream?last_event_id=0", headers={"Last-Event-ID": "1"}) as response:
        assert response.status_code == 200
        event = read_sse_event(response)
    data = json.loads(event["data"])
    assert event["id"] == "2"
    assert data["task_id"] == second["task_id"]
    assert data["event_id"] == 2


def test_stream_rejects_invalid_last_event_id(tmp_path):
    client = configure(tmp_path)
    response = client.get("/api/stream?last_event_id=-1")
    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "validation_error"


def test_stream_token_auth(tmp_path):
    client = configure(tmp_path, token="secret")
    assert client.get("/api/stream?last_event_id=0").status_code == 401
    with client.stream("GET", "/api/stream?last_event_id=0&token=secret") as response:
        assert response.status_code == 200
    with client.stream("GET", "/api/stream?last_event_id=0", headers={"Authorization": "Bearer secret"}) as response:
        assert response.status_code == 200


def test_format_sse_adds_packet_event_id():
    event = {
        "event_id": 42,
        "event_type": "packet",
        "task_id": "task-1",
        "created_at": "2026-07-07T00:00:00+00:00",
        "payload": {"protocol": "macp", "task_id": "task-1"},
    }
    rendered = format_sse(event)
    assert rendered.startswith("id: 42\nevent: packet\ndata: ")
    assert rendered.endswith("\n\n")
    data = json.loads(rendered.split("data: ", 1)[1])
    assert data["event_id"] == 42
