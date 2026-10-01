"""Temporary dev server: runs the market data simulator and its SSE stream.

Stand-in until the full FastAPI app (portfolio, watchlist, chat, static frontend) exists.
Run from backend/:  uvicorn dev_server:app --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.market import PriceCache, create_market_data_source, stream_router

DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.price_cache = PriceCache()
    app.state.market_source = create_market_data_source(app.state.price_cache)
    await app.state.market_source.start(DEFAULT_TICKERS)
    yield
    await app.state.market_source.stop()


app = FastAPI(title="FinAlly dev server", lifespan=lifespan)
app.include_router(stream_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", **app.state.market_source.status()}
