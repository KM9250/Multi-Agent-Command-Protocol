from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import app


def test_web_index_served():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "MACP Notify" in body
    assert "/api/tasks" in body
    assert "/api/stream" in body


def test_web_index_security_and_storage_markers():
    client = TestClient(app)
    body = client.get("/").text
    assert "innerHTML" not in body
    assert "textContent" in body
    assert "macp_token" in body
    assert "macp_last_event_id" in body
    assert "macp_unread_task_ids" in body
    assert "EventSource" in body
    assert "Authorization" in body
    assert "Bearer" in body
    assert "last_event_id" in body
    assert "token" in body


def test_health_response_unchanged():
    client = TestClient(app)
    assert client.get("/api/health").json() == {"status": "ok"}
