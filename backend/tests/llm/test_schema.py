"""Structured-output parsing: all valid shapes, plus malformed replies."""
from __future__ import annotations

import json

import pytest

from app.llm.schema import LLMParseError, LLMResponse, parse_llm_response


def test_message_only():
    r = parse_llm_response('{"message": "hi", "trades": [], "watchlist_changes": []}')
    assert r == LLMResponse(message="hi", trades=[], watchlist_changes=[])


def test_missing_action_lists_default_to_empty():
    r = parse_llm_response('{"message": "hi"}')
    assert r.trades == [] and r.watchlist_changes == []


def test_null_action_lists_default_to_empty():
    r = parse_llm_response('{"message": "hi", "trades": null, "watchlist_changes": null}')
    assert r.trades == [] and r.watchlist_changes == []


def test_trades_and_watchlist_changes():
    raw = json.dumps({
        "message": "Done",
        "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10},
                   {"ticker": "MSFT", "side": "sell", "quantity": 2.5}],
        "watchlist_changes": [{"ticker": "PYPL", "action": "add"},
                              {"ticker": "NFLX", "action": "remove"}],
    })
    r = parse_llm_response(raw)
    assert [(t.ticker, t.side, t.quantity) for t in r.trades] == [("AAPL", "buy", 10), ("MSFT", "sell", 2.5)]
    assert [(w.ticker, w.action) for w in r.watchlist_changes] == [("PYPL", "add"), ("NFLX", "remove")]


def test_uppercase_enums_are_accepted():
    r = parse_llm_response('{"message": "x", "trades": [{"ticker": "AAPL", "side": "BUY", "quantity": 1}],'
                           ' "watchlist_changes": [{"ticker": "V", "action": "Add"}]}')
    assert r.trades[0].side == "buy" and r.watchlist_changes[0].action == "add"


def test_code_fenced_json():
    r = parse_llm_response('```json\n{"message": "fenced"}\n```')
    assert r.message == "fenced"


def test_json_wrapped_in_prose():
    r = parse_llm_response('Sure! {"message": "inner", "trades": []} hope that helps')
    assert r.message == "inner"


def test_malformed_items_are_dropped_not_fatal():
    raw = json.dumps({
        "message": "partial",
        "trades": [{"ticker": "AAPL", "side": "hold", "quantity": 1},
                   {"ticker": "AAPL", "side": "buy"},
                   "garbage",
                   {"ticker": "TSLA", "side": "sell", "quantity": 3}],
        "watchlist_changes": {"not": "a list"},
    })
    r = parse_llm_response(raw)
    assert [(t.ticker, t.side) for t in r.trades] == [("TSLA", "sell")]
    assert r.watchlist_changes == []


@pytest.mark.parametrize("raw", [None, "", "   ", "not json at all", "[1, 2]", '{"trades": []}',
                                 '{"message": ""}', '{"message": 42}', '{"message": "x"'])
def test_unusable_replies_raise(raw):
    with pytest.raises(LLMParseError):
        parse_llm_response(raw)


def test_schema_is_strict_friendly():
    schema = LLMResponse.model_json_schema()
    assert set(schema["required"]) == {"message", "trades", "watchlist_changes"}
    assert schema["additionalProperties"] is False
    for name in ("TradeInstruction", "WatchlistInstruction"):
        sub = schema["$defs"][name]
        assert set(sub["required"]) == set(sub["properties"])
        assert sub["additionalProperties"] is False
