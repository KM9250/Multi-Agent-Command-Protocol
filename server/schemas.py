from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import get_settings

logger = logging.getLogger(__name__)

Protocol = Literal["macp"]
Intent = Literal["notify_user", "handoff_agent", "report_agent", "log_only", "need_review"]
Status = Literal["queued", "running", "done", "failed", "blocked", "need_review"]
Priority = Literal["low", "normal", "high"]
DestinationType = Literal["user", "agent", "broadcast"]

COMMAND_ALIASES = {
    "/curren-check": "/review",
    "/curren-polish": "/polish",
    "/vega-triage": "/triage",
    "/vega-spec": "/spec",
}
SERVER_FIELDS = {"event_id", "received_at", "mood_computed"}
KNOWN_TASK_TYPES = {"portfolio", "coding", "avatar_3d", "research", "document", "slides", "agent_handoff", "notification_test", "maintenance"}
KNOWN_MOODS = {"good", "caution", "bad", "blocked", "unknown"}


class CompatModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")


class AgentRef(CompatModel):
    agent_id: str
    agent_role: str | None = None


class Destination(CompatModel):
    type: DestinationType
    target: str | None = None


class ResultRef(CompatModel):
    format: str | None = None
    path: str | None = None
    url: str | None = None


class Evaluation(CompatModel):
    confidence: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    requirement_satisfaction: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    mood: str | None = None
    requires_user_action: bool = False


class ActionItem(CompatModel):
    label: str
    action_type: str
    target: str | None = None


class Handoff(CompatModel):
    handoff_id: str
    requested_command: str
    reason: str
    priority: Priority | None = None
    return_to: str | None = None
    return_intent: str | None = None
    return_format: str | None = None
    hop: int
    max_hops: int
    confidence_gate: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    must_return_to: bool = True

    @model_validator(mode="after")
    def validate_return_to(self) -> "Handoff":
        if self.must_return_to and not self.return_to:
            raise ValueError("return_to is required when must_return_to is true")
        return self


class MacpPacket(CompatModel):
    protocol: Protocol
    version: str = Field(pattern=r"^0\.\d+\.\d+$")
    task_id: str
    task_type: str
    intent: Intent
    from_: AgentRef = Field(alias="from")
    to: Destination | None = None
    command: str | None = None
    command_alias: str | None = None
    status: Status
    priority: Priority | None = None
    summary: str
    requirement_summary: str | None = None
    agent_message: str | None = None
    detail: str | None = None
    result: ResultRef | None = None
    evaluation: Evaluation | None = None
    actions: list[ActionItem] | None = None
    handoff: Handoff | None = None
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def drop_server_fields(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k not in SERVER_FIELDS}
        return data

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        parts = value.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts) or parts[0] != "0":
            raise ValueError("version must be semver with major version 0")
        return value

    @field_validator("created_at")
    @classmethod
    def validate_created_at_tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include timezone")
        return value

    @model_validator(mode="after")
    def validate_handoff_required(self) -> "MacpPacket":
        if self.task_type not in KNOWN_TASK_TYPES:
            logger.warning("unknown task_type accepted: %s", self.task_type)
        if self.evaluation and self.evaluation.mood and self.evaluation.mood not in KNOWN_MOODS:
            logger.warning("unknown evaluation.mood accepted: %s", self.evaluation.mood)
        if self.intent == "handoff_agent" and self.handoff is None:
            raise ValueError("handoff is required when intent is handoff_agent")
        return self


def _dump(packet: MacpPacket | dict) -> dict:
    if isinstance(packet, MacpPacket):
        return packet.model_dump(mode="json", by_alias=True, exclude_none=True)
    return dict(packet)


def compute_mood(packet: MacpPacket | dict) -> str:
    data = _dump(packet)
    status = data.get("status")
    if status == "failed":
        return "bad"
    if status == "blocked":
        return "blocked"
    if status in {"queued", "running"}:
        return "unknown"
    evaluation = data.get("evaluation") or {}
    confidence = evaluation.get("confidence")
    satisfaction = evaluation.get("requirement_satisfaction")
    if confidence is None:
        return "unknown"
    settings = get_settings()
    if confidence < settings.mood_bad_threshold:
        return "bad"
    if satisfaction is not None and satisfaction < settings.mood_bad_threshold:
        return "bad"
    if status == "need_review" or evaluation.get("requires_user_action") is True:
        return "caution"
    if confidence >= settings.mood_good_confidence and (
        satisfaction is None or satisfaction >= settings.mood_good_satisfaction
    ):
        return "good"
    return "caution"


def normalize_packet(packet: MacpPacket) -> dict:
    data = packet.model_dump(mode="json", by_alias=True, exclude_none=True)
    for field in SERVER_FIELDS:
        data.pop(field, None)
    if data.get("command") in COMMAND_ALIASES:
        data["command_alias"] = data["command"]
        data["command"] = COMMAND_ALIASES[data["command"]]
    handoff = data.get("handoff")
    if handoff and handoff.get("requested_command") in COMMAND_ALIASES:
        handoff["requested_command_alias"] = handoff["requested_command"]
        handoff["requested_command"] = COMMAND_ALIASES[handoff["requested_command"]]
    data.setdefault("to", {"type": "broadcast"})
    data.setdefault("priority", "normal")
    data["received_at"] = datetime.now(timezone.utc).isoformat()
    data["mood_computed"] = compute_mood(data)
    return data
