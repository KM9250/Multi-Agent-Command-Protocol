from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("MACP_HOST", "127.0.0.1")
    port: int = int(os.getenv("MACP_PORT", "8765"))
    db_path: str = os.getenv("MACP_DB_PATH", "./data/macp.sqlite3")
    jsonl_path: str | None = os.getenv("MACP_JSONL_PATH", "./data/audit.jsonl") or None
    token: str | None = os.getenv("MACP_TOKEN") or None
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("MACP_CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    )
    mood_bad_threshold: float = float(os.getenv("MACP_MOOD_BAD_THRESHOLD", "0.5"))
    mood_good_confidence: float = float(os.getenv("MACP_MOOD_GOOD_CONFIDENCE", "0.75"))
    mood_good_satisfaction: float = float(os.getenv("MACP_MOOD_GOOD_SATISFACTION", "0.8"))


def get_settings() -> Settings:
    return Settings()
