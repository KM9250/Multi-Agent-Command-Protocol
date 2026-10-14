from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import threading

import pytest
from fastapi import Request

from fastapi.testclient import TestClient

from server.app import app, get_store
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


def keyed_packet(name="notify_done.json"):
    return {**load(name), "producer_id": "map-coordination",
            "producer_event_id": "map.notification.v1:" + "a" * 64}


def counts(store):
    return tuple(store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                 for table in ("events", "tasks", "notification_idempotency", "handoffs"))


def test_replays_preserve_every_side_effect(tmp_path):
    client = configure(tmp_path)
    queue = app.state.bus.subscribe()
    packet = keyed_packet()
    first = client.post("/api/notify", json=packet)
    assert first.status_code == 201
    assert first.json()["idempotent_replay"] is False
    before = app.state.store.get_task(packet["task_id"])
    audit = (tmp_path / "audit.jsonl").read_bytes()
    for _ in range(5):
        replay = client.post("/api/notify", json=packet)
        assert replay.status_code == 200
        assert replay.json() == {**first.json(), "idempotent_replay": True}
    assert counts(app.state.store) == (1, 1, 1, 0)
    assert app.state.store.get_task(packet["task_id"]) == before
    assert (tmp_path / "audit.jsonl").read_bytes() == audit
    assert len(audit.splitlines()) == 1
    assert queue.qsize() == 1
    assert queue.get_nowait()["event_id"] == first.json()["event_id"]


@pytest.mark.parametrize("changed", [
    {"summary": "different"}, {"task_id": "different"}, {"status": "running"},
    {"created_at": "2026-07-08T00:00:00Z"}, {"metadata": {"kind": "different"}},
])
def test_conflict_leaves_no_side_effects(tmp_path, changed):
    client = configure(tmp_path)
    packet = keyed_packet()
    assert client.post("/api/notify", json=packet).status_code == 201
    before = app.state.store.get_task(packet["task_id"])
    audit = (tmp_path / "audit.jsonl").read_bytes()
    queue = app.state.bus.subscribe()
    response = client.post("/api/notify", json={**packet, **changed})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"
    assert counts(app.state.store) == (1, 1, 1, 0)
    assert app.state.store.get_task(packet["task_id"]) == before
    assert (tmp_path / "audit.jsonl").read_bytes() == audit
    assert queue.empty()


def test_canonical_json_and_existing_normalization(tmp_path, monkeypatch):
    client = configure(tmp_path)
    packet = keyed_packet()
    packet["metadata"] = {"z": 1, "a": {"y": 2, "b": "日本語"}}
    packet["command"] = "/vega-spec"
    packet.pop("command_alias", None)
    packet.pop("priority", None)
    packet.pop("to", None)
    first = client.post("/api/notify", json=packet)
    reordered = copy.deepcopy(packet)
    reordered.update(command="/spec", command_alias="/vega-spec", priority="normal", to={"type": "broadcast"},
                     event_id=999, received_at="ignored", mood_computed="ignored")
    # Server-derived mood changes must not change the digest or replay response.
    monkeypatch.setattr("server.schemas.compute_mood", lambda _: "bad")
    response = client.post("/api/notify", content=json.dumps(reordered, sort_keys=True, indent=4),
                           headers={"Content-Type": "application/json"})
    assert first.status_code == 201
    assert response.status_code == 200
    assert response.json() == {**first.json(), "idempotent_replay": True}


@pytest.mark.parametrize("field", ["producer_id", "producer_event_id"])
def test_distinct_producer_scope_or_event(tmp_path, field):
    client = configure(tmp_path)
    packet = keyed_packet()
    first = client.post("/api/notify", json=packet)
    second = client.post("/api/notify", json={**packet, field: "different"})
    assert first.status_code == second.status_code == 201
    assert first.json()["event_id"] != second.json()["event_id"]
    assert counts(app.state.store) == (2, 1, 2, 0)


def test_old_replay_does_not_revert_newer_task_state(tmp_path):
    client = configure(tmp_path)
    running = {**keyed_packet(), "status": "running"}
    first = client.post("/api/notify", json=running)
    done = {**running, "status": "done", "producer_event_id": "done-event"}
    assert client.post("/api/notify", json=done).status_code == 201
    before = app.state.store.get_task(done["task_id"])
    assert before["task"]["status"] == "done"
    assert client.post("/api/notify", json=running).json()["event_id"] == first.json()["event_id"]
    assert app.state.store.get_task(done["task_id"]) == before


def test_reconnect_preserves_idempotency(tmp_path):
    client = configure(tmp_path)
    packet = keyed_packet()
    first = client.post("/api/notify", json=packet)
    app.state.store._conn.close()
    client = configure(tmp_path)
    response = client.post("/api/notify", json=packet)
    assert response.status_code == 200
    assert response.json()["event_id"] == first.json()["event_id"]
    assert counts(app.state.store) == (1, 1, 1, 0)
    assert len((tmp_path / "audit.jsonl").read_text().splitlines()) == 1
    assert client.post("/api/notify", json={**packet, "summary": "changed"}).status_code == 409


@pytest.mark.parametrize("field", ["producer_id", "producer_event_id"])
@pytest.mark.parametrize("value", ["", " ", "a b", "\ta", "a\n", "a\r", "a\x00", "a\x7f", "a\u0085", "a\u200b", "日本語", "a/../b", "x" * 257, 42, True, [], {}, None])
def test_invalid_keys_rejected(tmp_path, field, value):
    client = configure(tmp_path)
    packet = {**keyed_packet(), field: value}
    assert client.post("/api/notify", json=packet).status_code == 422
    assert counts(app.state.store) == (0, 0, 0, 0)
    assert not (tmp_path / "audit.jsonl").exists()


@pytest.mark.parametrize("field", ["producer_id", "producer_event_id"])
def test_keys_must_be_paired(tmp_path, field):
    client = configure(tmp_path)
    packet = keyed_packet()
    del packet[field]
    assert client.post("/api/notify", json=packet).status_code == 422


def test_key_length_boundaries(tmp_path):
    client = configure(tmp_path)
    packet = {**keyed_packet(), "producer_id": "x" * 128, "producer_event_id": "y" * 256}
    assert client.post("/api/notify", json=packet).status_code == 201
    packet["producer_id"] += "x"
    assert client.post("/api/notify", json=packet).status_code == 422
    packet.update(producer_id="x", producer_event_id="y")
    assert client.post("/api/notify", json=packet).status_code == 201


@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_posts_use_independent_db_connections(tmp_path, monkeypatch, conflicting):
    configure(tmp_path)
    stores = [app.state.store, Store(str(tmp_path / "macp.sqlite3"), str(tmp_path / "audit.jsonl"))]
    barrier = threading.Barrier(2)
    for store in stores:
        original = store.append_packet
        def append(normalized, raw, original=original):
            barrier.wait(timeout=5)
            return original(normalized, raw)
        monkeypatch.setattr(store, "append_packet", append)

    def independent_store(request: Request):
        return stores[int(request.headers["x-test-store"])]
    monkeypatch.setitem(app.dependency_overrides, get_store, independent_store)
    packet = keyed_packet()
    packets = [packet, {**packet, "summary": "different"} if conflicting else packet]
    queue = app.state.bus.subscribe()

    def post(index):
        with TestClient(app) as client:
            return client.post("/api/notify", json=packets[index], headers={"x-test-store": str(index)})

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(post, range(2)))
        assert sorted(r.status_code for r in responses) == ([201, 409] if conflicting else [200, 201])
        if not conflicting:
            assert responses[0].json()["event_id"] == responses[1].json()["event_id"]
        assert counts(stores[0]) == (1, 1, 1, 0)
        assert len((tmp_path / "audit.jsonl").read_text().splitlines()) == 1
        assert queue.qsize() == 1
    finally:
        stores[1]._conn.close()


@pytest.mark.parametrize("table", ["tasks", "notification_idempotency"])
def test_failed_transaction_rolls_back_all_records(tmp_path, table):
    configure(tmp_path)
    client = TestClient(app, raise_server_exceptions=False)
    conn = app.state.store._conn
    conn.execute(f"CREATE TRIGGER fail_insert AFTER INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    queue = app.state.bus.subscribe()
    packet = keyed_packet()
    assert client.post("/api/notify", json=packet).status_code == 500
    assert counts(app.state.store) == (0, 0, 0, 0)
    assert not (tmp_path / "audit.jsonl").exists()
    assert queue.empty()
    conn.execute("DROP TRIGGER fail_insert")
    assert client.post("/api/notify", json=packet).status_code == 201
    assert client.post("/api/notify", json=packet).status_code == 200
    assert counts(app.state.store) == (1, 1, 1, 0)


def test_upgrade_existing_database_and_unique_constraint(tmp_path):
    client = configure(tmp_path)
    old = load("notify_done.json")
    assert client.post("/api/notify", json=old).status_code == 201
    before = app.state.store.get_task(old["task_id"])
    app.state.store._conn.execute("DROP TABLE notification_idempotency")
    app.state.store._conn.close()
    client = configure(tmp_path)
    assert app.state.store.get_task(old["task_id"]) == before
    assert client.post("/api/notify", json=keyed_packet()).status_code == 201
    conn = app.state.store._conn
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("INSERT INTO notification_idempotency SELECT * FROM notification_idempotency")
    assert counts(app.state.store) == (2, 1, 1, 0)


def test_failed_key_insert_restores_existing_task_and_handoff(tmp_path):
    client = configure(tmp_path)
    packet = keyed_packet("handoff_agent.json")
    assert client.post("/api/handoff", json=packet).status_code == 201
    before = app.state.store.get_task(packet["task_id"])
    audit = (tmp_path / "audit.jsonl").read_bytes()
    queue = app.state.bus.subscribe()
    conn = app.state.store._conn
    conn.execute("""CREATE TRIGGER fail_key AFTER INSERT ON notification_idempotency
                    BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    changed = {**packet, "producer_event_id": "new", "status": "running", "summary": "new state"}
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post("/api/handoff", json=changed).status_code == 500
    assert app.state.store.get_task(packet["task_id"]) == before
    assert counts(app.state.store) == (1, 1, 1, 1)
    assert (tmp_path / "audit.jsonl").read_bytes() == audit
    assert queue.empty()
    conn.execute("DROP TRIGGER fail_key")
    assert client.post("/api/handoff", json=changed).status_code == 201
    assert counts(app.state.store) == (2, 1, 2, 1)


def test_key_does_not_bypass_authentication(tmp_path):
    client = configure(tmp_path, token="secret")
    packet = keyed_packet()
    assert client.post("/api/notify", json=packet).status_code == 401
    first = client.post("/api/notify", json=packet, headers={"Authorization": "Bearer secret"})
    assert first.status_code == 201
    assert client.post("/api/notify", json=packet).status_code == 401
    assert client.post("/api/notify", json=packet, headers={"X-MACP-Token": "wrong"}).status_code == 401
    assert client.post("/api/notify", json=packet, headers={"X-MACP-Token": "secret"}).status_code == 200
    assert counts(app.state.store) == (1, 1, 1, 0)


def test_handoff_idempotency_shared_with_notify(tmp_path):
    client = configure(tmp_path)
    packet = keyed_packet("handoff_agent.json")
    first = client.post("/api/handoff", json=packet)
    assert first.status_code == 201
    before = app.state.store.get_task(packet["task_id"])
    queue = app.state.bus.subscribe()
    for endpoint in ("/api/handoff", "/api/notify"):
        replay = client.post(endpoint, json=packet)
        assert replay.status_code == 200
        assert replay.json()["event_id"] == first.json()["event_id"]
        assert client.post(endpoint, json={**packet, "summary": "changed"}).status_code == 409
    assert app.state.store.get_task(packet["task_id"]) == before
    assert counts(app.state.store) == (1, 1, 1, 1)
    assert queue.empty()


@pytest.mark.parametrize("path", sorted((ROOT / "examples").glob("*.json")), ids=lambda p: p.name)
def test_existing_sample_posts(tmp_path, path):
    client = configure(tmp_path)
    packet = json.loads(path.read_text())
    response = client.post("/api/notify", json=packet)
    assert response.status_code == 201
    assert response.json()["task_id"] == packet["task_id"]
