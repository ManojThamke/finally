"""Watchlist operations: keep the DB and the live market data source in sync."""
from __future__ import annotations

import re
import sqlite3

from app import db
from app.market import MarketDataSource, PriceCache, normalize_ticker

_TICKER_RE = re.compile(r"^[A-Z.]{1,10}$")


class InvalidTickerError(ValueError):
    """Raised for an empty or malformed ticker symbol. Message is user-facing."""


def validate_ticker(ticker: str) -> str:
    """Normalize `ticker` and check it looks like a symbol; return the normalized form."""
    normalized = normalize_ticker(ticker or "")
    if not _TICKER_RE.match(normalized):
        raise InvalidTickerError(f"Invalid ticker: {ticker!r}")
    return normalized


async def add_ticker(conn: sqlite3.Connection, market_source: MarketDataSource, ticker: str) -> bool:
    """Add to the watchlist and start streaming it. False if already watched."""
    ticker = validate_ticker(ticker)
    added = db.add_watchlist_ticker(conn, ticker)
    if added:
        await market_source.add_ticker(ticker)
    return added


async def remove_ticker(conn: sqlite3.Connection, market_source: MarketDataSource, ticker: str) -> bool:
    """Remove from the watchlist. Keeps streaming it if a position still holds it. False if absent."""
    ticker = normalize_ticker(ticker or "")
    removed = db.remove_watchlist_ticker(conn, ticker)
    if removed and db.get_position(conn, ticker) is None:
        await market_source.remove_ticker(ticker)
    return removed


def list_watchlist_with_prices(conn: sqlite3.Connection, price_cache: PriceCache) -> list[dict]:
    """`GET /api/watchlist` rows: every watched ticker with its latest price (or nulls)."""
    rows = []
    for ticker in db.list_watchlist(conn):
        update = price_cache.get(ticker)
        if update is None:
            rows.append({
                "ticker": ticker, "price": None, "previous_price": None, "change": None,
                "change_percent": None, "day_change_percent": None, "direction": None,
            })
            continue
        rows.append({
            "ticker": ticker,
            "price": update.price,
            "previous_price": update.previous_price,
            "change": update.change,
            "change_percent": update.change_percent,
            "day_change_percent": update.day_change_percent,
            "direction": update.direction,
        })
    return rows


def tracked_tickers(conn: sqlite3.Connection) -> list[str]:
    """Tickers the market source must stream: union of watchlist and held positions."""
    tickers = dict.fromkeys(db.list_watchlist(conn))
    tickers.update(dict.fromkeys(p["ticker"] for p in db.list_positions(conn)))
    return list(tickers)
