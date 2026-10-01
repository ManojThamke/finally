"""Portfolio logic: market-order execution, valuation and snapshots."""
from __future__ import annotations

import math
import sqlite3

from app import db
from app.market import PriceCache

from .watchlist import InvalidTickerError, validate_ticker

# Float noise tolerance: a position below this many shares is treated as closed,
# and cash/share checks allow this much slack.
EPSILON = 1e-6


class TradeError(Exception):
    """A trade failed validation. The message is shown to the user as-is."""


def _price_for(price_cache: PriceCache, ticker: str, avg_cost: float) -> float:
    price = price_cache.get_price(ticker)
    return price if price is not None else avg_cost


def build_portfolio(conn: sqlite3.Connection, price_cache: PriceCache) -> dict:
    """The `GET /api/portfolio` body. Positions with no live price are valued at avg cost."""
    cash = db.get_cash(conn)
    positions = []
    for p in db.list_positions(conn):
        current = _price_for(price_cache, p["ticker"], p["avg_cost"])
        cost_basis = p["quantity"] * p["avg_cost"]
        market_value = p["quantity"] * current
        pnl = market_value - cost_basis
        positions.append({
            "ticker": p["ticker"],
            "quantity": p["quantity"],
            "avg_cost": round(p["avg_cost"], 4),
            "current_price": current,
            "market_value": market_value,
            "unrealized_pnl": pnl,
            "unrealized_pnl_percent": round(pnl / cost_basis * 100, 2) if cost_basis else 0.0,
        })

    positions_value = sum(p["market_value"] for p in positions)
    total_cost = sum(p["quantity"] * p["avg_cost"] for p in positions)
    total_pnl = positions_value - total_cost
    total_value = cash + positions_value
    for p in positions:
        p["weight"] = round(p["market_value"] / total_value * 100, 2) if total_value else 0.0
        p["market_value"] = round(p["market_value"], 2)
        p["unrealized_pnl"] = round(p["unrealized_pnl"], 2)

    return {
        "cash_balance": round(cash, 2),
        "positions_value": round(positions_value, 2),
        "total_value": round(total_value, 2),
        "unrealized_pnl": round(total_pnl, 2),
        "unrealized_pnl_percent": round(total_pnl / total_cost * 100, 2) if total_cost else 0.0,
        "positions": positions,
    }


def record_snapshot(conn: sqlite3.Connection, price_cache: PriceCache) -> dict:
    """Store the current total portfolio value."""
    return db.insert_snapshot(conn, build_portfolio(conn, price_cache)["total_value"])


def execute_trade(
    conn: sqlite3.Connection, price_cache: PriceCache, ticker: str, side: str, quantity: float
) -> dict:
    """Fill a market order at the cached price. Raises TradeError; does not commit."""
    try:
        ticker = validate_ticker(ticker)
    except InvalidTickerError as exc:
        raise TradeError(str(exc)) from None
    side = (side or "").strip().lower()
    if side not in ("buy", "sell"):
        raise TradeError(f"Invalid side: {side!r} (expected 'buy' or 'sell')")
    try:
        quantity = float(quantity)
    except (TypeError, ValueError):
        raise TradeError("Quantity must be a number") from None
    if not math.isfinite(quantity) or quantity <= 0:
        raise TradeError("Quantity must be positive")

    price = price_cache.get_price(ticker)
    if price is None:
        raise TradeError(f"No price available for {ticker}")

    cash = db.get_cash(conn)
    position = db.get_position(conn, ticker)
    held = position["quantity"] if position else 0.0
    cost = quantity * price

    if side == "buy":
        if cost > cash + EPSILON:
            raise TradeError(f"Insufficient cash: need ${cost:,.2f}, have ${cash:,.2f}")
        new_qty = held + quantity
        avg_cost = (held * position["avg_cost"] + cost) / new_qty if position else price
        db.set_cash(conn, max(cash - cost, 0.0))
        db.upsert_position(conn, ticker, new_qty, avg_cost)
    else:
        if quantity > held + EPSILON:
            raise TradeError(f"Insufficient shares: trying to sell {quantity:g} {ticker}, hold {held:g}")
        new_qty = held - quantity
        db.set_cash(conn, cash + cost)
        if new_qty <= EPSILON:
            db.delete_position(conn, ticker)
        else:
            db.upsert_position(conn, ticker, new_qty, position["avg_cost"])

    trade = db.insert_trade(conn, ticker, side, quantity, price)
    record_snapshot(conn, price_cache)
    return trade
