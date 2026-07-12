from __future__ import annotations

import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError

from .config import get_settings
from .event_bus import EventBus
from .schemas import MacpPacket, normalize_packet
from .store import Store

settings = get_settings()
WEB_INDEX = Path(__file__).resolve().parents[1] / "clients" / "web" / "index.html"
Path("./data").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
handler = RotatingFileHandler("./data/server.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.getLogger().addHandler(handler)
logger = logging.getLogger(__name__)
if settings.host == "0.0.0.0" and not settings.token:
    logger.warning("MACP_TOKEN is not set while binding to 0.0.0.0")

app = FastAPI(title="MACP Notify Server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "X-MACP-Token", "Content-Type", "Last-Event-ID"],
)
app.state.settings = settings
app.state.store = Store(settings.db_path, settings.jsonl_path)
app.state.bus = EventBus()


def error_response(code: str, message: str, http_status: int, fields: list[str] | None = None) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code, "message": message, "fields": fields or []}}, status_code=http_status)


def validation_fields(errors: list[dict[str, Any]]) -> list[str]:
    fields = []
    for err in errors:
        loc = [str(x) for x in err.get("loc", []) if x not in ("body", "__root__")]
        fields.append(".".join(loc) if loc else "packet")
    return fields


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    return error_response("validation_error", "Validation failed", 422, validation_fields(exc.errors()))


@app.exception_handler(ValidationError)
async def pydantic_validation_handler(request: Request, exc: ValidationError):
    return error_response("validation_error", "Validation failed", 422, validation_fields(exc.errors()))


@app.exception_handler(HTTPException)
async def http_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401:
        return error_response("unauthorized", "Unauthorized", 401)
    if exc.status_code == 404:
        return error_response("not_found", "Not found", 404)
    if exc.status_code == 422:
        return error_response("validation_error", str(exc.detail), 422)
    return error_response("internal_error", "Internal server error", exc.status_code)


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.exception("Unhandled server error")
    return error_response("internal_error", "Internal server error", 500)


def _bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ")
    return None


def require_auth(
    request: Request,
    authorization: str | None = Header(default=None),
    x_macp_token: str | None = Header(default=None),
):
    token = request.app.state.settings.token
    if not token:
        return
    supplied = _bearer_token(authorization) or x_macp_token
    if supplied != token:
        raise HTTPException(status_code=401)


def require_stream_auth(
    request: Request,
    authorization: str | None = Header(default=None),
    x_macp_token: str | None = Header(default=None),
    token_query: str | None = Query(default=None, alias="token"),
):
    token = request.app.state.settings.token
    if not token:
        return
    supplied = _bearer_token(authorization) or x_macp_token or token_query
    if supplied != token:
        raise HTTPException(status_code=401)



def parse_last_event_id(header_value: str | None, query_value: str | None) -> int | None:
    raw = header_value if header_value not in (None, "") else query_value
    if raw in (None, ""):
        return None
    try:
        last_event_id = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="last_event_id must be a non-negative integer")
    if last_event_id < 0:
        raise HTTPException(status_code=422, detail="last_event_id must be a non-negative integer")
    return last_event_id


def packet_event(event_id: int, normalized: dict) -> dict:
    return {
        "event_id": event_id,
        "event_type": "packet",
        "task_id": normalized["task_id"],
        "created_at": normalized["received_at"],
        "payload": normalized,
    }


def format_sse(event: dict) -> str:
    event_id = int(event["event_id"])
    event_type = event.get("event_type", "packet")
    payload = event["payload"]
    if event_type == "packet":
        data = dict(payload)
        data["event_id"] = event_id
    else:
        data = dict(payload)
        data.setdefault("event_id", event_id)
        data.setdefault("event_type", event_type)
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\n" f"event: {event_type}\n" f"data: {data_json}\n\n"


async def event_generator(request: Request, store: Store, bus: EventBus, last_id: int | None):
    queue = bus.subscribe()
    cursor = last_id if last_id is not None else store.get_max_event_id()
    try:
        if last_id is not None:
            for event in store.get_events_after(last_id):
                if await request.is_disconnected():
                    return
                yield format_sse(event)
                cursor = max(cursor, int(event["event_id"]))

        while True:
            if await request.is_disconnected():
                return
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            event_id = int(event["event_id"])
            if event_id <= cursor:
                continue
            yield format_sse(event)
            cursor = event_id
    finally:
        bus.unsubscribe(queue)


def get_store(request: Request) -> Store:
    return request.app.state.store


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def web_index():
    if not WEB_INDEX.exists():
        raise HTTPException(status_code=404)
    return FileResponse(WEB_INDEX)


@app.post("/api/notify", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_auth)])
async def notify(packet: MacpPacket, request: Request, store: Store = Depends(get_store)):
    raw = await request.json()
    normalized = normalize_packet(packet)
    event_id = store.append_packet(normalized, raw)
    normalized["event_id"] = event_id
    logger.info("received task_id=%s intent=%s status=%s mood_computed=%s summary=%s", normalized.get("task_id"), normalized.get("intent"), normalized.get("status"), normalized.get("mood_computed"), normalized.get("summary"))
    await request.app.state.bus.publish(packet_event(event_id, normalized))
    return {"ok": True, "event_id": event_id, "task_id": normalized["task_id"], "mood_computed": normalized["mood_computed"]}


@app.post("/api/handoff", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_auth)])
async def handoff(packet: MacpPacket, request: Request, store: Store = Depends(get_store)):
    if packet.intent != "handoff_agent":
        raise HTTPException(status_code=422, detail="intent must be handoff_agent")
    raw = await request.json()
    normalized = normalize_packet(packet)
    event_id = store.append_packet(normalized, raw)
    normalized["event_id"] = event_id
    await request.app.state.bus.publish(packet_event(event_id, normalized))
    return {"ok": True, "event_id": event_id, "handoff_id": normalized["handoff"]["handoff_id"], "state": "pending"}


@app.get("/api/stream", dependencies=[Depends(require_stream_auth)])
async def stream(
    request: Request,
    store: Store = Depends(get_store),
    last_event_id: str | None = Query(default=None),
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
):
    last_id = parse_last_event_id(last_event_id_header, last_event_id)
    return StreamingResponse(
        event_generator(request, store, request.app.state.bus, last_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/tasks", dependencies=[Depends(require_auth)])
async def tasks(
    store: Store = Depends(get_store), status: str | None = None, task_type: str | None = None,
    intent: str | None = None, acknowledged: bool | None = None,
    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
):
    return {
        "ok": True,
        "tasks": store.list_tasks(status=status, task_type=task_type, intent=intent, acknowledged=acknowledged, limit=limit, offset=offset),
        "max_event_id": store.get_max_event_id(),
    }


@app.get("/api/tasks/{task_id}", dependencies=[Depends(require_auth)])
async def task_detail(task_id: str, store: Store = Depends(get_store)):
    data = store.get_task(task_id)
    if not data:
        raise HTTPException(status_code=404)
    return {"ok": True, **data}
