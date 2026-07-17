from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from server.app import app
from server.event_bus import EventBus
from server.store import Store


def configure(tmp_path):
    app.state.store = Store(str(tmp_path / "macp.sqlite3"), str(tmp_path / "audit.jsonl"))
    app.state.bus = EventBus()
    app.state.settings = type("S", (), {"token": None})()
    return TestClient(app)


def test_root_serves_web_ui(tmp_path):
    client = configure(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "/api/tasks" in response.text
    assert "/api/stream" in response.text


def test_web_ui_uses_safe_text_rendering_and_cursor_storage():
    html = (Path(__file__).resolve().parents[1] / "clients" / "web" / "index.html").read_text(encoding="utf-8")
    assert "innerHTML" not in html
    assert "textContent" in html
    assert '"macp_token"' in html
    assert '"macp_last_event_id"' in html
    assert '"macp_unread_task_ids"' in html
    assert "storedLastEventId" in html
    assert "hasStoredCursor" in html
    assert "max_event_id" in html
