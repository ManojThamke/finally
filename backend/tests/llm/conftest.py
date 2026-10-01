"""Shared fixtures for LLM/chat tests: temp DB, warm price cache, fake market source."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import chat
from app.market import PriceCache

PRICES = {"AAPL": 190.0, "GOOGL": 175.0, "MSFT": 420.0, "TSLA": 250.0}


class FakeMarketSource:
    """Minimal MarketDataSource stand-in: tracks tickers and warms the cache on add."""

    name = "fake"

    def __init__(self, cache: PriceCache) -> None:
        self.cache = cache
        self.tickers: set[str] = set(PRICES)

    async def add_ticker(self, ticker: str) -> None:
        self.tickers.add(ticker)
        if ticker not in self.cache:
            self.cache.update(ticker, 50.0)

    async def remove_ticker(self, ticker: str) -> None:
        self.tickers.discard(ticker)
        self.cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return sorted(self.tickers)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "finally.db"
    monkeypatch.setenv("FINALLY_DB_PATH", str(path))
    monkeypatch.delenv("LLM_MOCK", raising=False)
    return path


@pytest.fixture
def price_cache() -> PriceCache:
    cache = PriceCache()
    for ticker, price in PRICES.items():
        cache.update(ticker, price)
    return cache


@pytest.fixture
def market_source(price_cache) -> FakeMarketSource:
    return FakeMarketSource(price_cache)


@pytest.fixture
def client(price_cache, market_source):
    app = FastAPI()
    app.state.price_cache = price_cache
    app.state.market_source = market_source
    app.include_router(chat.router)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the network call; set `.reply` (str or Exception) and inspect `.calls`."""

    class Fake:
        reply: str | Exception = '{"message": "ok", "trades": [], "watchlist_changes": []}'
        calls: list[list[dict]] = []

    fake = Fake()
    fake.calls = []

    async def _call(messages):
        fake.calls.append(messages)
        if isinstance(fake.reply, Exception):
            raise fake.reply
        return fake.reply

    monkeypatch.setattr("app.llm.service.call_llm", _call)
    return fake
