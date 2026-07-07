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
