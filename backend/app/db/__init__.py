"""SQLite persistence layer: lazy init, connections, repository functions."""
from __future__ import annotations

from .connection import default_db_path, get_connection, init_db
from .repository import (
    add_watchlist_ticker,
    delete_position,
    get_cash,
    get_position,
    insert_chat_message,
    insert_snapshot,
    insert_trade,
    list_chat_messages,
    list_positions,
    list_snapshots,
    list_trades,
    list_watchlist,
    remove_watchlist_ticker,
    set_cash,
    upsert_position,
)
from .seed import DEFAULT_CASH, DEFAULT_TICKERS
from .util import DEFAULT_USER

__all__ = [
    "DEFAULT_CASH",
    "DEFAULT_TICKERS",
    "DEFAULT_USER",
    "add_watchlist_ticker",
    "default_db_path",
    "delete_position",
    "get_cash",
    "get_connection",
    "get_position",
    "init_db",
    "insert_chat_message",
    "insert_snapshot",
    "insert_trade",
    "list_chat_messages",
    "list_positions",
    "list_snapshots",
    "list_trades",
    "list_watchlist",
    "remove_watchlist_ticker",
    "set_cash",
    "upsert_position",
]
