"""FinAlly FastAPI app: API routers, SSE stream, background tasks and the static frontend.

Run from backend/:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parents[1]
# Real environment variables win over the repo-root .env (Docker passes --env-file).
load_dotenv(_BACKEND_DIR.parent / ".env", override=False)

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402

from app import db  # noqa: E402
from app.api import chat, health, portfolio, watchlist  # noqa: E402
from app.llm import warm_up  # noqa: E402
from app.market import PriceCache, create_market_data_source, stream_router  # noqa: E402
from app.services.portfolio import record_snapshot  # noqa: E402
from app.services.watchlist import tracked_tickers  # noqa: E402

log = logging.getLogger(__name__)

SNAPSHOT_INTERVAL = float(os.getenv("SNAPSHOT_INTERVAL", "30"))


def _take_snapshot(price_cache: PriceCache) -> None:
    with db.get_connection() as conn:
        record_snapshot(conn, price_cache)


async def _snapshot_loop(price_cache: PriceCache, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(_take_snapshot, price_cache)
        except Exception:
            log.exception("Portfolio snapshot failed")  # never let the loop die


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    with db.get_connection() as conn:
        tickers = tracked_tickers(conn)

    app.state.price_cache = PriceCache()
    app.state.market_source = create_market_data_source(app.state.price_cache)
    await app.state.market_source.start(tickers)
    snapshot_task = asyncio.create_task(
        _snapshot_loop(app.state.price_cache, SNAPSHOT_INTERVAL), name="portfolio-snapshots"
    )
    # Pre-import litellm in the background so the first chat doesn't pay for it.
    warm_task = asyncio.create_task(warm_up(), name="llm-warm-up")
    try:
        yield
    finally:
        for task in (snapshot_task, warm_task):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await app.state.market_source.stop()


app = FastAPI(title="FinAlly", lifespan=lifespan)
app.include_router(health.router)
app.include_router(stream_router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(chat.router)


# --- static frontend (Next.js export) ---------------------------------------

def static_dir() -> Path:
    env = os.getenv("FINALLY_STATIC_DIR", "").strip()
    return Path(env).resolve() if env else _BACKEND_DIR / "static"


def _resolve_static(root: Path, path: str) -> Path | None:
    """Map a URL path to an exported file: exact file, `foo.html`, `foo/index.html`, else SPA index.

    Missing assets (paths with a file extension, e.g. `/_next/x.js`) 404 instead of getting HTML.
    """
    path = path.strip("/")
    candidates = [root / path, root / f"{path}.html", root / path / "index.html"] if path else []
    if not Path(path).suffix:
        candidates.append(root / "index.html")
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate.is_file() and candidate.is_relative_to(root):
            return candidate
    return None


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str) -> FileResponse:
    if path == "api" or path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    root = static_dir()
    file = _resolve_static(root, path) if root.is_dir() else None
    if file is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(file)
