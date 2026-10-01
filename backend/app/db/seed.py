"""Default seed data: one user profile with $10k and the starter watchlist."""
from __future__ import annotations

import sqlite3
import uuid

from .util import DEFAULT_USER, now_iso

DEFAULT_CASH = 10000.0
DEFAULT_TICKERS = ("AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX")


def seed_defaults(conn: sqlite3.Connection, user_id: str = DEFAULT_USER) -> None:
    """Seed the profile and watchlist only when the profile is first created.

    Tying the watchlist seed to profile creation means a user who empties their
    watchlist does not get the defaults back on the next restart.
    """
    created = conn.execute(
        "INSERT OR IGNORE INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
        (user_id, DEFAULT_CASH, now_iso()),
    ).rowcount
    if not created:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
        [(str(uuid.uuid4()), user_id, t, now_iso()) for t in DEFAULT_TICKERS],
    )
