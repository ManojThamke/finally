"""Watchlist endpoints. Changes are mirrored into the live market data source."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import db
from app.market import normalize_ticker
from app.services import watchlist as service

router = APIRouter(prefix="/api/watchlist")


class AddTickerRequest(BaseModel):
    ticker: str


@router.get("")
def get_watchlist(request: Request) -> dict:
    with db.get_connection() as conn:
        return {"tickers": service.list_watchlist_with_prices(conn, request.app.state.price_cache)}


@router.post("", status_code=201)
async def add_ticker(body: AddTickerRequest, request: Request) -> dict:
    try:
        ticker = service.validate_ticker(body.ticker)
    except service.InvalidTickerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    with db.get_connection() as conn:
        added = await service.add_ticker(conn, request.app.state.market_source, ticker)
    if not added:
        raise HTTPException(status_code=409, detail=f"{ticker} is already in the watchlist")
    return {"ticker": ticker, "added": True}


@router.delete("/{ticker}")
async def remove_ticker(ticker: str, request: Request) -> dict:
    ticker = normalize_ticker(ticker)
    with db.get_connection() as conn:
        removed = await service.remove_ticker(conn, request.app.state.market_source, ticker)
    if not removed:
        raise HTTPException(status_code=404, detail=f"{ticker} is not in the watchlist")
    return {"ticker": ticker, "removed": True}
