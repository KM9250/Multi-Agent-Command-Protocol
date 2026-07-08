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


if __name__ == "__main__":
    main()
