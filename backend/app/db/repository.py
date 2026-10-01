"""Repository functions. Each takes an open connection and does NOT commit.

Ordering ties (identical ISO timestamps) are broken by SQLite rowid, i.e. insert order.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from .seed import seed_defaults
from .util import DEFAULT_USER, now_iso


def _norm(ticker: str) -> str:
    return ticker.strip().upper()


def _new_id() -> str:
    return str(uuid.uuid4())


# --- cash -------------------------------------------------------------------

def get_cash(conn: sqlite3.Connection, *, user_id: str = DEFAULT_USER) -> float:
    row = conn.execute("SELECT cash_balance FROM users_profile WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        seed_defaults(conn, user_id)
        row = conn.execute("SELECT cash_balance FROM users_profile WHERE id = ?", (user_id,)).fetchone()
    return float(row["cash_balance"])


def set_cash(conn: sqlite3.Connection, amount: float, *, user_id: str = DEFAULT_USER) -> None:
    conn.execute(
        "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET cash_balance = excluded.cash_balance",
        (user_id, float(amount), now_iso()),
    )


# --- watchlist --------------------------------------------------------------

def list_watchlist(conn: sqlite3.Connection, *, user_id: str = DEFAULT_USER) -> list[str]:
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at, rowid", (user_id,)
    ).fetchall()
    return [r["ticker"] for r in rows]


def add_watchlist_ticker(conn: sqlite3.Connection, ticker: str, *, user_id: str = DEFAULT_USER) -> bool:
    cur = conn.execute(
        "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
        (_new_id(), user_id, _norm(ticker), now_iso()),
    )
    return cur.rowcount == 1


def remove_watchlist_ticker(conn: sqlite3.Connection, ticker: str, *, user_id: str = DEFAULT_USER) -> bool:
    cur = conn.execute(
        "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?", (user_id, _norm(ticker))
    )
    return cur.rowcount > 0


# --- positions --------------------------------------------------------------

_POSITION_COLS = "ticker, quantity, avg_cost, updated_at"


def list_positions(conn: sqlite3.Connection, *, user_id: str = DEFAULT_USER) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {_POSITION_COLS} FROM positions WHERE user_id = ? ORDER BY ticker", (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_position(
    conn: sqlite3.Connection, ticker: str, *, user_id: str = DEFAULT_USER
) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_POSITION_COLS} FROM positions WHERE user_id = ? AND ticker = ?",
        (user_id, _norm(ticker)),
    ).fetchone()
    return dict(row) if row else None


def upsert_position(
    conn: sqlite3.Connection,
    ticker: str,
    quantity: float,
    avg_cost: float,
    *,
    user_id: str = DEFAULT_USER,
) -> None:
    conn.execute(
        "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id, ticker) DO UPDATE SET "
        "quantity = excluded.quantity, avg_cost = excluded.avg_cost, updated_at = excluded.updated_at",
        (_new_id(), user_id, _norm(ticker), float(quantity), float(avg_cost), now_iso()),
    )


def delete_position(conn: sqlite3.Connection, ticker: str, *, user_id: str = DEFAULT_USER) -> None:
    conn.execute("DELETE FROM positions WHERE user_id = ? AND ticker = ?", (user_id, _norm(ticker)))


# --- trades -----------------------------------------------------------------

def insert_trade(
    conn: sqlite3.Connection,
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    *,
    user_id: str = DEFAULT_USER,
) -> dict[str, Any]:
    trade = {
        "id": _new_id(),
        "ticker": _norm(ticker),
        "side": side,
        "quantity": float(quantity),
        "price": float(price),
        "executed_at": now_iso(),
    }
    conn.execute(
        "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (trade["id"], user_id, trade["ticker"], side, trade["quantity"], trade["price"], trade["executed_at"]),
    )
    return trade


def list_trades(
    conn: sqlite3.Connection, limit: int = 50, *, user_id: str = DEFAULT_USER
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, ticker, side, quantity, price, executed_at FROM trades "
        "WHERE user_id = ? ORDER BY executed_at DESC, rowid DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# --- portfolio snapshots ----------------------------------------------------

def insert_snapshot(
    conn: sqlite3.Connection, total_value: float, *, user_id: str = DEFAULT_USER
) -> dict[str, Any]:
    snap = {"id": _new_id(), "total_value": float(total_value), "recorded_at": now_iso()}
    conn.execute(
        "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) VALUES (?, ?, ?, ?)",
        (snap["id"], user_id, snap["total_value"], snap["recorded_at"]),
    )
    return snap


def list_snapshots(
    conn: sqlite3.Connection, limit: int | None = None, *, user_id: str = DEFAULT_USER
) -> list[dict[str, Any]]:
    """Oldest first. With `limit`, returns the most recent `limit` snapshots (still oldest first)."""
    rows = conn.execute(
        "SELECT id, total_value, recorded_at FROM portfolio_snapshots "
        "WHERE user_id = ? ORDER BY recorded_at DESC, rowid DESC LIMIT ?",
        (user_id, -1 if limit is None else limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


# --- chat -------------------------------------------------------------------

def _chat_row(row: sqlite3.Row) -> dict[str, Any]:
    msg = dict(row)
    msg["actions"] = json.loads(msg["actions"]) if msg["actions"] is not None else None
    return msg


def insert_chat_message(
    conn: sqlite3.Connection,
    role: str,
    content: str,
    actions: dict | list | None = None,
    *,
    user_id: str = DEFAULT_USER,
) -> dict[str, Any]:
    msg = {"id": _new_id(), "role": role, "content": content, "actions": actions, "created_at": now_iso()}
    conn.execute(
        "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            msg["id"],
            user_id,
            role,
            content,
            json.dumps(actions) if actions is not None else None,
            msg["created_at"],
        ),
    )
    return msg


def list_chat_messages(
    conn: sqlite3.Connection, limit: int = 20, *, user_id: str = DEFAULT_USER
) -> list[dict[str, Any]]:
    """The most recent `limit` messages, returned oldest first."""
    rows = conn.execute(
        "SELECT id, role, content, actions, created_at FROM chat_messages "
        "WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [_chat_row(r) for r in reversed(rows)]
