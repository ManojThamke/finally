"""Chat flow: LLM reply -> auto-executed actions -> persisted messages."""
from __future__ import annotations

import json

from app import db
from app.llm.client import LLMError
from app.llm.prompt import SYSTEM_PROMPT
from app.llm.service import APOLOGY_MESSAGE, handle_chat


def _reply(message="ok", trades=(), watch=()):
    return json.dumps({"message": message, "trades": list(trades), "watchlist_changes": list(watch)})


async def test_buy_executes_and_persists(fake_llm, price_cache, market_source):
    fake_llm.reply = _reply("Bought.", trades=[{"ticker": "aapl", "side": "buy", "quantity": 10}])
    body = await handle_chat("buy 10 apple", price_cache, market_source)

    assert body["role"] == "assistant" and body["message"] == "Bought."
    assert body["id"] and body["created_at"]
    assert body["trades"] == [{"ticker": "AAPL", "side": "buy", "quantity": 10, "status": "executed",
                               "price": 190.0, "error": None}]
    assert body["watchlist_changes"] == []
    with db.get_connection() as conn:
        assert db.get_cash(conn) == 10000.0 - 1900.0
        assert db.get_position(conn, "AAPL")["quantity"] == 10
        msgs = db.list_chat_messages(conn)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "buy 10 apple" and msgs[0]["actions"] is None
    assert msgs[1]["actions"]["trades"][0]["status"] == "executed"


async def test_insufficient_cash_is_failed_action(fake_llm, price_cache, market_source):
    fake_llm.reply = _reply(trades=[{"ticker": "MSFT", "side": "buy", "quantity": 1000}])
    body = await handle_chat("buy lots", price_cache, market_source)
    trade = body["trades"][0]
    assert trade["status"] == "failed" and trade["price"] is None
    assert "Insufficient cash" in trade["error"]
    with db.get_connection() as conn:
        assert db.get_cash(conn) == 10000.0
        assert db.get_position(conn, "MSFT") is None


async def test_one_failure_does_not_roll_back_others(fake_llm, price_cache, market_source):
    fake_llm.reply = _reply(trades=[
        {"ticker": "AAPL", "side": "buy", "quantity": 1},
        {"ticker": "TSLA", "side": "sell", "quantity": 5},       # not held
        {"ticker": "GOOGL", "side": "buy", "quantity": 0},       # invalid quantity
        {"ticker": "GOOGL", "side": "buy", "quantity": 2},
    ])
    body = await handle_chat("trade", price_cache, market_source)
    assert [t["status"] for t in body["trades"]] == ["executed", "failed", "failed", "executed"]
    assert "Insufficient shares" in body["trades"][1]["error"]
    assert "positive" in body["trades"][2]["error"]
    with db.get_connection() as conn:
        assert {p["ticker"] for p in db.list_positions(conn)} == {"AAPL", "GOOGL"}


async def test_unknown_ticker_trade_fails(fake_llm, price_cache, market_source):
    fake_llm.reply = _reply(trades=[{"ticker": "ZZZZ", "side": "buy", "quantity": 1}])
    body = await handle_chat("buy zzzz", price_cache, market_source)
    assert body["trades"][0]["status"] == "failed"
    assert "No price" in body["trades"][0]["error"]


async def test_watchlist_changes(fake_llm, price_cache, market_source):
    fake_llm.reply = _reply(watch=[{"ticker": "pypl", "action": "add"},
                                   {"ticker": "AAPL", "action": "add"},       # already present
                                   {"ticker": "NFLX", "action": "remove"},
                                   {"ticker": "XYZQ", "action": "remove"},    # absent
                                   {"ticker": "B@D!", "action": "add"}])      # invalid
    body = await handle_chat("watch stuff", price_cache, market_source)
    wc = body["watchlist_changes"]
    assert [(w["ticker"], w["status"]) for w in wc] == [
        ("PYPL", "executed"), ("AAPL", "failed"), ("NFLX", "executed"), ("XYZQ", "failed"), ("B@D!", "failed")]
    assert "already" in wc[1]["error"] and "not in the watchlist" in wc[3]["error"]
    assert "Invalid ticker" in wc[4]["error"]
    assert "PYPL" in market_source.tickers
    with db.get_connection() as conn:
        tickers = db.list_watchlist(conn)
    assert "PYPL" in tickers and "NFLX" not in tickers


async def test_watchlist_add_runs_before_trade(fake_llm, price_cache, market_source):
    fake_llm.reply = _reply(trades=[{"ticker": "PYPL", "side": "buy", "quantity": 2}],
                            watch=[{"ticker": "PYPL", "action": "add"}])
    body = await handle_chat("add pypl and buy 2", price_cache, market_source)
    assert body["watchlist_changes"][0]["status"] == "executed"
    assert body["trades"][0]["status"] == "executed" and body["trades"][0]["price"] == 50.0


async def test_llm_error_returns_apology(fake_llm, price_cache, market_source):
    fake_llm.reply = LLMError("boom")
    body = await handle_chat("hello", price_cache, market_source)
    assert body["message"] == APOLOGY_MESSAGE
    assert body["trades"] == [] and body["watchlist_changes"] == []
    with db.get_connection() as conn:
        assert [m["role"] for m in db.list_chat_messages(conn)] == ["user", "assistant"]


async def test_unexpected_exception_returns_apology(fake_llm, price_cache, market_source):
    fake_llm.reply = RuntimeError("weird")
    body = await handle_chat("hello", price_cache, market_source)
    assert body["message"] == APOLOGY_MESSAGE


async def test_malformed_json_returns_apology(fake_llm, price_cache, market_source):
    fake_llm.reply = "I'd buy AAPL if I were you"
    body = await handle_chat("hello", price_cache, market_source)
    assert body["message"] == APOLOGY_MESSAGE and body["trades"] == []


async def test_prompt_contains_context_and_history(fake_llm, price_cache, market_source):
    fake_llm.reply = _reply("first", trades=[{"ticker": "AAPL", "side": "buy", "quantity": 1}])
    await handle_chat("buy one apple", price_cache, market_source)
    fake_llm.reply = _reply("second")
    await handle_chat("how am I doing?", price_cache, market_source)

    messages = fake_llm.calls[-1]
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    context = json.loads(messages[1]["content"].split("\n", 1)[1])
    assert context["cash_balance"] == 10000.0 - 190.0
    assert context["positions"][0]["ticker"] == "AAPL"
    assert {"ticker": "AAPL", "price": 190.0, "day_change_percent": 0.0} in context["watchlist"]
    assert [m["role"] for m in messages[2:]] == ["user", "assistant", "user"]
    assert messages[2]["content"] == "buy one apple"
    assert messages[3]["content"].startswith("first\n[Actions: buy 1.0 AAPL: executed @ $190.0")
    assert messages[-1] == {"role": "user", "content": "how am I doing?"}


async def test_mock_mode_skips_llm(monkeypatch, fake_llm, price_cache, market_source):
    monkeypatch.setenv("LLM_MOCK", "true")
    body = await handle_chat("buy 5 AAPL", price_cache, market_source)
    assert fake_llm.calls == []
    assert body["message"] == "Mock: buying 5 AAPL."
    assert body["trades"][0]["status"] == "executed"


async def test_missing_api_key_without_mock_apologizes(monkeypatch, price_cache, market_source):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    body = await handle_chat("hi", price_cache, market_source)
    assert body["message"] == APOLOGY_MESSAGE
