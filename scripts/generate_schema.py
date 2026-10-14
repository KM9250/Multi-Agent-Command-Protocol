from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.schemas import MacpPacket  # noqa: E402


def main() -> None:
    out = ROOT / "schema" / "macp-packet.schema.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = MacpPacket.model_json_schema(by_alias=True)
    out.write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Keep the existing TypeScript declarations; derive the new intake fields
    # from the same model as JSON Schema, never from a second handwritten list.
    ts_path = ROOT / "schema" / "macp.d.ts"
    start = "// BEGIN GENERATED IDEMPOTENCY FIELDS"
    end = "// END GENERATED IDEMPOTENCY FIELDS"
    before, rest = ts_path.read_text(encoding="utf-8").split(start)
    _, after = rest.split(end)
    lines = [start, "export interface ProducerEventFields {"]
    for name in schema["dependentRequired"]:
        field = schema["properties"][name]
        assert field["type"] == "string"
        lines.extend([
            f"  /** Supply both keys. {field['minLength']}–{field['maxLength']} ASCII letters, digits, '.', '_', ':', '-'. */",
            f"  {name}?: string;",
        ])
    lines.extend(["}", end])
    ts_path.write_text(before + "\n".join(lines) + after, encoding="utf-8")


if __name__ == "__main__":
    main()
