import asyncio
from datetime import date

import httpx

from app.market import MarketDataSource, PriceCache
from app.market.massive_client import (
    MassiveDataSource, parse_grouped_daily, parse_snapshot, pick_price, recent_weekdays,
)

SNAPSHOT = {
    "status": "OK",
    "tickers": [
        {"ticker": "AAPL", "lastTrade": {"p": 191.5}, "prevDay": {"c": 190.0}},
        {"ticker": "MSFT", "lastTrade": {"p": 0}, "min": {"c": 421.0}, "prevDay": {"c": 420.0}},
        {"ticker": "BAD", "day": {"c": 0}},
    ],
}
GROUPED = {"results": [{"T": "AAPL", "c": 189.0}, {"T": "MSFT", "c": 419.0}, {"T": "PYPL", "c": 70.0}]}


def test_pick_price_fallback_order():
    assert pick_price({"lastTrade": {"p": 1.5}, "min": {"c": 2}}) == 1.5
    assert pick_price({"lastTrade": {"p": 0}, "min": {"c": 2}}) == 2.0
    assert pick_price({"day": {"c": 3}}) == 3.0
    assert pick_price({"prevDay": {"c": 4}}) == 4.0
    assert pick_price({"lastTrade": None}) is None
    assert pick_price({}) is None


def test_parsers():
    assert parse_snapshot(SNAPSHOT) == {"AAPL": (191.5, 190.0), "MSFT": (421.0, 420.0)}
    assert parse_snapshot({}) == {}
    assert parse_grouped_daily(GROUPED)["PYPL"] == 70.0
    assert parse_grouped_daily({"resultsCount": 0}) == {}
    assert parse_grouped_daily({"results": [{"T": "X", "c": 0}, {"c": 5}]}) == {}


def test_recent_weekdays_skips_weekend():
    monday = date(2026, 9, 28)
    assert recent_weekdays(monday, None, limit=2) == [monday, date(2026, 9, 25)]
    assert recent_weekdays(monday, newer_than=date(2026, 9, 25)) == [monday]
    assert recent_weekdays(monday, newer_than=monday) == []


def make_source(handler, **kw):
    calls = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    src = MassiveDataSource(
        PriceCache(), "test-key", transport=httpx.MockTransport(wrapped),
        today=lambda: date(2026, 9, 28), **kw,
    )
    return src, calls


async def test_live_mode_populates_cache():
    src, calls = make_source(lambda r: httpx.Response(200, json=SNAPSHOT))
    assert isinstance(src, MarketDataSource)
    await src.start(["AAPL", "MSFT"])
    assert src.mode == "live"
    assert src.cache.get_price("AAPL") == 191.5
    assert src.cache.get("AAPL").session_open == 190.0
    assert calls[0].headers["Authorization"] == "Bearer test-key"
    assert "test-key" not in str(calls[0].url)
    assert calls[0].url.params["tickers"] == "AAPL,MSFT"
    assert src.status()["healthy"] and src.status()["mode"] == "live"
    await src.stop()


async def test_no_request_without_tickers():
    src, calls = make_source(lambda r: httpx.Response(200, json=SNAPSHOT))
    await src.start([])
    assert calls == []
    await src.stop()
    await src.stop()  # idempotent


async def test_403_falls_back_to_eod_and_add_ticker_uses_cached_closes():
    def handler(r: httpx.Request) -> httpx.Response:
        if "snapshot" in r.url.path:
            return httpx.Response(403, json={"status": "NOT_AUTHORIZED"})
        if r.url.path.endswith("2026-09-28"):
            return httpx.Response(200, json={"resultsCount": 0})  # before close
        return httpx.Response(200, json=GROUPED)

    src, calls = make_source(handler)
    await src.start(["AAPL"])
    assert src.mode == "eod" and src.cache.get_price("AAPL") == 189.0
    assert src.cache.get("AAPL").session_open == 189.0
    n = len(calls)
    await src.add_ticker("PYPL")
    assert src.cache.get_price("PYPL") == 70.0 and len(calls) == n   # no extra request
    await src.stop()


async def test_401_stops_polling():
    src, _ = make_source(lambda r: httpx.Response(401))
    await src.start(["AAPL"])
    assert src.mode == "unauthorized" and not src.status()["healthy"]
    assert src.last_error == "HTTP 401"
    await src.stop()


async def test_429_backs_off_and_network_error_keeps_prices():
    responses = iter([httpx.Response(200, json=SNAPSHOT), httpx.Response(429)])

    def handler(r):
        try:
            return next(responses)
        except StopIteration:
            raise httpx.ConnectTimeout("boom")

    src, _ = make_source(handler, poll_interval=15)
    await src.start(["AAPL"])
    await src._poll_once()
    assert src._backoff == 15
    assert src._next_delay() == 30
    await src._poll_once()
    assert src.cache.get_price("AAPL") == 191.5 and "ConnectTimeout" in src.last_error
    assert not src.status()["healthy"]
    await src.stop()


async def test_backoff_doubles_and_caps():
    src, _ = make_source(lambda r: httpx.Response(429), poll_interval=15, max_backoff=60)
    await src.start(["AAPL"])
    seen = [src._backoff]
    for _ in range(3):
        await src._poll_once()
        seen.append(src._backoff)
    assert seen == [15, 30, 60, 60]
    await src.stop()


async def test_server_error_keeps_prices_and_recovers():
    state = {"fail": False}

    def handler(r):
        return httpx.Response(500) if state["fail"] else httpx.Response(200, json=SNAPSHOT)

    src, _ = make_source(handler)
    await src.start(["AAPL"])
    state["fail"] = True
    await src._poll_once()
    assert src.cache.get_price("AAPL") == 191.5 and src.last_error == "HTTP 500"
    state["fail"] = False
    await src._poll_once()
    assert src.last_error is None
    await src.stop()


async def test_bad_json_is_handled():
    src, _ = make_source(lambda r: httpx.Response(200, content=b"not json"))
    await src.start(["AAPL"])
    assert src.last_error is not None and len(src.cache) == 0
    await src.stop()


async def test_add_ticker_wakes_poller():
    src, calls = make_source(lambda r: httpx.Response(200, json=SNAPSHOT), poll_interval=3600)
    await src.start(["AAPL"])
    await src.add_ticker("MSFT")
    for _ in range(50):
        if src.cache.get_price("MSFT"):
            break
        await asyncio.sleep(0.01)
    assert src.cache.get_price("MSFT") == 421.0 and len(calls) == 2
    await src.remove_ticker("MSFT")
    assert "MSFT" not in src.cache and src.get_tickers() == ["AAPL"]
    await src.stop()


async def test_removed_ticker_in_flight_not_reinserted():
    src, _ = make_source(lambda r: httpx.Response(200, json=SNAPSHOT))
    await src.start(["AAPL", "MSFT"])
    await src.remove_ticker("MSFT")
    await src._poll_once()
    assert "MSFT" not in src.cache
    await src.stop()
