"""Deterministic mock-mode rules (relied on by the E2E tests)."""
from __future__ import annotations

import pytest

from app.llm.mock import DEFAULT_MESSAGE, mock_response


def _trades(r):
    return [(t.ticker, t.side, t.quantity) for t in r.trades]


def _watch(r):
    return [(w.ticker, w.action) for w in r.watchlist_changes]


@pytest.mark.parametrize("text", ["buy 5 AAPL", "Buy 5 aapl", "please BUY 5 shares of AAPL", "buy AAPL 5"])
def test_buy(text):
    r = mock_response(text)
    assert _trades(r) == [("AAPL", "buy", 5)]
    assert r.message == "Mock: buying 5 AAPL."
    assert r.watchlist_changes == []


def test_sell_fractional():
    r = mock_response("sell 2.5 TSLA")
    assert _trades(r) == [("TSLA", "sell", 2.5)]
    assert r.message == "Mock: selling 2.5 TSLA."


@pytest.mark.parametrize("text", ["add PYPL", "watch pypl", "add PYPL to my watchlist"])
def test_watch_add(text):
    r = mock_response(text)
    assert _watch(r) == [("PYPL", "add")]
    assert r.trades == []
    assert r.message == "Mock: adding PYPL to the watchlist."


def test_watch_remove():
    r = mock_response("remove NFLX")
    assert _watch(r) == [("NFLX", "remove")]
    assert r.message == "Mock: removing NFLX from the watchlist."


def test_combined():
    r = mock_response("add PYPL and buy 3 PYPL")
    assert _watch(r) == [("PYPL", "add")]
    assert _trades(r) == [("PYPL", "buy", 3)]


@pytest.mark.parametrize("text", ["hello", "how is my portfolio?", "buy something", "buy 0 AAPL",
                                  "add to watchlist"])
def test_default(text):
    r = mock_response(text)
    assert r.message == DEFAULT_MESSAGE
    assert r.trades == [] and r.watchlist_changes == []


def test_deterministic():
    assert mock_response("buy 5 AAPL") == mock_response("buy 5 AAPL")
