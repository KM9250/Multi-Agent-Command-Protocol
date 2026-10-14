from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
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


def stream_response(path, headers=None, packet_count=1):
    """Exercise the real ASGI route, disconnecting after the expected frames.

    TestClient buffers response bodies until EOF, so it cannot consume an
    infinite SSE stream. This client signals http.disconnect while the stream
    is live and bounds the whole exchange, including failure cases.
    """
    async def collect():
        request = httpx.Request("GET", "http://testserver" + path, headers=headers)
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
                 "http_version": "1.1", "method": "GET", "scheme": "http",
                 "path": request.url.path, "raw_path": request.url.raw_path.split(b"?")[0],
                 "query_string": request.url.query,
                 "headers": [(name.lower(), value) for name, value in request.headers.raw],
                 "server": ("testserver", 80), "client": ("testclient", 123)}
        disconnect = asyncio.Event()
        chunks = []
        status_code = None
        response_headers = []

        async def receive():
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            nonlocal status_code, response_headers
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = message["headers"]
                if packet_count == 0:
                    disconnect.set()
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if b"".join(chunks).count(b"event: packet\n") >= packet_count or not message.get("more_body"):
                    disconnect.set()

        await asyncio.wait_for(app(scope, receive, send), timeout=3)
        return httpx.Response(status_code, headers=response_headers, content=b"".join(chunks))

    return asyncio.run(collect())


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
    response = stream_response("/api/stream?last_event_id=0")
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
    response = stream_response("/api/stream?last_event_id=0", headers={"Last-Event-ID": "1"})
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
    response = stream_response("/api/stream?last_event_id=0&token=secret", packet_count=0)
    assert response.status_code == 200
    response = stream_response("/api/stream?last_event_id=0", headers={"Authorization": "Bearer secret"}, packet_count=0)
    assert response.status_code == 200


def test_last_event_id_backlog_contains_one_event_after_reposts(tmp_path):
    client = configure(tmp_path)
    first = client.post("/api/notify", json=load("notify_done.json")).json()
    packet = {**load("notify_failed.json"), "producer_id": "map-coordination", "producer_event_id": "stable-id"}
    created = client.post("/api/notify", json=packet)
    assert created.status_code == 201
    for _ in range(3):
        assert client.post("/api/notify", json=packet).status_code == 200
    response = stream_response("/api/stream", headers={"Last-Event-ID": str(first["event_id"])})
    event = read_sse_event(response)
    assert int(event["id"]) == created.json()["event_id"]
    assert len(app.state.store.get_events_after(first["event_id"])) == 1
    assert json.loads(event["data"])["producer_event_id"] == "stable-id"
    assert not app.state.bus.subscribers


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
