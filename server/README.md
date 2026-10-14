# MACP Notify Server

## Setup

```bash
pip install -r requirements.txt
uvicorn server.app:app --host 127.0.0.1 --port 8765
```

## Environment

- `MACP_HOST` / `MACP_PORT`: bind host and port (`127.0.0.1:8765` by default).
- `MACP_DB_PATH`: SQLite path (`./data/macp.sqlite3`). Parent directories are created automatically.
- `MACP_JSONL_PATH`: raw packet audit log (`./data/audit.jsonl`). Set to an empty string to disable.
- `MACP_TOKEN`: optional bearer or `X-MACP-Token` token. When set, all endpoints except `/api/health` require it.
- `MACP_CORS_ORIGINS`: comma-separated browser origins.

## Examples

```bash
curl -s http://127.0.0.1:8765/api/health
curl -s -X POST http://127.0.0.1:8765/api/notify \
  -H "Content-Type: application/json" \
  -d @examples/notify_done.json
curl -s http://127.0.0.1:8765/api/tasks | python -m json.tool
```

With a token:

```bash
curl -s -H "Authorization: Bearer $MACP_TOKEN" http://127.0.0.1:8765/api/tasks
curl -s -H "X-MACP-Token: $MACP_TOKEN" http://127.0.0.1:8765/api/tasks
```

## Idempotent notification intake

Optionally include both `producer_id` (1–128 characters) and `producer_event_id`
(1–256 characters). Keys are case-sensitive ASCII letters, digits, `.`, `_`, `:`,
or `-`; empty strings, whitespace, controls, nulls, and unpaired keys return 422.
For MAP, use `map-coordination` and the stable COORD-4A `notificationId`.

```bash
python -c 'import json; p=json.load(open("examples/notify_done.json")); p.update(producer_id="map-coordination", producer_event_id="demo-notification-001"); print(json.dumps(p))' > /tmp/macp-idempotent.json
curl -i -X POST http://127.0.0.1:8765/api/notify \
  -H "Content-Type: application/json" -d @/tmp/macp-idempotent.json
# Repeat this same POST: 200 and the original event_id, without another event.
```

- First POST: 201, `idempotent_replay: false`; one event, JSONL line, and SSE publish.
- Same key and normalized payload: 200, `idempotent_replay: true`; no writes or publish.
- Same key with changed content, including `created_at`: 409 `idempotency_conflict`.
- Without keys: existing behavior, including multiple updates to the same `task_id`.
- `/api/handoff` shares these optional semantics and retains its response fields.

The server hashes canonical normalized JSON with SHA-256, excluding server-added
fields. It adds `notification_idempotency` with a unique producer/event pair to
existing SQLite databases without deleting data. Events, task/handoff updates,
and the key record commit together; independent connections serialize writes.
Keep the original notification timestamp and payload on retries. Keys persist
across restarts and have no expiry. `producer_id` grants no permissions; existing
`MACP_TOKEN` authentication also applies to replays.

SQLite is authoritative. JSONL and live SSE happen after commit: a crash can omit
them, and retries do not repair those side effects. Stored events remain available
through SSE `Last-Event-ID` replay. The live bus remains process-local.

Validation and schema generation:

```bash
python scripts/generate_schema.py
python -m pytest -q
git diff --check
```

Pydantic is the source of truth for JSON Schema and the generated TypeScript
producer fields. See `docs/protocol.md` and `docs/transport.md` for the contract.

## SSE stream

Replay stored packet events from the beginning:

```bash
curl -N "http://127.0.0.1:8765/api/stream?last_event_id=0"
```

Replay events after a stored cursor with the `Last-Event-ID` header:

```bash
curl -N -H "Last-Event-ID: 41" "http://127.0.0.1:8765/api/stream"
```

Connect with an EventSource-compatible query token when `MACP_TOKEN` is set:

```bash
curl -N "http://127.0.0.1:8765/api/stream?last_event_id=0&token=$MACP_TOKEN"
```

Manual live-delivery check:

Terminal A:

```bash
uvicorn server.app:app --host 127.0.0.1 --port 8765
```

Terminal B:

```bash
curl -N "http://127.0.0.1:8765/api/stream?last_event_id=0"
```

Terminal C:

```bash
curl -s -X POST http://127.0.0.1:8765/api/notify \
  -H "Content-Type: application/json" \
  -d @examples/notify_done.json
```

Terminal B should receive a packet event similar to:

```text
id: 1
event: packet
data: {"protocol":"macp",...,"event_id":1,...}

```

When no events are available for 15 seconds, the stream sends a heartbeat comment:

```text
: ping

```

## Phase 2-A summary

- Added `GET /api/stream` SSE endpoint.
- Added `Last-Event-ID` / `?last_event_id=` support.
- Added `?token=` support for EventSource.
- Added heartbeat and backlog replay tests.
