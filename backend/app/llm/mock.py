"""Deterministic LLM stand-in for LLM_MOCK=true (E2E tests, development without a key).

Rules (on the lower-cased message), all matches are collected:
- "buy 5 AAPL" / "buy AAPL 5" / "buy 5 shares of AAPL" -> buy trade
- same with "sell" -> sell trade
- "add PYPL" / "watch PYPL" -> watchlist add; "remove PYPL" / "unwatch PYPL" -> watchlist remove
- nothing matched -> DEFAULT_MESSAGE, no actions
"""
from __future__ import annotations

import re

from .schema import LLMResponse, TradeInstruction, WatchlistInstruction

DEFAULT_MESSAGE = "Mock response: I am FinAlly, your AI trading assistant."

_NUM = r"(\d+(?:\.\d+)?)"
_TICKER = r"([a-z][a-z.]{0,9})"
_STOPWORDS = {"shares", "share", "of", "to", "the", "my", "a", "an", "some", "more", "from"}

_TRADE_QTY_FIRST = re.compile(rf"\b(buy|sell)\s+{_NUM}\s+(?:shares?\s+)?(?:of\s+)?{_TICKER}\b")
_TRADE_TICKER_FIRST = re.compile(rf"\b(buy|sell)\s+{_TICKER}\s+{_NUM}\b")
_WATCH = re.compile(rf"\b(add|watch|remove|unwatch)\s+{_TICKER}\b")


def _fmt_qty(quantity: float) -> str:
    return f"{quantity:g}"


def mock_response(user_message: str) -> LLMResponse:
    text = user_message.lower()
    trades: list[TradeInstruction] = []
    watch: list[WatchlistInstruction] = []
    parts: list[str] = []

    seen_trade_spans: list[tuple[int, int]] = []
    for m in _TRADE_QTY_FIRST.finditer(text):
        side, qty, ticker = m.group(1), float(m.group(2)), m.group(3)
        if ticker in _STOPWORDS or qty <= 0:
            continue
        trades.append(TradeInstruction(ticker=ticker.upper(), side=side, quantity=qty))
        seen_trade_spans.append(m.span())
    for m in _TRADE_TICKER_FIRST.finditer(text):
        if any(s <= m.start() < e for s, e in seen_trade_spans):
            continue
        side, ticker, qty = m.group(1), m.group(2), float(m.group(3))
        if ticker in _STOPWORDS or qty <= 0:
            continue
        trades.append(TradeInstruction(ticker=ticker.upper(), side=side, quantity=qty))
    for t in trades:
        verb = "buying" if t.side == "buy" else "selling"
        parts.append(f"Mock: {verb} {_fmt_qty(t.quantity)} {t.ticker}.")

    for m in _WATCH.finditer(text):
        verb, ticker = m.group(1), m.group(2)
        if ticker in _STOPWORDS:
            continue
        action = "add" if verb in ("add", "watch") else "remove"
        watch.append(WatchlistInstruction(ticker=ticker.upper(), action=action))
        if action == "add":
            parts.append(f"Mock: adding {ticker.upper()} to the watchlist.")
        else:
            parts.append(f"Mock: removing {ticker.upper()} from the watchlist.")

    message = " ".join(parts) if parts else DEFAULT_MESSAGE
    return LLMResponse(message=message, trades=trades, watchlist_changes=watch)
