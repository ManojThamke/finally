import pytest

from app import db
from app.market import PriceCache
from app.market.simulator import SimulatorDataSource
from app.services.portfolio import execute_trade
from app.services.watchlist import (
    InvalidTickerError,
    add_ticker,
    list_watchlist_with_prices,
    remove_ticker,
    tracked_tickers,
    validate_ticker,
)


@pytest.fixture
def source():
    return SimulatorDataSource(PriceCache(), seed=1)


@pytest.mark.parametrize("raw", [" pypl ", "BRK.B", "x"])
def test_validate_ticker_ok(raw):
    assert validate_ticker(raw) == raw.strip().upper()


@pytest.mark.parametrize("raw", ["", "   ", "AB1", "TOOLONGTICKER", "A-B", None])
def test_validate_ticker_rejects(raw):
    with pytest.raises(InvalidTickerError):
        validate_ticker(raw)


async def test_add_ticker_updates_db_and_source(conn, source):
    assert await add_ticker(conn, source, "pypl") is True
    assert "PYPL" in db.list_watchlist(conn)
    assert "PYPL" in source.get_tickers()
    assert source.cache.get_price("PYPL") is not None
    assert await add_ticker(conn, source, "PYPL") is False


async def test_remove_ticker(conn, source):
    await add_ticker(conn, source, "PYPL")
    assert await remove_ticker(conn, source, "pypl") is True
    assert "PYPL" not in db.list_watchlist(conn)
    assert "PYPL" not in source.get_tickers()
    assert await remove_ticker(conn, source, "PYPL") is False


async def test_remove_keeps_streaming_held_ticker(conn, source):
    await add_ticker(conn, source, "PYPL")
    execute_trade(conn, source.cache, "PYPL", "buy", 1)
    assert await remove_ticker(conn, source, "PYPL") is True
    assert "PYPL" in source.get_tickers()


async def test_list_with_prices_and_tracked(conn, source):
    await source.add_ticker("AAPL")
    rows = list_watchlist_with_prices(conn, source.cache)
    assert [r["ticker"] for r in rows] == list(db.DEFAULT_TICKERS)
    aapl = rows[0]
    assert aapl["price"] is not None and aapl["direction"] == "flat"
    assert set(aapl) == {"ticker", "price", "previous_price", "change", "change_percent",
                         "day_change_percent", "direction"}
    assert rows[1]["price"] is None  # not streamed yet

    await add_ticker(conn, source, "PYPL")
    execute_trade(conn, source.cache, "PYPL", "buy", 1)
    db.remove_watchlist_ticker(conn, "PYPL")
    assert set(tracked_tickers(conn)) == set(db.DEFAULT_TICKERS) | {"PYPL"}
