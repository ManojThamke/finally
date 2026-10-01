"""SQLite connection handling with lazy, idempotent schema init + seed."""
from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .seed import seed_defaults

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
# backend/app/db/connection.py -> repo root is three parents up from app/
_REPO_ROOT = Path(__file__).resolve().parents[3]

_init_lock = threading.Lock()
_initialized: set[Path] = set()


def default_db_path() -> Path:
    env = os.environ.get("FINALLY_DB_PATH", "").strip()
    return Path(env) if env else _REPO_ROOT / "db" / "finally.db"


def _resolve(path: str | Path | None) -> Path:
    return Path(path).expanduser().resolve() if path is not None else default_db_path().resolve()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(path: str | Path | None = None) -> None:
    """Create the DB file, tables and default seed data if missing. Safe to call repeatedly."""
    db_path = _resolve(path)
    with _init_lock:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect(db_path)
        try:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            seed_defaults(conn)
            conn.commit()
        finally:
            conn.close()
        _initialized.add(db_path)


@contextmanager
def get_connection(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a fresh connection; commit on clean exit, roll back on exception."""
    db_path = _resolve(path)
    if db_path not in _initialized or not db_path.exists():
        init_db(db_path)
    conn = _connect(db_path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
