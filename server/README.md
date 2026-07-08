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

## Web UI

Start server:

```bash
uvicorn server.app:app --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765/
```

Then post a sample packet:

```bash
curl -s -X POST http://127.0.0.1:8765/api/notify \
  -H "Content-Type: application/json" \
  -d @examples/notify_done.json
```

The task should appear in the browser without reloading.

With token:

```bash
MACP_TOKEN=secret uvicorn server.app:app --host 127.0.0.1 --port 8765
```

Open the Web UI, enter `secret` in the token dialog, and reconnect.

For LAN / smartphone browser:

```bash
MACP_TOKEN=secret uvicorn server.app:app --host 0.0.0.0 --port 8765
```

Open:

```text
http://<PC LAN IP>:8765/
```

The Web UI stores `macp_token`, `macp_last_event_id`, and `macp_unread_task_ids` in browser localStorage. The local read state is browser-only and does not call the Phase 3 server ack API.
