from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.schemas import MacpPacket, compute_mood, normalize_packet

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_examples_parse_and_normalize():
    files = sorted(EXAMPLES.glob("*.json"))
    assert len(files) == 5
    for path in files:
        packet = MacpPacket.model_validate_json(path.read_text(encoding="utf-8"))
        normalized = normalize_packet(packet)
        assert normalized["protocol"] == "macp"
        assert "from" in normalized
        assert "received_at" in normalized
        assert "mood_computed" in normalized


def test_missing_summary_rejected():
    data = load("notify_done.json")
    data.pop("summary")
    with pytest.raises(ValidationError):
        MacpPacket.model_validate(data)


def test_confidence_range_rejected():
    data = load("notify_done.json")
    data["evaluation"]["confidence"] = 1.5
    with pytest.raises(ValidationError):
        MacpPacket.model_validate(data)


def test_enum_policy():
    data = load("notify_done.json")
    bad = copy.deepcopy(data); bad["intent"] = "unknown_intent"
    with pytest.raises(ValidationError):
        MacpPacket.model_validate(bad)
    ok = copy.deepcopy(data); ok["task_type"] = "space_travel"; ok["evaluation"]["mood"] = "great"
    packet = MacpPacket.model_validate(ok)
    assert packet.task_type == "space_travel"
    assert packet.evaluation.mood == "great"


def test_handoff_required():
    data = load("handoff_agent.json")
    data.pop("handoff")
    with pytest.raises(ValidationError):
        MacpPacket.model_validate(data)


def test_alias_normalization():
    data = load("notify_done.json")
    data["command"] = "/vega-spec"
    data.pop("command_alias", None)
    normalized = normalize_packet(MacpPacket.model_validate(data))
    assert normalized["command"] == "/spec"
    assert normalized["command_alias"] == "/vega-spec"


def packet_with(**updates):
    data = load("notify_done.json")
    data.update(updates)
    data["evaluation"] = updates.get("evaluation", data.get("evaluation"))
    return MacpPacket.model_validate(data)


def test_compute_mood_cases():
    assert compute_mood(packet_with(status="failed")) == "bad"
    assert compute_mood(packet_with(status="blocked")) == "blocked"
    assert compute_mood(packet_with(status="running")) == "unknown"
    assert compute_mood(packet_with(evaluation=None)) == "unknown"
    assert compute_mood(packet_with(evaluation={"confidence": 0.3, "requirement_satisfaction": 0.9})) == "bad"
    assert compute_mood(packet_with(status="need_review")) == "caution"
    assert compute_mood(packet_with(evaluation={"confidence": 0.86, "requirement_satisfaction": 0.9, "requires_user_action": False})) == "good"
    assert compute_mood(packet_with(evaluation={"confidence": 0.6, "requirement_satisfaction": 0.6})) == "caution"


def test_server_fields_are_discarded():
    data = load("notify_done.json")
    data["event_id"] = 999
    data["received_at"] = "2000-01-01T00:00:00+00:00"
    data["mood_computed"] = "bad"
    normalized = normalize_packet(MacpPacket.model_validate(data))
    assert "event_id" not in normalized
    assert normalized["received_at"] != "2000-01-01T00:00:00+00:00"
    assert normalized["mood_computed"] == "caution"


def test_handoff_requested_command_alias_normalization():
    data = load("handoff_agent.json")
    data["handoff"]["requested_command"] = "/curren-check"
    normalized = normalize_packet(MacpPacket.model_validate(data))
    assert normalized["handoff"]["requested_command"] == "/review"
    assert normalized["handoff"]["requested_command_alias"] == "/curren-check"


def test_handoff_confidence_gate_range_rejected():
    data = load("handoff_agent.json")
    data["handoff"]["confidence_gate"] = 1.5
    with pytest.raises(ValidationError):
        MacpPacket.model_validate(data)


def test_schema_drift(tmp_path):
    before = (ROOT / "schema" / "macp-packet.schema.json").read_text(encoding="utf-8")
    subprocess.run([sys.executable, "scripts/generate_schema.py"], cwd=ROOT, check=True)
    after = (ROOT / "schema" / "macp-packet.schema.json").read_text(encoding="utf-8")
    assert before == after
