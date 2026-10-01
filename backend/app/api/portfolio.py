"""Portfolio endpoints: holdings, market-order trades and value history."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import db
from app.services.portfolio import TradeError, build_portfolio, execute_trade

router = APIRouter(prefix="/api/portfolio")


class TradeRequest(BaseModel):
    ticker: str
    quantity: float
    side: Literal["buy", "sell"]


@router.get("")
def get_portfolio(request: Request) -> dict:
    with db.get_connection() as conn:
        return build_portfolio(conn, request.app.state.price_cache)


@router.post("/trade")
def trade(body: TradeRequest, request: Request) -> dict:
    cache = request.app.state.price_cache
    try:
        with db.get_connection() as conn:
            result = execute_trade(conn, cache, body.ticker, body.side, body.quantity)
            portfolio = build_portfolio(conn, cache)
    except TradeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"trade": result, "portfolio": portfolio}


@router.get("/history")
def history() -> dict:
    with db.get_connection() as conn:
        snapshots = db.list_snapshots(conn)
    return {"snapshots": [{"total_value": s["total_value"], "recorded_at": s["recorded_at"]} for s in snapshots]}
