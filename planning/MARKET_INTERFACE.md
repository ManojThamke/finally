# Market Data Interface: Unified Python API

This document defines the single Python API that all FinAlly backend code uses to get stock prices. If `MASSIVE_API_KEY` is set, the data comes from the Massive REST API (see `MASSIVE_API.md`). Otherwise, it comes from the built-in simulator (see `MARKET_SIMULATOR.md`). Nothing outside `app/market/` knows or cares which source is active.

---

## 1. Design goals

- **One interface, two producers.** `SimulatorDataSource` and `MassiveDataSource` both implement `MarketDataSource`.
- **Push into a cache, read from the cache.** Producers write to a shared in-memory `PriceCache`. Consumers (the SSE stream, portfolio valuation, trade execution, LLM context) only *read* the cache. No consumer ever awaits a network call to get a price.
- **Dynamic ticker set.** The watchlist changes at runtime, so sources support `add_ticker` / `remove_ticker`.
- **Async-native.** Each source runs as one asyncio background task started in the FastAPI lifespan.
- **Testable.** Pure functions for parsing and math, an injectable clock and RNG, and no hidden globals beyond the app-level singleton.

```
                ┌───────────────────────────────┐
  env var ───►  │ create_market_data_source()   │
                └──────────────┬────────────────┘
                               │ returns one of
             ┌─────────────────┴──────────────────┐
             ▼                                    ▼
  SimulatorDataSource                     MassiveDataSource
  (GBM tick every 0.5 s)                  (REST poll every 15 s)
             │  cache.update(...)                 │
             └─────────────────┬──────────────────┘
                               ▼
                         PriceCache (in-memory, thread-safe)
                               │ read-only
        ┌──────────────┬───────┴────────┬────────────────┐
        ▼              ▼                ▼                ▼
  SSE /api/stream  /api/portfolio  trade execution   LLM chat context
```

---

## 2. Module layout

```
backend/app/market/
├── __init__.py          # Public exports (see §9)
├── models.py            # PriceUpdate dataclass
├── cache.py             # PriceCache
├── interface.py         # MarketDataSource ABC
├── seed_prices.py       # Seed prices + per-ticker GBM params + sector map
├── simulator.py         # GBMSimulator (math) + SimulatorDataSource (async task)
├── massive_client.py    # MassiveDataSource (REST poller) + parse helpers
├── factory.py           # create_market_data_source()
└── stream.py            # SSE router: GET /api/stream/prices
```

---

## 3. `PriceUpdate` (models.py)

This is the immutable record for one ticker's latest price. It is the unit stored in the cache and sent over SSE.

```python
from __future__ import annotations
from dataclasses import dataclass, field
import time


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    ticker: str
    price: float
    previous_price: float          # price from the previous update (tick-to-tick)
    timestamp: float = field(default_factory=time.time)  # unix seconds
    session_open: float | None = None  # reference for "daily change %" (prev close or first price seen)

    @property
    def change(self) -> float:
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def direction(self) -> str:
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    @property
    def day_change_percent(self) -> float:
        ref = self.session_open or self.previous_price
        return round((self.price - ref) / ref * 100, 4) if ref else 0.0

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "day_change_percent": self.day_change_percent,
            "direction": self.direction,
        }
```

`direction` and `change` are tick-to-tick values that drive the green/red flash. `day_change_percent` drives the watchlist's "daily change %" column. For Massive it is relative to `prevDay.c`. For the simulator it is relative to the seed price.

---

## 4. `PriceCache` (cache.py)

```python
import threading
import time
from .models import PriceUpdate


class PriceCache:
    """Latest price per ticker. Written by one producer, read by many consumers."""

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = threading.Lock()
        self._version = 0  # bumps on every write; lets SSE skip unchanged frames

    def update(self, ticker: str, price: float, timestamp: float | None = None,
               session_open: float | None = None) -> PriceUpdate:
        price = round(float(price), 2)
        with self._lock:
            prev = self._prices.get(ticker)
            update = PriceUpdate(
                ticker=ticker,
                price=price,
                previous_price=prev.price if prev else price,
                timestamp=timestamp or time.time(),
                session_open=session_open or (prev.session_open if prev else price),
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        with self._lock:
            return self._prices.get(ticker)

    def get_price(self, ticker: str) -> float | None:
        u = self.get(ticker)
        return u.price if u else None

    def get_all(self) -> dict[str, PriceUpdate]:
        with self._lock:
            return dict(self._prices)

    def remove(self, ticker: str) -> None:
        with self._lock:
            if self._prices.pop(ticker, None) is not None:
                self._version += 1

    @property
    def version(self) -> int:
        return self._version

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices
```

A `threading.Lock` (not an `asyncio.Lock`) is used because the Massive client does its HTTP work in `asyncio.to_thread`, and cheap sync reads are convenient from any context. All critical sections are tiny.

---

## 5. `MarketDataSource` (interface.py)

```python
from abc import ABC, abstractmethod
from .cache import PriceCache


class MarketDataSource(ABC):
    """Produces prices for a dynamic set of tickers and writes them into a PriceCache."""

    def __init__(self, cache: PriceCache) -> None:
        self.cache = cache

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Seed the initial tickers and launch the background task. Returns promptly."""

    @abstractmethod
    async def stop(self) -> None:
        """Cancel the background task and release resources. Idempotent."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Start producing prices for `ticker`. No-op if already tracked."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop producing prices for `ticker` and drop it from the cache."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Tickers currently being tracked."""

    @property
    @abstractmethod
    def name(self) -> str:
        """'simulator' or 'massive' (exposed in /api/health)."""
```

### Contract

| Rule | Detail |
|---|---|
| Ticker normalization | Callers pass uppercase, stripped symbols. Sources may defensively `.upper().strip()`. |
| First price | `SimulatorDataSource.add_ticker` writes a price to the cache **immediately**, so a new watchlist row has a price right away. `MassiveDataSource.add_ticker` triggers an out-of-cycle fetch (best effort). |
| `start()` | Must not block for long. It may do one initial fetch or tick so the cache isn't empty when the first SSE client connects. |
| Failures | A source never raises out of its background loop. It logs, keeps the last prices, and retries. |
| Removal | `remove_ticker` also calls `cache.remove(ticker)` so it disappears from SSE. |
| Positions | Tickers held in a position but not on the watchlist **must still be tracked** so P&L stays live. The caller (watchlist service) is responsible for this: only call `remove_ticker` when the ticker is neither watched nor held. |

---

## 6. Implementations (summary)

### SimulatorDataSource (simulator.py)

This class wraps a pure `GBMSimulator`. Its loop is: every `0.5 s`, call `sim.step()`, then call `cache.update(t, p)` for every ticker. Full details are in `MARKET_SIMULATOR.md`.

### MassiveDataSource (massive_client.py)

```python
import asyncio
import logging
import os
import time
from datetime import date, timedelta

from massive import RESTClient
from massive.exceptions import BadResponse

from .cache import PriceCache
from .interface import MarketDataSource

log = logging.getLogger(__name__)


def pick_price(snap) -> float | None:
    """Price selection rule from MASSIVE_API.md §3."""
    for candidate in (
        getattr(snap.last_trade, "price", None) if snap.last_trade else None,
        getattr(snap.min, "close", None) if snap.min else None,
        getattr(snap.day, "close", None) if snap.day else None,
        getattr(snap.prev_day, "close", None) if snap.prev_day else None,
    ):
        if candidate:
            return float(candidate)
    return None


class MassiveDataSource(MarketDataSource):
    EOD_INTERVAL = 300.0  # free tier: refresh end-of-day data every 5 min

    def __init__(self, cache: PriceCache, api_key: str, poll_interval: float = 15.0) -> None:
        super().__init__(cache)
        self._client = RESTClient(api_key=api_key)
        self._interval = poll_interval
        self._tickers: set[str] = set()
        self._task: asyncio.Task | None = None
        self._mode = "live"  # "live" (snapshot) | "eod" (grouped daily, free tier)
        self._backoff = 0.0

    name = "massive"

    async def start(self, tickers: list[str]) -> None:
        self._tickers = {t.upper() for t in tickers}
        await self._poll_once()  # probe: decides live vs eod and warms the cache
        self._task = asyncio.create_task(self._run(), name="massive-poller")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.upper()
        if ticker not in self._tickers:
            self._tickers.add(ticker)
            if self._mode == "live":
                await self._poll_once()  # give the new row a price now

    async def remove_ticker(self, ticker: str) -> None:
        self._tickers.discard(ticker.upper())
        self.cache.remove(ticker.upper())

    def get_tickers(self) -> list[str]:
        return sorted(self._tickers)

    async def _run(self) -> None:
        while True:
            interval = self._interval if self._mode == "live" else self.EOD_INTERVAL
            await asyncio.sleep(interval + self._backoff)
            await self._poll_once()

    async def _poll_once(self) -> None:
        if not self._tickers:
            return
        try:
            if self._mode == "live":
                await self._poll_snapshot()
            else:
                await self._poll_eod()
            self._backoff = 0.0
        except BadResponse as e:
            msg = str(e)
            if "NOT_AUTHORIZED" in msg or "403" in msg:
                log.warning("Massive plan has no snapshot access; switching to end-of-day prices")
                self._mode = "eod"
                await self._poll_eod()
            elif "429" in msg:
                self._backoff = min(max(self._backoff * 2, self._interval), 60.0)
                log.warning("Massive rate limited; backing off %.0fs", self._backoff)
            else:
                log.error("Massive request failed: %s", msg)
        except Exception:
            log.exception("Massive poll failed; keeping last prices")

    async def _poll_snapshot(self) -> None:
        tickers = sorted(self._tickers)
        snaps = await asyncio.to_thread(self._client.get_snapshot_all, "stocks", tickers=tickers)
        now = time.time()
        for s in snaps:
            price = pick_price(s)
            if price is not None and s.ticker in self._tickers:
                prev_close = s.prev_day.close if s.prev_day and s.prev_day.close else None
                self.cache.update(s.ticker, price, timestamp=now, session_open=prev_close)

    async def _poll_eod(self) -> None:
        closes = await asyncio.to_thread(self._latest_grouped_daily)
        now = time.time()
        for ticker, close in closes.items():
            self.cache.update(ticker, close, timestamp=now)

    def _latest_grouped_daily(self) -> dict[str, float]:
        d = date.today()
        for _ in range(7):
            bars = self._client.get_grouped_daily_aggs(d.isoformat(), adjusted=True)
            if bars:
                return {b.ticker: b.close for b in bars if b.ticker in self._tickers}
            d -= timedelta(days=1)
        return {}
```

Notes:
- Each poll makes **one** network call for all tickers (snapshot or grouped daily), regardless of watchlist size.
- `pick_price` is a pure function. Unit-test it with fake snapshot objects (`types.SimpleNamespace`).
- In tests, inject a fake client by replacing `source._client` with a stub that has `get_snapshot_all` / `get_grouped_daily_aggs`.

---

## 7. Factory (factory.py)

```python
import logging
import os
from .cache import PriceCache
from .interface import MarketDataSource

log = logging.getLogger(__name__)


def create_market_data_source(cache: PriceCache) -> MarketDataSource:
    api_key = os.getenv("MASSIVE_API_KEY", "").strip()
    if api_key:
        from .massive_client import MassiveDataSource  # lazy: simulator users don't need the package loaded
        interval = float(os.getenv("MASSIVE_POLL_INTERVAL", "15"))
        log.info("Market data: Massive API (poll every %ss)", interval)
        return MassiveDataSource(cache, api_key=api_key, poll_interval=interval)

    from .simulator import SimulatorDataSource
    log.info("Market data: built-in simulator")
    return SimulatorDataSource(cache)
```

| Env var | Default | Effect |
|---|---|---|
| `MASSIVE_API_KEY` | empty | Non-empty → Massive. Empty or absent → simulator. |
| `MASSIVE_POLL_INTERVAL` | `15` | Seconds between snapshot polls (live mode only) |
| `SIM_TICK_INTERVAL` | `0.5` | Seconds between simulator ticks |
| `SIM_SEED` | unset | Integer RNG seed for deterministic simulator runs (tests) |

---

## 8. SSE stream (stream.py)

```python
import asyncio
import json
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

STREAM_INTERVAL = 0.5


def create_stream_router(cache: PriceCache) -> APIRouter:
    router = APIRouter()

    @router.get("/api/stream/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        async def gen():
            yield "retry: 1000\n\n"  # EventSource reconnect delay
            last_version = -1
            while not await request.is_disconnected():
                if cache.version != last_version:
                    last_version = cache.version
                    payload = {t: u.to_dict() for t, u in cache.get_all().items()}
                    yield f"event: prices\ndata: {json.dumps(payload)}\n\n"
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(STREAM_INTERVAL)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
```

Each event is one JSON object keyed by ticker. It contains every tracked ticker and is sent only when the cache changed:

```
event: prices
data: {"AAPL": {"ticker": "AAPL", "price": 191.23, "previous_price": 191.18, "timestamp": 1759300000.5,
                "change": 0.05, "change_percent": 0.0262, "day_change_percent": 0.65, "direction": "up"}, ...}
```

Frontend: `new EventSource("/api/stream/prices").addEventListener("prices", e => ...)`. Sending the full set each frame keeps the client trivial: it needs no diffing logic and no replay after a reconnect. Because the frontend already receives every ticker's latest price on each frame, it can derive the flash from `direction`.

---

## 9. Wiring into FastAPI (main.py)

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.market import PriceCache, create_market_data_source, create_stream_router
from app.db import get_watchlist_tickers, get_position_tickers  # backend's DB layer


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache = PriceCache()
    source = create_market_data_source(cache)
    tickers = sorted(set(get_watchlist_tickers()) | set(get_position_tickers()))
    await source.start(tickers)
    app.state.price_cache = cache
    app.state.market = source
    app.include_router(create_stream_router(cache))
    yield
    await source.stop()


app = FastAPI(lifespan=lifespan)
```

`app/market/__init__.py` exports:

```python
from .models import PriceUpdate
from .cache import PriceCache
from .interface import MarketDataSource
from .factory import create_market_data_source
from .stream import create_stream_router

__all__ = ["PriceUpdate", "PriceCache", "MarketDataSource",
           "create_market_data_source", "create_stream_router"]
```

### How other features use it

| Feature | Call |
|---|---|
| `POST /api/watchlist` | Insert the DB row, then `await app.state.market.add_ticker(t)` |
| `DELETE /api/watchlist/{t}` | Delete the DB row, then call `remove_ticker(t)` **only if no open position** |
| `POST /api/portfolio/trade` | `price = cache.get_price(t)`. If `None`, return 400 "no price available for t". A buy of an untracked ticker should `add_ticker` first. |
| `GET /api/portfolio` | Value each position with `cache.get_price` (fall back to `avg_cost` if missing) |
| `GET /api/watchlist` | Join DB tickers with `cache.get(t).to_dict()` |
| LLM chat context | `cache.get_all()` → compact text table |
| `GET /api/health` | `{"status": "ok", "market_source": app.state.market.name}` |
| Snapshot task (30 s) | Total value = cash + Σ qty × `cache.get_price` |

---

## 10. Testing checklist

- `PriceCache`: first update has `previous_price == price` and direction `flat`. Subsequent updates set direction correctly. `remove` bumps the version.
- `PriceUpdate.to_dict` has the exact keys the frontend expects.
- Factory: env set → `MassiveDataSource`, env empty/whitespace → `SimulatorDataSource` (use `monkeypatch.setenv/delenv`).
- `pick_price`: falls through `last_trade → min → day → prev_day` and returns `None` when all are empty.
- `MassiveDataSource` with a stub client: a snapshot populates the cache. A `BadResponse("403 NOT_AUTHORIZED")` switches to `eod` mode and populates from grouped daily. Generic exceptions keep old prices.
- Both sources: `add_ticker` / `remove_ticker` update `get_tickers()` and the cache, and `stop()` is idempotent.
- SSE: with `httpx.AsyncClient` + `ASGITransport`, read the first `prices` event and assert it parses as JSON.
