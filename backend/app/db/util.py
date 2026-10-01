from __future__ import annotations

from datetime import datetime, timezone

DEFAULT_USER = "default"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
