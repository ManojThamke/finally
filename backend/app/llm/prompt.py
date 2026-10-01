"""System prompt, portfolio context and message assembly for the chat LLM."""
from __future__ import annotations

import json
import sqlite3

from app.db import list_watchlist
from app.market import PriceCache
from app.services.portfolio import build_portfolio

SYSTEM_PROMPT = """You are FinAlly, an AI trading assistant embedded in a simulated trading workstation.
The user trades a paper portfolio with virtual money: market orders only, instant fill at the
current price, no fees, fractional shares allowed.

Your job:
- Analyze portfolio composition, risk concentration, and P&L using the live context provided.
- Suggest trades with brief, data-driven reasoning.
- Execute trades when the user asks for one or agrees to your suggestion, by listing them in `trades`.
  Trades execute automatically - only include a trade when the user wants it executed.
- Manage the watchlist proactively via `watchlist_changes` (e.g. add a ticker the user asks about).
- Be concise and data-driven. Use numbers from the context; never invent prices.

Rules:
- Only buy what available cash covers and only sell shares the user holds; otherwise explain why not.
- Tickers are upper-case exchange symbols (e.g. AAPL). Quantities are positive numbers of shares.
- If the user gives a dollar amount, convert it to shares using the current price.
- Results of previously executed actions appear in the conversation history as [Actions: ...].

Always respond with valid JSON matching the schema:
{"message": "<your reply to the user>",
 "trades": [{"ticker": "AAPL", "side": "buy" | "sell", "quantity": 10}],
 "watchlist_changes": [{"ticker": "PYPL", "action": "add" | "remove"}]}
Use empty lists when there are no actions."""

HISTORY_LIMIT = 20


def build_portfolio_context(conn: sqlite3.Connection, price_cache: PriceCache) -> dict:
    """Snapshot of cash, positions with P&L, watchlist with live prices, total value."""
    portfolio = build_portfolio(conn, price_cache)
    watchlist = []
    for ticker in list_watchlist(conn):
        update = price_cache.get(ticker)
        watchlist.append({
            "ticker": ticker,
            "price": update.price if update else None,
            "day_change_percent": update.day_change_percent if update else None,
        })
    return {
        "cash_balance": portfolio["cash_balance"],
        "positions_value": portfolio["positions_value"],
        "total_value": portfolio["total_value"],
        "unrealized_pnl": portfolio["unrealized_pnl"],
        "unrealized_pnl_percent": portfolio["unrealized_pnl_percent"],
        "positions": [
            {k: p.get(k) for k in ("ticker", "quantity", "avg_cost", "current_price",
                                   "market_value", "unrealized_pnl",
                                   "unrealized_pnl_percent", "weight")}
            for p in portfolio["positions"]
        ],
        "watchlist": watchlist,
    }


def _summarize_actions(actions: dict | list | None) -> str:
    if not isinstance(actions, dict):
        return ""
    parts = []
    for t in actions.get("trades") or []:
        desc = f"{t.get('side')} {t.get('quantity')} {t.get('ticker')}: {t.get('status')}"
        if t.get("status") == "executed" and t.get("price") is not None:
            desc += f" @ ${t['price']}"
        if t.get("error"):
            desc += f" ({t['error']})"
        parts.append(desc)
    for w in actions.get("watchlist_changes") or []:
        desc = f"watchlist {w.get('action')} {w.get('ticker')}: {w.get('status')}"
        if w.get("error"):
            desc += f" ({w['error']})"
        parts.append(desc)
    return f"\n[Actions: {'; '.join(parts)}]" if parts else ""


def build_messages(context: dict, history: list[dict], user_message: str) -> list[dict]:
    """System prompt + live context, prior turns (oldest first), then the new user message."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system",
         "content": "Current portfolio context (live):\n" + json.dumps(context, default=str)},
    ]
    for row in history:
        role = row.get("role")
        if role not in ("user", "assistant"):
            continue
        content = row.get("content") or ""
        if role == "assistant":
            content += _summarize_actions(row.get("actions"))
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages
