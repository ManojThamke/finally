import json

import httpx
from fastapi import FastAPI

from app.market import PriceCache, create_market_data_source, stream_router
from app.market.massive_client import MassiveDataSource
from app.market.simulator import SimulatorDataSource
from app.market.stream import format_prices_event, price_events


def test_factory(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)
    monkeypatch.setenv("MASSIVE_API_KEY", "   ")
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)
    monkeypatch.setenv("MASSIVE_API_KEY", "abc")
    assert isinstance(create_market_data_source(PriceCache()), MassiveDataSource)


def test_factory_poll_interval(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "abc")
    monkeypatch.setenv("MASSIVE_POLL_INTERVAL", "3")
    assert create_market_data_source(PriceCache()).poll_interval == 3
    monkeypatch.setenv("MASSIVE_POLL_INTERVAL", "")
    assert create_market_data_source(PriceCache()).poll_interval == 15


async def test_stream_emits_prices_event():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    gen = price_events(cache, interval=0.01)
    assert await anext(gen) == "retry: 1000\n\n"
    frame = await anext(gen)
    assert frame.startswith("event: prices\n")
    data = json.loads(frame.split("data: ", 1)[1])
    assert data["AAPL"]["price"] == 190.0
    cache.update("AAPL", 191.0)
    data = json.loads((await anext(gen)).split("data: ", 1)[1])
    assert data["AAPL"]["direction"] == "up"
    await gen.aclose()


async def test_stream_sends_keepalive_when_idle(monkeypatch):
    monkeypatch.setattr("app.market.stream.KEEPALIVE_EVERY", 0.02)
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    gen = price_events(cache, interval=0.01)
    await anext(gen)
    await anext(gen)  # initial frame
    assert await anext(gen) == ": keepalive\n\n"
    await gen.aclose()


def test_format_prices_event_is_sorted_json():
    cache = PriceCache()
    cache.update("MSFT", 420.0)
    cache.update("AAPL", 190.0)
    frame = format_prices_event(cache)
    assert frame.endswith("\n\n")
    assert list(json.loads(frame.split("data: ", 1)[1])) == ["AAPL", "MSFT"]


async def test_sse_route_over_http():
    app = FastAPI()
    app.include_router(stream_router)
    app.state.price_cache = PriceCache()
    app.state.price_cache.update("AAPL", 190.0)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream("GET", "/api/stream/prices") as resp:
            assert resp.headers["content-type"].startswith("text/event-stream")
            assert resp.headers["cache-control"] == "no-cache"
            body = ""
            async for chunk in resp.aiter_text():
                body += chunk
                if "event: prices" in body and body.endswith("\n\n"):
                    break
    assert body.startswith("retry: 1000")
    data = json.loads(body.split("data: ", 1)[1])
    assert data["AAPL"]["price"] == 190.0
