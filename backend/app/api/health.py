"""GET /api/health: liveness plus market data source diagnostics."""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/health")
def health(request: Request) -> dict:
    return {"status": "ok", **request.app.state.market_source.status()}
