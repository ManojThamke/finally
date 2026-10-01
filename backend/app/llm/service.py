"""Chat orchestration: context -> LLM (or mock) -> auto-execute actions -> persist."""
from __future__ import annotations

import logging

from app import db
from app.market import MarketDataSource, PriceCache, normalize_ticker
from app.services import watchlist as watchlist_service
from app.services.portfolio import TradeError, execute_trade

from .client import LLMError, call_llm, is_mock_mode
from .mock import mock_response
from .prompt import HISTORY_LIMIT, build_messages, build_portfolio_context
from .schema import LLMParseError, LLMResponse, TradeInstruction, WatchlistInstruction, parse_llm_response

logger = logging.getLogger(__name__)

APOLOGY_MESSAGE = (
    "Sorry, I couldn't process that request right now. Please try again in a moment."
)


async def _get_llm_response(messages: list[dict], user_message: str) -> LLMResponse:
    if is_mock_mode():
        return mock_response(user_message)
    try:
        raw = await call_llm(messages)
        return parse_llm_response(raw)
    except (LLMError, LLMParseError) as exc:
        logger.warning("Chat LLM failure: %s", exc)
    except Exception:  # never let the LLM path surface a 500
        logger.exception("Unexpected chat LLM failure")
    return LLMResponse(message=APOLOGY_MESSAGE, trades=[], watchlist_changes=[])


def _run_trade(price_cache: PriceCache, trade: TradeInstruction) -> dict:
    ticker = normalize_ticker(trade.ticker)
    result = {"ticker": ticker, "side": trade.side, "quantity": trade.quantity,
              "status": "failed", "price": None, "error": None}
    try:
        # One transaction per action: a failure rolls back only itself.
        with db.get_connection() as conn:
            executed = execute_trade(conn, price_cache, ticker, trade.side, trade.quantity)
        result.update(status="executed", price=executed["price"])
    except TradeError as exc:
        result["error"] = str(exc)
    except Exception as exc:
        logger.exception("Chat trade failed unexpectedly")
        result["error"] = f"Trade failed: {type(exc).__name__}"
    return result


async def _run_watchlist_change(market_source: MarketDataSource, change: WatchlistInstruction) -> dict:
    ticker = normalize_ticker(change.ticker)
    result = {"ticker": ticker, "action": change.action, "status": "failed", "error": None}
    try:
        with db.get_connection() as conn:
            if change.action == "add":
                ok = await watchlist_service.add_ticker(conn, market_source, ticker)
                error = f"{ticker} is already in the watchlist"
            else:
                ok = await watchlist_service.remove_ticker(conn, market_source, ticker)
                error = f"{ticker} is not in the watchlist"
        if ok:
            result["status"] = "executed"
        else:
            result["error"] = error
    except watchlist_service.InvalidTickerError as exc:
        result["error"] = str(exc)
    except Exception as exc:
        logger.exception("Chat watchlist change failed unexpectedly")
        result["error"] = f"Watchlist change failed: {type(exc).__name__}"
    return result


async def handle_chat(
    user_message: str, price_cache: PriceCache, market_source: MarketDataSource
) -> dict:
    """Process one user chat message end to end; returns the POST /api/chat body."""
    with db.get_connection() as conn:
        context = build_portfolio_context(conn, price_cache)
        history = db.list_chat_messages(conn, limit=HISTORY_LIMIT)
        db.insert_chat_message(conn, "user", user_message)

    messages = build_messages(context, history, user_message)
    response = await _get_llm_response(messages, user_message)

    # Watchlist changes first so "add XYZ and buy some" has a live price for the trade.
    watchlist_results = [
        await _run_watchlist_change(market_source, c) for c in response.watchlist_changes
    ]
    trade_results = [_run_trade(price_cache, t) for t in response.trades]

    actions = {"trades": trade_results, "watchlist_changes": watchlist_results}
    with db.get_connection() as conn:
        saved = db.insert_chat_message(conn, "assistant", response.message, actions)

    return {
        "id": saved["id"],
        "role": "assistant",
        "message": response.message,
        "created_at": saved["created_at"],
        "trades": trade_results,
        "watchlist_changes": watchlist_results,
    }


def chat_history(limit: int = 200) -> list[dict]:
    with db.get_connection() as conn:
        rows = db.list_chat_messages(conn, limit=limit)
    return [
        {k: row.get(k) for k in ("id", "role", "content", "actions", "created_at")}
        for row in rows
    ]
