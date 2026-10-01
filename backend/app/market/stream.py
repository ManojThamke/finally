"""SSE endpoint: GET /api/stream/prices."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

STREAM_INTERVAL = 0.5     # seconds between cache checks
KEEPALIVE_EVERY = 15.0    # seconds of silence before a comment line is sent

router = APIRouter()


def format_prices_event(cache: PriceCache) -> str:
    payload = {t: u.to_dict() for t, u in sorted(cache.get_all().items())}
    return f"event: prices\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def price_events(
    cache: PriceCache, request: Request | None = None, interval: float = STREAM_INTERVAL
) -> AsyncIterator[str]:
    yield "retry: 1000\n\n"           # EventSource reconnect delay (ms)
    last_version, idle = -1, 0.0
    while request is None or not await request.is_disconnected():
        if cache.version != last_version:
            last_version = cache.version
            idle = 0.0
            yield format_prices_event(cache)
        elif idle >= KEEPALIVE_EVERY:
            idle = 0.0
            yield ": keepalive\n\n"   # keeps proxies from closing an idle connection
        await asyncio.sleep(interval)
        idle += interval


@router.get("/api/stream/prices")
async def stream_prices(request: Request) -> StreamingResponse:
    cache: PriceCache = request.app.state.price_cache
    return StreamingResponse(
        price_events(cache, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
