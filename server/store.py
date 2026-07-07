from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS events (
  event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id    TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload    TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY, task_type TEXT, intent TEXT, command TEXT, status TEXT NOT NULL,
  priority TEXT, summary TEXT, agent_id TEXT, mood TEXT, mood_computed TEXT,
  requires_user_action INTEGER DEFAULT 0, latest_packet TEXT NOT NULL,
  acknowledged INTEGER NOT NULL DEFAULT 0, acknowledged_at TEXT, retry_requested_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS handoffs (
  handoff_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, requested_command TEXT, from_agent TEXT,
  to_agent TEXT, return_to TEXT, hop INTEGER, max_hops INTEGER, state TEXT NOT NULL,
  payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: str, jsonl_path: str | None):
        self.db_path = db_path
        self.jsonl_path = jsonl_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        if jsonl_path:
            Path(jsonl_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(DDL)

    def append_packet(self, normalized: dict, raw: dict) -> int:
        payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        task_id = normalized["task_id"]
        now = normalized["received_at"]
        ev = normalized.get("evaluation") or {}
        agent = normalized.get("from") or {}
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            try:
                cur.execute(
                    "INSERT INTO events(task_id,event_type,payload,created_at) VALUES(?,?,?,?)",
                    (task_id, "packet", payload, now),
                )
                event_id = int(cur.lastrowid)
                cur.execute(
                    """
                    INSERT INTO tasks(task_id,task_type,intent,command,status,priority,summary,agent_id,mood,
                      mood_computed,requires_user_action,latest_packet,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(task_id) DO UPDATE SET
                      task_type=excluded.task_type,intent=excluded.intent,command=excluded.command,
                      status=excluded.status,priority=excluded.priority,summary=excluded.summary,
                      agent_id=excluded.agent_id,mood=excluded.mood,mood_computed=excluded.mood_computed,
                      requires_user_action=excluded.requires_user_action,latest_packet=excluded.latest_packet,
                      updated_at=excluded.updated_at
                    """,
                    (task_id, normalized.get("task_type"), normalized.get("intent"), normalized.get("command"),
                     normalized.get("status"), normalized.get("priority"), normalized.get("summary"),
                     agent.get("agent_id"), ev.get("mood"), normalized.get("mood_computed"),
                     1 if ev.get("requires_user_action") else 0, payload, normalized.get("created_at"), now),
                )
                if normalized.get("intent") == "handoff_agent" and normalized.get("handoff"):
                    h = normalized["handoff"]
                    to = normalized.get("to") or {}
                    cur.execute(
                        """
                        INSERT INTO handoffs(handoff_id,task_id,requested_command,from_agent,to_agent,return_to,hop,max_hops,state,payload,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(handoff_id) DO UPDATE SET task_id=excluded.task_id,requested_command=excluded.requested_command,
                          from_agent=excluded.from_agent,to_agent=excluded.to_agent,return_to=excluded.return_to,hop=excluded.hop,
                          max_hops=excluded.max_hops,state=excluded.state,payload=excluded.payload,updated_at=excluded.updated_at
                        """,
                        (h["handoff_id"], task_id, h.get("requested_command"), agent.get("agent_id"), to.get("target"),
                         h.get("return_to"), h.get("hop"), h.get("max_hops"), "pending", payload, now, now),
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        self._append_jsonl(raw)
        return event_id

    def _append_jsonl(self, raw: dict) -> None:
        if not self.jsonl_path:
            return
        try:
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(raw, ensure_ascii=False, separators=(",", ":")) + "\n")
        except Exception as exc:
            logger.warning("JSONL append failed: %s", exc)

    def get_events_after(self, last_event_id: int, limit: int = 500) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE event_id>? ORDER BY event_id LIMIT ?", (last_event_id, limit)
        ).fetchall()
        return [self._event(row) for row in rows]

    def list_tasks(self, *, status=None, task_type=None, intent=None, acknowledged=None, limit=50, offset=0) -> list[dict]:
        clauses, params = [], []
        for col, val in (("status", status), ("task_type", task_type), ("intent", intent)):
            if val is not None:
                clauses.append(f"{col}=?"); params.append(val)
        if acknowledged is not None:
            clauses.append("acknowledged=?"); params.append(1 if acknowledged else 0)
        sql = "SELECT * FROM tasks" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        rows = self._conn.execute(sql, (*params, limit, offset)).fetchall()
        return [self._task(row) for row in rows]

    def get_task(self, task_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return None
        events = self._conn.execute("SELECT * FROM events WHERE task_id=? ORDER BY event_id", (task_id,)).fetchall()
        handoffs = self._conn.execute("SELECT * FROM handoffs WHERE task_id=? ORDER BY created_at", (task_id,)).fetchall()
        return {"task": self._task(row), "events": [self._event(e) for e in events], "handoffs": [self._handoff(h) for h in handoffs]}

    def _task(self, row):
        d = dict(row); d["latest_packet"] = json.loads(d["latest_packet"]); d["acknowledged"] = bool(d["acknowledged"]); d["requires_user_action"] = bool(d["requires_user_action"]); return d
    def _event(self, row):
        d = dict(row); d["payload"] = json.loads(d["payload"]); return d
    def _handoff(self, row):
        d = dict(row); d["payload"] = json.loads(d["payload"]); return d
    def ack(self, task_id: str):
        raise NotImplementedError
    def mark_retry(self, task_id: str):
        raise NotImplementedError
