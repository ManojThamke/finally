# Market Data Backend — Detailed Design

**Status:** Implementation-ready design. **Owner:** Backend / Market Data agent.
**Inputs:** `PLAN.md` §6 (requirements), `MARKET_INTERFACE.md` (unified API), `MARKET_SIMULATOR.md` (GBM approach), `MASSIVE_API.md` (Massive REST reference).

This document is the build guide for `backend/app/market/`. The three earlier docs describe the *what*. This one gives the complete *how*: every module as working code, the wire format for the frontend, the FastAPI wiring, and the test suite. All code below has been run: the tests in §13 pass (23 tests) and the SSE endpoint was checked against a live uvicorn server. Copy the code blocks into the paths in their headers.

Where this design differs from the earlier docs, it says why. The differences are listed together in §14.

---

## Contents

1. [Requirements](#1-requirements)
2. [Architecture](#2-architecture)
3. [Module layout and dependencies](#3-module-layout-and-dependencies)
4. [Data model: `PriceUpdate`](#4-data-model-priceupdate)
5. [`PriceCache`](#5-pricecache)
6. [Unified interface: `MarketDataSource`](#6-unified-interface-marketdatasource)
7. [Simulator](#7-simulator)
8. [Massive API client](#8-massive-api-client)
9. [Factory and configuration](#9-factory-and-configuration)
10. [SSE stream](#10-sse-stream)
11. [Package exports](#11-package-exports)
12. [Integration with the rest of the backend](#12-integration-with-the-rest-of-the-backend)
13. [Tests](#13-tests)
14. [Design decisions and changes from earlier docs](#14-design-decisions-and-changes-from-earlier-docs)
15. [Implementation checklist](#15-implementation-checklist)

---

## 1. Requirements

| # | Requirement (PLAN.md) | Where it is met |
|---|---|---|
| R1 | One interface, two implementations, chosen by `MASSIVE_API_KEY` | §6 `MarketDataSource`, §9 factory |
| R2 | Simulator: GBM with per-ticker drift/vol, ~500 ms ticks | §7 `GBMSimulator`, `SimulatorDataSource` |
| R3 | Simulator: correlated moves (tech together) | §7.2 sector correlation + Cholesky |
| R4 | Simulator: occasional 2–5% events | §7.3 |
| R5 | Simulator: realistic seed prices | §7.4 `seed_prices.py` |
| R6 | Massive: REST polling of the union of watched tickers, configurable interval (15 s free, 2–15 s paid) | §8 `MassiveDataSource` |
| R7 | Massive output has the same shape as the simulator's | Both write `PriceCache.update()` → `PriceUpdate` |
| R8 | Shared in-memory cache: latest price, previous price, timestamp | §5 `PriceCache` |
| R9 | `GET /api/stream/prices` SSE, ~500 ms cadence, ticker/price/prev/timestamp/direction | §10 |
| R10 | Client reconnects automatically | `retry:` field + full snapshot each frame (§10) |
| R11 | Watchlist changes at runtime | `add_ticker` / `remove_ticker` on both sources |
| R12 | Unit tests: valid prices, GBM math, Massive parsing, interface conformance | §13 |

Non-goals: order books, intraday history storage, historical backfill for charts (the frontend builds sparklines from the stream), Massive WebSockets.

---

## 2. Architecture

```
                     MASSIVE_API_KEY set?
                            │
              ┌─────────────┴──────────────┐
              ▼ no                         ▼ yes
   ┌──────────────────────┐    ┌──────────────────────────┐
   │ SimulatorDataSource  │    │ MassiveDataSource        │
   │  └ GBMSimulator      │    │  └ httpx.AsyncClient     │
   │ asyncio task, 0.5 s  │    │ asyncio task, 15 s / 5 m │
   └──────────┬───────────┘    └────────────┬─────────────┘
              │ cache.update(ticker, price, ...)   (single writer)
              └──────────────┬──────────────┘
                             ▼
                  ┌─────────────────────┐
                  │     PriceCache      │  dict[ticker → PriceUpdate] + version
                  └──────────┬──────────┘
                             │ read-only: get / get_price / get_all / version
     ┌───────────────┬───────┴────────┬─────────────────┬──────────────────┐
     ▼               ▼                ▼                 ▼                  ▼
 SSE stream    GET /api/portfolio  trade execution  LLM chat context  snapshot task (30 s)
 (per client)  GET /api/watchlist
```

### Key principles

1. **Producers push, consumers read.** No request handler ever awaits a network call to get a price. Reading a price costs a dict lookup under a lock.
2. **One writer.** Exactly one background task writes to the cache. `add_ticker` and `remove_ticker` run on the same event loop, so the source's internal state never changes in the middle of a tick.
3. **Source-agnostic downstream.** Code outside `app/market/` imports only from `app.market` (§11) and never checks which source is active, except to show `status()` in `/api/health`.
4. **Failures never escape the loop.** Network errors, bad JSON and rate limits are logged, the last good prices stay in the cache, and the next cycle retries.
5. **Testable by construction.** The math (`GBMSimulator`) and the parsing (`parse_snapshot`, ...) are pure functions or classes. The network is injected (`httpx.MockTransport`). The RNG is seedable and "today" is injectable.

### Concurrency model

| Actor | Runs on | Touches |
|---|---|---|
| Simulator / Massive loop | asyncio task (event loop) | writes cache |
| `add_ticker` / `remove_ticker` | awaited from route handlers (event loop) | source state + cache |
| SSE generators (one per browser tab) | event loop | read cache every 0.5 s |
| Sync `def` route handlers, if any | FastAPI threadpool | read cache |

The cache uses a `threading.Lock` (not `asyncio.Lock`) so the threadpool readers are safe too. Every critical section is a few dict operations, so the lock is never contended in practice.

### Lifecycle

```
uvicorn start
  └ lifespan()
      ├ cache  = PriceCache()
      ├ source = create_market_data_source(cache)        # env decides
      ├ await source.start(watchlist ∪ position tickers) # warms cache, spawns task
      ├ yield  ──── app serves requests ────
      └ await source.stop()                              # cancels task, closes HTTP client
```

---

## 3. Module layout and dependencies

```
backend/
├── pyproject.toml                # + numpy, httpx (fastapi/uvicorn already present)
├── app/
│   ├── main.py                   # lifespan wiring (§12)
│   └── market/
│       ├── __init__.py           # public API (§11)
│       ├── models.py             # PriceUpdate                     (§4)
│       ├── cache.py              # PriceCache                      (§5)
│       ├── interface.py          # MarketDataSource ABC            (§6)
│       ├── seed_prices.py        # seeds, GBM params, sectors      (§7.4)
│       ├── simulator.py          # GBMSimulator, SimulatorDataSource (§7)
│       ├── massive_client.py     # parse helpers, MassiveDataSource (§8)
│       ├── factory.py            # create_market_data_source       (§9)
│       └── stream.py             # SSE router                      (§10)
└── tests/
    └── market/
        ├── test_cache.py
        ├── test_simulator.py
        ├── test_massive.py
        └── test_factory_and_stream.py
```

```bash
cd backend
uv add numpy httpx
uv add --dev pytest pytest-asyncio
```

`pyproject.toml` test settings (lets `async def test_...` run without decorators):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

The official `massive` Python package is **not** a dependency. See §14 for why httpx is used instead.

---

## 4. Data model: `PriceUpdate`

`PriceUpdate` is the immutable record for one ticker's latest price. The cache stores it, the SSE stream sends it, and every consumer reads it.

```python
# backend/app/market/models.py
"""Immutable price record shared by the cache, the SSE stream and every consumer."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

Direction = Literal["up", "down", "flat"]


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    ticker: str
    price: float
    previous_price: float                      # price of the previous update (tick-to-tick)
    session_open: float                        # reference for "daily change %"
    timestamp: float = field(default_factory=time.time)  # unix seconds

    @property
    def change(self) -> float:
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        if not self.previous_price:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def day_change_percent(self) -> float:
        if not self.session_open:
            return 0.0
        return round((self.price - self.session_open) / self.session_open * 100, 4)

    @property
    def direction(self) -> Direction:
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "session_open": self.session_open,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "day_change_percent": self.day_change_percent,
            "direction": self.direction,
        }
```

### Field semantics

| Field | Meaning | Drives |
|---|---|---|
| `price` | Latest price, rounded to cents | Everything |
| `previous_price` | Price of the previous update for this ticker. Equals `price` on the first update. | Flash direction |
| `session_open` | Reference for "daily change". Massive: yesterday's close (`prevDay.c`). Simulator: the seed price, which is the price when the app started or when the ticker was added. | Watchlist "change %" column |
| `timestamp` | Unix seconds (float) when the cache received the price | Chart x-axis |
| `change`, `change_percent` | Tick-to-tick move | Optional tooltip |
| `day_change_percent` | `(price − session_open) / session_open × 100` | Watchlist "change %" column |
| `direction` | `"up"` / `"down"` / `"flat"` | Green/red flash CSS class |

### JSON contract (one ticker)

This is the exact shape inside each SSE frame and in `GET /api/watchlist` rows. The frontend can rely on it.

```json
{
  "ticker": "AAPL",
  "price": 191.23,
  "previous_price": 191.18,
  "session_open": 190.0,
  "timestamp": 1790831225.69,
  "change": 0.05,
  "change_percent": 0.0262,
  "day_change_percent": 0.6474,
  "direction": "up"
}
```

---

## 5. `PriceCache`

```python
# backend/app/market/cache.py
"""In-memory latest-price store. One producer writes, many consumers read."""
from __future__ import annotations

import threading
import time

from .models import PriceUpdate


class PriceCache:
    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = threading.Lock()
        self._version = 0  # bumps on every write; SSE uses it to skip unchanged frames

    def update(
        self,
        ticker: str,
        price: float,
        *,
        timestamp: float | None = None,
        session_open: float | None = None,
    ) -> PriceUpdate:
        """Record a new price. previous_price/session_open are carried over automatically."""
        ticker = ticker.upper().strip()
        price = round(float(price), 2)
        with self._lock:
            prev = self._prices.get(ticker)
            if session_open is None:
                session_open = prev.session_open if prev else price
            update = PriceUpdate(
                ticker=ticker,
                price=price,
                previous_price=prev.price if prev else price,
                session_open=round(float(session_open), 2),
                timestamp=timestamp if timestamp is not None else time.time(),
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        with self._lock:
            return self._prices.get(ticker.upper())

    def get_price(self, ticker: str) -> float | None:
        update = self.get(ticker)
        return update.price if update else None

    def get_all(self) -> dict[str, PriceUpdate]:
        with self._lock:
            return dict(self._prices)

    def remove(self, ticker: str) -> None:
        with self._lock:
            if self._prices.pop(ticker.upper(), None) is not None:
                self._version += 1

    @property
    def version(self) -> int:
        return self._version

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker.upper() in self._prices

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)
```

### Behaviour

| Call | Effect |
|---|---|
| `update("aapl", 190.004)` (first time) | Stores `AAPL @ 190.0`, `previous_price = 190.0`, `session_open = 190.0`, `direction = "flat"` |
| `update("AAPL", 191.0)` | `previous_price = 190.0`, `direction = "up"`, `session_open` carried over (`190.0`) |
| `update("AAPL", 191.0, session_open=189.5)` | Overrides the daily reference (Massive passes `prevDay.c` every poll) |
| `remove("AAPL")` | Drops the ticker. Bumps `version` only if it existed. |
| `version` | Increases on every write. The SSE stream sends a frame only when it changed. |

Rounding to cents happens here, in one place. The simulator keeps full float precision internally, so a tiny move that rounds to the same cent shows as `flat`. That looks realistic.

---

## 6. Unified interface: `MarketDataSource`

```python
# backend/app/market/interface.py
"""The one abstraction every market data producer implements."""
from __future__ import annotations

from abc import ABC, abstractmethod

from .cache import PriceCache


class MarketDataSource(ABC):
    """Produces prices for a dynamic set of tickers and writes them into a PriceCache.

    Consumers never call a source to *get* a price - they read the cache. The source
    API is only about lifecycle and which tickers to track.
    """

    name: str  # "simulator" | "massive"

    def __init__(self, cache: PriceCache) -> None:
        self.cache = cache

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Track `tickers`, warm the cache, and launch the background task. Returns promptly."""

    @abstractmethod
    async def stop(self) -> None:
        """Cancel the background task and release resources. Idempotent."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Start tracking `ticker`. No-op if already tracked."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking `ticker` and drop it from the cache. No-op if unknown."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Tickers currently tracked, sorted."""

    def status(self) -> dict:
        """Diagnostics for GET /api/health. Subclasses extend this."""
        return {"source": self.name, "tickers": len(self.get_tickers()), "healthy": True}


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()
```

### Contract (both implementations must obey)

| Rule | Simulator | Massive |
|---|---|---|
| `start(tickers)` returns promptly and leaves the cache warm | Writes seed prices synchronously, then spawns the tick task | One probe request (≤10 s timeout) decides live vs. EOD mode, then spawns the poll task. A failed probe still returns, with an empty cache. |
| `start` is safe to call with `[]` | ✓ | ✓ (no request is made while there are no tickers) |
| `add_ticker` gives the new row a price quickly | Immediately (seed price) | Live mode: wakes the poller, so the price arrives after one request (~100–300 ms). EOD mode: served from the cached full-market closes with no request. |
| `remove_ticker` drops it from the cache | ✓ | ✓ |
| Tickers are normalized to upper case | ✓ `normalize_ticker` | ✓ |
| `stop()` is idempotent | ✓ | ✓ (also closes the HTTP client) |
| Loop never dies on errors | `try/except` per tick | per-poll error handling (§8.4) |
| Unknown ticker | Generated seed price ($50–$300, stable per symbol) | Missing from the response, so no price. Trades on it get a 400 (§12). |
| `status()` | `{source, tickers, healthy, ticks, speed}` | `{source, tickers, healthy, mode, last_success, last_error}` |

**Ownership rule for tracked tickers:** the market source tracks **watchlist ∪ open positions**. Only the caller knows both sets, so the watchlist/portfolio code decides when to call `remove_ticker` (§12.2). A held ticker must keep getting prices even after it is removed from the watchlist, or its P&L would freeze.

---

## 7. Simulator

### 7.1 GBM step

For a ticker with price $S$, annual drift $\mu$, annual volatility $\sigma$ and a step of $\Delta t$ years:

$$S_{t+\Delta t} = S_t \exp\!\Big((\mu - \tfrac12\sigma^2)\Delta t + \sigma\sqrt{\Delta t}\,Z\Big),\quad Z\sim\mathcal N(0,1)$$

This is the exact solution of $dS = \mu S\,dt + \sigma S\,dW$, so prices can never go negative. `MIN_PRICE = 0.01` is only a guard.

- Trading year = 252 days × 6.5 h = 5,896,800 s.
- `dt = tick_seconds × SIM_SPEED / 5,896,800`. With the defaults (0.5 s × 50) each tick simulates 25 s of market time. AAPL (σ = 0.25) then moves about ±$0.10 per tick, which makes sparklines visibly alive within a minute. `SIM_SPEED=1` gives true real-time volatility, which looks nearly flat on screen.

### 7.2 Correlation

Each tick draws $\mathbf z\sim\mathcal N(0,I_n)$ and uses $\mathbf Z = L\mathbf z$, where $LL^\top = C$ (Cholesky). Pairwise $C_{ij}$:

| Pair | ρ |
|---|---|
| Same ticker | 1.00 |
| Involves an idiosyncratic name (`TSLA`) | 0.20 |
| Both `tech` | 0.60 |
| Both `finance` | 0.50 |
| Same other sector (incl. two unknown tickers, both `other`) | 0.40 |
| Different sectors | 0.25 |

$L$ is rebuilt whenever the ticker set changes (O(n³), trivial for n ≤ 50). A `1e-10` diagonal jitter plus an identity fallback guard against numerical failure. The test suite asserts that the default 10-ticker matrix is positive definite.

### 7.3 Events

Each tick, each ticker independently fires an event with probability `event_prob = 0.001`. With 10 tickers at 2 ticks/s, that is about one event every 50 s across the board. An event multiplies the GBM factor by `1 ± U(0.02, 0.05)`. It is uncorrelated with other tickers (a "news" move) and is logged at DEBUG level.

### 7.4 Seed data — `seed_prices.py`

```python
# backend/app/market/seed_prices.py
"""Static seed data for the simulator: starting prices, GBM params, sectors."""

SEED_PRICES: dict[str, float] = {
    "AAPL": 190.0, "GOOGL": 175.0, "MSFT": 420.0, "AMZN": 185.0, "TSLA": 250.0,
    "NVDA": 120.0, "META": 500.0, "JPM": 200.0, "V": 280.0, "NFLX": 650.0,
}

# (mu, sigma) - annualized drift and volatility
TICKER_PARAMS: dict[str, tuple[float, float]] = {
    "AAPL": (0.08, 0.25), "GOOGL": (0.08, 0.28), "MSFT": (0.08, 0.24),
    "AMZN": (0.10, 0.30), "TSLA": (0.10, 0.55), "NVDA": (0.15, 0.50),
    "META": (0.10, 0.35), "JPM": (0.06, 0.20), "V": (0.06, 0.18),
    "NFLX": (0.10, 0.38),
}
DEFAULT_PARAMS: tuple[float, float] = (0.06, 0.30)

SECTORS: dict[str, str] = {
    "AAPL": "tech", "GOOGL": "tech", "MSFT": "tech", "AMZN": "tech", "NVDA": "tech",
    "META": "tech", "NFLX": "tech", "TSLA": "auto", "JPM": "finance", "V": "finance",
}
DEFAULT_SECTOR = "other"

# Pairwise correlation of GBM shocks
INTRA_SECTOR_CORR: dict[str, float] = {"tech": 0.60, "finance": 0.50}
DEFAULT_INTRA_SECTOR_CORR = 0.40
CROSS_SECTOR_CORR = 0.25
IDIOSYNCRATIC: dict[str, float] = {"TSLA": 0.20}  # caps correlation with anything
```

Unknown tickers (e.g. `PYPL`) get a seed price drawn from $50–$300 by an RNG seeded with `crc32(ticker)`. The same symbol always starts at the same price, in every run and every test. They also get `DEFAULT_PARAMS` and sector `other`. To make a new ticker realistic, add a row to each table. Nothing else changes.

### 7.5 Code — `simulator.py`

```python
# backend/app/market/simulator.py
"""Built-in market simulator: correlated GBM with random news events."""
from __future__ import annotations

import asyncio
import logging
import os
import zlib

import numpy as np

from .cache import PriceCache
from .interface import MarketDataSource, normalize_ticker
from .seed_prices import (
    CROSS_SECTOR_CORR, DEFAULT_INTRA_SECTOR_CORR, DEFAULT_PARAMS, DEFAULT_SECTOR,
    IDIOSYNCRATIC, INTRA_SECTOR_CORR, SECTORS, SEED_PRICES, TICKER_PARAMS,
)

log = logging.getLogger(__name__)

TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600  # 5,896,800
MIN_PRICE = 0.01


def pair_correlation(a: str, b: str) -> float:
    if a == b:
        return 1.0
    for t in (a, b):
        if t in IDIOSYNCRATIC:
            return IDIOSYNCRATIC[t]
    sa, sb = SECTORS.get(a, DEFAULT_SECTOR), SECTORS.get(b, DEFAULT_SECTOR)
    if sa != sb:
        return CROSS_SECTOR_CORR
    return INTRA_SECTOR_CORR.get(sa, DEFAULT_INTRA_SECTOR_CORR)


def seed_price_for(ticker: str) -> float:
    """Known tickers use the table; unknown ones get a stable pseudo-random $50-$300."""
    if ticker in SEED_PRICES:
        return SEED_PRICES[ticker]
    rng = np.random.default_rng(zlib.crc32(ticker.encode()))
    return round(float(rng.uniform(50, 300)), 2)


class GBMSimulator:
    """Pure, synchronous price engine. No I/O, no asyncio, no clock."""

    def __init__(
        self,
        tickers: list[str] | None = None,
        *,
        tick_seconds: float = 0.5,
        speed: float = 50.0,
        event_prob: float = 0.001,
        event_range: tuple[float, float] = (0.02, 0.05),
        seed: int | None = None,
    ) -> None:
        self.dt = tick_seconds * speed / TRADING_SECONDS_PER_YEAR  # in years
        self.event_prob = event_prob
        self.event_range = event_range
        self.rng = np.random.default_rng(seed)
        self.tickers: list[str] = []
        self.prices: dict[str, float] = {}
        for t in tickers or []:
            self.add_ticker(t, rebuild=False)
        self._rebuild()

    # -- ticker management ------------------------------------------------
    def add_ticker(self, ticker: str, *, rebuild: bool = True) -> float:
        if ticker not in self.prices:
            self.tickers.append(ticker)
            self.prices[ticker] = seed_price_for(ticker)
            if rebuild:
                self._rebuild()
        return self.prices[ticker]

    def remove_ticker(self, ticker: str) -> None:
        if ticker in self.prices:
            self.tickers.remove(ticker)
            del self.prices[ticker]
            self._rebuild()

    def _rebuild(self) -> None:
        """Recompute per-ticker param vectors and the Cholesky factor."""
        n = len(self.tickers)
        params = [TICKER_PARAMS.get(t, DEFAULT_PARAMS) for t in self.tickers]
        self._mu = np.array([p[0] for p in params], dtype=float)
        self._sigma = np.array([p[1] for p in params], dtype=float)
        corr = np.array([[pair_correlation(a, b) for b in self.tickers] for a in self.tickers])
        try:
            self._chol = np.linalg.cholesky(corr + 1e-10 * np.eye(n)) if n else np.eye(0)
        except np.linalg.LinAlgError:
            log.warning("Correlation matrix not positive definite; using independent moves")
            self._chol = np.eye(n)

    # -- one tick -----------------------------------------------------------
    def step(self) -> dict[str, float]:
        n = len(self.tickers)
        if n == 0:
            return {}
        z = self._chol @ self.rng.standard_normal(n)              # correlated N(0,1)
        drift = (self._mu - 0.5 * self._sigma**2) * self.dt
        diffusion = self._sigma * np.sqrt(self.dt) * z
        factors = np.exp(drift + diffusion)

        events = self.rng.random(n) < self.event_prob
        if events.any():
            mags = self.rng.uniform(*self.event_range, n)
            signs = self.rng.choice([-1.0, 1.0], n)
            factors = np.where(events, factors * (1.0 + signs * mags), factors)
            for i in np.flatnonzero(events):
                log.debug("Market event: %s %+.1f%%", self.tickers[i], signs[i] * mags[i] * 100)

        for i, t in enumerate(self.tickers):
            self.prices[t] = max(MIN_PRICE, self.prices[t] * float(factors[i]))
        return dict(self.prices)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


class SimulatorDataSource(MarketDataSource):
    """Async adapter: runs GBMSimulator.step() every tick and writes to the cache."""

    name = "simulator"

    def __init__(
        self,
        cache: PriceCache,
        *,
        tick_seconds: float | None = None,
        speed: float | None = None,
        seed: int | None = None,
        event_prob: float = 0.001,
    ) -> None:
        super().__init__(cache)
        self.tick_seconds = tick_seconds if tick_seconds is not None else _env_float("SIM_TICK_INTERVAL", 0.5)
        self.speed = speed if speed is not None else _env_float("SIM_SPEED", 50.0)
        env_seed = os.getenv("SIM_SEED", "").strip()
        self.seed = seed if seed is not None else (int(env_seed) if env_seed else None)
        self.sim = GBMSimulator(
            tick_seconds=self.tick_seconds, speed=self.speed, event_prob=event_prob, seed=self.seed
        )
        self._task: asyncio.Task | None = None
        self._ticks = 0

    async def start(self, tickers: list[str]) -> None:
        for t in tickers:
            await self.add_ticker(t)  # warms the cache with seed prices
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="market-simulator")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def add_ticker(self, ticker: str) -> None:
        ticker = normalize_ticker(ticker)
        if ticker not in self.sim.prices:
            price = self.sim.add_ticker(ticker)
            self.cache.update(ticker, price, session_open=price)  # new row gets a price now

    async def remove_ticker(self, ticker: str) -> None:
        ticker = normalize_ticker(ticker)
        self.sim.remove_ticker(ticker)
        self.cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return sorted(self.sim.tickers)

    def status(self) -> dict:
        return {**super().status(), "ticks": self._ticks, "speed": self.speed}

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.tick_seconds)
            try:
                for ticker, price in self.sim.step().items():
                    self.cache.update(ticker, price)
                self._ticks += 1
            except Exception:
                log.exception("Simulator tick failed")  # never let the loop die
```

### 7.6 Example

```python
>>> from app.market.simulator import GBMSimulator
>>> sim = GBMSimulator(["AAPL", "MSFT", "JPM"], seed=42)
>>> sim.prices
{'AAPL': 190.0, 'MSFT': 420.0, 'JPM': 200.0}
>>> sim.step()                     # one 0.5 s tick (25 s of market time at speed 50)
{'AAPL': 190.0298..., 'MSFT': 419.8653..., 'JPM': 200.0549...}
>>> sim.add_ticker("PYPL")         # stable pseudo-random seed for unknown symbols
>>> sorted(sim.prices)
['AAPL', 'JPM', 'MSFT', 'PYPL']
```

---

## 8. Massive API client

### 8.1 Endpoints used

| Mode | Endpoint | Requests per cycle | Cadence |
|---|---|---|---|
| live (paid plans) | `GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,...` | 1 for all tickers | `MASSIVE_POLL_INTERVAL` (default 15 s) |
| eod (free plan) | `GET /v2/aggs/grouped/locale/us/market/stocks/{YYYY-MM-DD}?adjusted=true` | 0–3, usually 0 after the first | every 300 s |

Auth is the header `Authorization: Bearer <key>` against `https://api.massive.com`. A header keeps the key out of URLs, so it never shows up in access logs or exception messages.

### 8.2 Mode state machine

```
             start()
               │ probe snapshot
     ┌─────────┼───────────────────────────┐
     ▼ 200     ▼ 403 NOT_AUTHORIZED        ▼ 401
  ┌──────┐   ┌──────┐                  ┌──────────────┐
  │ live │──►│ eod  │                  │ unauthorized │  (terminal: polling stops,
  └──────┘403└──────┘                  └──────────────┘   /api/health healthy=false)
     ▲ │         ▲ │
     └─┘         └─┘   429 → extra backoff (15 s, 30 s, 60 s cap); 5xx/timeouts → retry next cycle
```

### 8.3 Price selection and parsing

The price for each snapshot row is chosen in this order, and the first positive value wins:

1. `lastTrade.p`, the last trade (includes after-hours)
2. `min.c`, the close of the current minute bar
3. `day.c`, today's running close
4. `prevDay.c`, yesterday's close (e.g. in the 3:30–4:00 AM ET reset window)

`prevDay.c` becomes `session_open`, so the watchlist's change % matches what brokers show: the change versus the previous close.

**EOD mode** downloads the grouped-daily bars for the whole market (~10k rows, a few MB). It keeps **all** of the closes in memory (`_eod_closes`), so a ticker added later gets its price with no extra request. That matters on a 5 calls/min plan. Refreshes only look for a trading day **newer** than the one already held, and they skip weekends. In steady state a refresh costs 1 request (today, until today's bar appears) or 0. In EOD mode `session_open` equals the close, so the change % is 0 and prices don't flash. That is expected for end-of-day data.

### 8.4 Error handling

| Condition | Detected by | Action |
|---|---|---|
| 200 (`status` `OK` or `DELAYED`) | — | Update cache, reset backoff, set `last_success` |
| 401 | `HTTPStatusError` | `mode = "unauthorized"`, log ERROR once, stop polling. Cache keeps whatever it had (likely empty). |
| 403 in live mode | `HTTPStatusError` | Switch to `eod`, fetch grouped daily immediately |
| 429 | `HTTPStatusError` | `backoff = min(max(2·backoff, poll_interval), 60)` added to the next delay |
| Other 4xx/5xx | `HTTPStatusError` | Log WARNING, keep prices, retry next cycle |
| Timeout / DNS / connection / bad JSON | any `Exception` | Same as above. `last_error` is shown in `/api/health`. |
| Unknown ticker | Missing from `tickers[]` | No cache entry. Downstream returns "no price available". |
| Ticker removed while a request was in flight | `ticker in self._tickers` check | Response row ignored, so it never reappears in the cache |

### 8.5 Code — `massive_client.py`

```python
# backend/app/market/massive_client.py
"""Massive (formerly Polygon.io) REST poller."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any, Literal

import httpx

from .cache import PriceCache
from .interface import MarketDataSource, normalize_ticker

log = logging.getLogger(__name__)

BASE_URL = "https://api.massive.com"
SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"
GROUPED_DAILY_PATH = "/v2/aggs/grouped/locale/us/market/stocks/{day}"

Mode = Literal["live", "eod", "unauthorized"]


# --------------------------------------------------------------------------
# Pure parsing helpers (unit-test these with plain dicts)
# --------------------------------------------------------------------------
def _num(obj: dict | None, key: str) -> float | None:
    value = (obj or {}).get(key)
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def pick_price(snap: dict) -> float | None:
    """lastTrade.p -> min.c -> day.c -> prevDay.c, first positive value wins."""
    return (
        _num(snap.get("lastTrade"), "p")
        or _num(snap.get("min"), "c")
        or _num(snap.get("day"), "c")
        or _num(snap.get("prevDay"), "c")
    )


def parse_snapshot(payload: dict) -> dict[str, tuple[float, float | None]]:
    """Snapshot response -> {ticker: (price, previous_close)}. Skips unusable rows."""
    out: dict[str, tuple[float, float | None]] = {}
    for snap in payload.get("tickers") or []:
        ticker = snap.get("ticker")
        price = pick_price(snap)
        if ticker and price is not None:
            out[ticker.upper()] = (price, _num(snap.get("prevDay"), "c"))
    return out


def parse_grouped_daily(payload: dict) -> dict[str, float]:
    """Grouped daily response -> {ticker: close} for the whole market."""
    return {
        row["T"].upper(): float(row["c"])
        for row in payload.get("results") or []
        if row.get("T") and isinstance(row.get("c"), (int, float)) and row["c"] > 0
    }


def recent_weekdays(today: date, newer_than: date | None, limit: int = 7) -> list[date]:
    """Candidate dates for grouped daily, newest first, skipping weekends."""
    days, d = [], today
    while len(days) < limit and (newer_than is None or d > newer_than):
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days


# --------------------------------------------------------------------------
# Data source
# --------------------------------------------------------------------------
class MassiveDataSource(MarketDataSource):
    """Polls Massive for the union of tracked tickers - one HTTP request per cycle.

    live mode:  snapshot endpoint every `poll_interval` s (paid plans)
    eod mode:   grouped-daily endpoint every `eod_interval` s (free plan; snapshot -> 403)
    unauthorized: bad key (401); polling stops, last prices (if any) stay in the cache
    """

    name = "massive"

    def __init__(
        self,
        cache: PriceCache,
        api_key: str,
        *,
        poll_interval: float = 15.0,
        eod_interval: float = 300.0,
        max_backoff: float = 60.0,
        base_url: str = BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,  # tests inject httpx.MockTransport
        today: Callable[[], date] = date.today,
    ) -> None:
        super().__init__(cache)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},  # keeps the key out of URLs/logs
            timeout=httpx.Timeout(10.0),
            transport=transport,
        )
        self.poll_interval = poll_interval
        self.eod_interval = eod_interval
        self.max_backoff = max_backoff
        self._today = today
        self._tickers: set[str] = set()
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self.mode: Mode = "live"
        self._backoff = 0.0
        self._eod_closes: dict[str, float] = {}   # full-market closes, reused for add_ticker
        self._eod_date: date | None = None
        self.last_success: float | None = None
        self.last_error: str | None = None

    # -- lifecycle ----------------------------------------------------------
    async def start(self, tickers: list[str]) -> None:
        self._tickers = {normalize_ticker(t) for t in tickers}
        await self._poll_once()  # probe: decides live vs eod and warms the cache
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="massive-poller")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._client.aclose()

    async def add_ticker(self, ticker: str) -> None:
        ticker = normalize_ticker(ticker)
        if ticker in self._tickers:
            return
        self._tickers.add(ticker)
        if self.mode == "eod" and ticker in self._eod_closes:
            close = self._eod_closes[ticker]
            self.cache.update(ticker, close, session_open=close)  # no API call needed
        else:
            self._wake.set()  # poll early so the new row gets a price within ~1 request

    async def remove_ticker(self, ticker: str) -> None:
        ticker = normalize_ticker(ticker)
        self._tickers.discard(ticker)
        self.cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return sorted(self._tickers)

    def status(self) -> dict:
        return {
            **super().status(),
            "healthy": self.mode != "unauthorized" and self.last_error is None,
            "mode": self.mode,
            "last_success": self.last_success,
            "last_error": self.last_error,
        }

    # -- loop ---------------------------------------------------------------
    def _next_delay(self) -> float:
        base = self.poll_interval if self.mode == "live" else self.eod_interval
        return base + self._backoff

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._next_delay())
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            if self.mode != "unauthorized":
                await self._poll_once()

    async def _poll_once(self) -> None:
        if not self._tickers:
            return
        try:
            if self.mode == "live":
                await self._poll_snapshot()
            else:
                await self._poll_eod()
            self._backoff = 0.0
            self.last_success = time.time()
            self.last_error = None
        except httpx.HTTPStatusError as exc:
            await self._handle_status_error(exc)
        except Exception as exc:  # timeouts, DNS, bad JSON... keep last prices
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("Massive poll failed (%s); keeping last prices", self.last_error)

    async def _handle_status_error(self, exc: httpx.HTTPStatusError) -> None:
        code = exc.response.status_code
        self.last_error = f"HTTP {code}"
        if code == 401:
            self.mode = "unauthorized"
            log.error("Massive rejected MASSIVE_API_KEY (401); market data polling stopped")
        elif code == 403 and self.mode == "live":
            log.warning("Massive plan has no snapshot access; using end-of-day prices")
            self.mode = "eod"
            await self._poll_once()  # fill the cache right away from grouped daily
        elif code == 429:
            self._backoff = min(max(self._backoff * 2, self.poll_interval), self.max_backoff)
            log.warning("Massive rate limit hit; backing off an extra %.0fs", self._backoff)
        else:
            log.warning("Massive returned HTTP %s; keeping last prices", code)

    # -- fetchers -----------------------------------------------------------
    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict:
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _poll_snapshot(self) -> None:
        tickers = sorted(self._tickers)
        payload = await self._get_json(SNAPSHOT_PATH, {"tickers": ",".join(tickers)})
        now = time.time()
        for ticker, (price, prev_close) in parse_snapshot(payload).items():
            if ticker in self._tickers:  # ignore rows for tickers removed mid-request
                self.cache.update(ticker, price, timestamp=now, session_open=prev_close)

    async def _poll_eod(self) -> None:
        # Only look for a trading day newer than the one we already have.
        for day in recent_weekdays(self._today(), newer_than=self._eod_date):
            payload = await self._get_json(
                GROUPED_DAILY_PATH.format(day=day.isoformat()), {"adjusted": "true"}
            )
            closes = parse_grouped_daily(payload)
            if closes:  # empty on holidays and before today's close
                self._eod_closes, self._eod_date = closes, day
                break
        now = time.time()
        for ticker in self._tickers:
            if ticker in self._eod_closes:
                close = self._eod_closes[ticker]
                self.cache.update(ticker, close, timestamp=now, session_open=close)
```

### 8.6 Example: a live-mode poll

Request:

```
GET https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT
Authorization: Bearer ****
```

Response (trimmed):

```json
{"status": "OK", "tickers": [
  {"ticker": "AAPL", "lastTrade": {"p": 191.5}, "prevDay": {"c": 190.0}},
  {"ticker": "MSFT", "lastTrade": {"p": 0}, "min": {"c": 421.0}, "prevDay": {"c": 420.0}}
]}
```

Result:

```python
parse_snapshot(payload) == {"AAPL": (191.5, 190.0), "MSFT": (421.0, 420.0)}
cache.get("AAPL").to_dict()["day_change_percent"] == 0.7895   # vs. prevDay close
```

### 8.7 Rate budget

| Plan | Mode | Requests/min (10–50 tickers) | Limit |
|---|---|---|---|
| Free | eod | ≤ 0.6 (one request per 5 min; at most 3 on the first start after a weekend) | 5/min ✓ |
| Starter+ | live @ 15 s | 4 + 1 per `add_ticker` | unlimited ✓ |
| Starter+ | live @ 2 s | 30 | unlimited ✓ |

---

## 9. Factory and configuration

```python
# backend/app/market/factory.py
"""Choose the market data source from the environment."""
from __future__ import annotations

import logging
import os

from .cache import PriceCache
from .interface import MarketDataSource

log = logging.getLogger(__name__)


def create_market_data_source(cache: PriceCache) -> MarketDataSource:
    api_key = os.getenv("MASSIVE_API_KEY", "").strip()
    if api_key:
        from .massive_client import MassiveDataSource

        interval = float(os.getenv("MASSIVE_POLL_INTERVAL", "").strip() or 15)
        log.info("Market data source: Massive API (poll every %.0fs)", interval)
        return MassiveDataSource(cache, api_key, poll_interval=interval)

    from .simulator import SimulatorDataSource

    log.info("Market data source: built-in simulator")
    return SimulatorDataSource(cache)
```

| Env var | Default | Read by | Effect |
|---|---|---|---|
| `MASSIVE_API_KEY` | empty | factory | Non-empty (after strip) → Massive. Empty, whitespace or absent → simulator. |
| `MASSIVE_POLL_INTERVAL` | `15` | factory | Live-mode poll seconds. Use 2–5 on paid plans. |
| `SIM_TICK_INTERVAL` | `0.5` | simulator | Seconds between ticks |
| `SIM_SPEED` | `50` | simulator | Market-time multiplier (1 = realistic, higher = livelier) |
| `SIM_SEED` | unset | simulator | Integer RNG seed for reproducible runs (E2E tests) |

Imports are lazy, so the Massive module (and httpx client setup) is never loaded in simulator mode.

---

## 10. SSE stream

### 10.1 Code — `stream.py`

```python
# backend/app/market/stream.py
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
```

### 10.2 Wire format

```
retry: 1000

event: prices
data: {"AAPL":{"ticker":"AAPL","price":191.23,"previous_price":191.18,"session_open":190.0,"timestamp":1790831225.69,"change":0.05,"change_percent":0.0262,"day_change_percent":0.6474,"direction":"up"},"AMZN":{...},...}

event: prices
data: {...}

: keepalive
```

- **One event type, `prices`.** The data is an object keyed by ticker that contains **every** tracked ticker. The frontend does no diffing, and after a reconnect the first frame restores full state, so there is no replay logic.
- **Frames are sent only when `cache.version` changed.** The simulator changes it every 0.5 s. Massive changes it every 15 s, and between polls only a keepalive comment is sent, every 15 s.
- **Cost:** ~2 KB per frame for 10 tickers, about 4 KB/s per tab. That is negligible on localhost.
- The cache is read from `request.app.state`, so the router is a plain module-level `APIRouter` included once at app creation.
- A removed ticker simply disappears from the next frame. The frontend should drop rows that are missing from the frame, or keep watchlist membership from `/api/watchlist` (the recommended approach) and use the frame only for prices.

### 10.3 Frontend consumption (reference for the Frontend agent)

```ts
// frontend/src/lib/usePriceStream.ts
import { useEffect, useRef, useState } from "react";

export type Direction = "up" | "down" | "flat";
export interface PriceUpdate {
  ticker: string; price: number; previous_price: number; session_open: number;
  timestamp: number; change: number; change_percent: number;
  day_change_percent: number; direction: Direction;
}
export type ConnectionStatus = "connected" | "reconnecting" | "disconnected";

const MAX_POINTS = 500; // sparkline history per ticker

export function usePriceStream() {
  const [prices, setPrices] = useState<Record<string, PriceUpdate>>({});
  const [status, setStatus] = useState<ConnectionStatus>("reconnecting");
  const history = useRef<Record<string, { time: number; value: number }[]>>({});

  useEffect(() => {
    const es = new EventSource("/api/stream/prices");
    es.onopen = () => setStatus("connected");
    es.onerror = () =>
      setStatus(es.readyState === EventSource.CLOSED ? "disconnected" : "reconnecting");
    es.addEventListener("prices", (e) => {
      const frame: Record<string, PriceUpdate> = JSON.parse((e as MessageEvent).data);
      for (const u of Object.values(frame)) {
        const h = (history.current[u.ticker] ??= []);
        if (!h.length || h[h.length - 1].time !== u.timestamp) {
          h.push({ time: u.timestamp, value: u.price });
          if (h.length > MAX_POINTS) h.shift();
        }
      }
      setPrices(frame);
    });
    return () => es.close();
  }, []);

  return { prices, status, history: history.current };
}
```

Flash: when `prices[t].direction !== "flat"` and its `timestamp` changed, add the class `flash-up` or `flash-down` to the row, then remove it after about 500 ms. The CSS `transition: background-color 500ms` does the fade.

---

## 11. Package exports

```python
# backend/app/market/__init__.py
"""Market data package. Everything outside app/market imports from here only."""
from .cache import PriceCache
from .factory import create_market_data_source
from .interface import MarketDataSource, normalize_ticker
from .models import PriceUpdate
from .stream import router as stream_router

__all__ = [
    "PriceCache",
    "PriceUpdate",
    "MarketDataSource",
    "create_market_data_source",
    "normalize_ticker",
    "stream_router",
]
```

---

## 12. Integration with the rest of the backend

### 12.1 `main.py` lifespan

```python
# backend/app/main.py  (market-data parts only)
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.market import PriceCache, create_market_data_source, stream_router
from app.db import get_position_tickers, get_watchlist_tickers, init_db  # backend DB layer


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()                                   # lazy schema + seed (PLAN.md §7)
    cache = PriceCache()
    source = create_market_data_source(cache)
    app.state.price_cache = cache
    app.state.market = source
    await source.start(sorted(set(get_watchlist_tickers()) | set(get_position_tickers())))
    try:
        yield
    finally:
        await source.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(stream_router)
# ... other routers, then static files mounted LAST so /api/* wins:
# app.mount("/", StaticFiles(directory="static", html=True), name="static")


@app.get("/api/health")
async def health(request: Request) -> dict:
    return {"status": "ok", "market": request.app.state.market.status()}
```

Example `/api/health` output (verified):

```json
{"status":"ok","market":{"source":"simulator","tickers":10,"healthy":true,"ticks":0,"speed":50.0}}
```

### 12.2 How other features use market data

```python
# Dependency helpers (e.g. app/deps.py)
from fastapi import Request
from app.market import MarketDataSource, PriceCache

def get_cache(request: Request) -> PriceCache:
    return request.app.state.price_cache

def get_market(request: Request) -> MarketDataSource:
    return request.app.state.market
```

**Watchlist add/remove.** The DB row is the source of truth, and the market source follows it:

```python
@router.post("/api/watchlist", status_code=201)
async def add_to_watchlist(body: TickerIn, market=Depends(get_market), cache=Depends(get_cache)):
    ticker = normalize_ticker(body.ticker)
    db.add_watchlist(ticker)                      # 409 if already present
    await market.add_ticker(ticker)               # no-op if already tracked (e.g. held)
    u = cache.get(ticker)
    return {"ticker": ticker, **(u.to_dict() if u else {"price": None})}


@router.delete("/api/watchlist/{ticker}", status_code=204)
async def remove_from_watchlist(ticker: str, market=Depends(get_market)):
    ticker = normalize_ticker(ticker)
    db.remove_watchlist(ticker)                   # 404 if absent
    if not db.has_position(ticker):               # keep pricing held tickers
        await market.remove_ticker(ticker)
```

**Trade execution.** The price always comes from the cache:

```python
async def execute_trade(ticker: str, side: str, quantity: float, market, cache) -> dict:
    ticker = normalize_ticker(ticker)
    if ticker not in market.get_tickers():
        await market.add_ticker(ticker)           # simulator: instant; Massive: next poll
    price = cache.get_price(ticker)
    if price is None:
        raise HTTPException(400, f"No price available for {ticker}")
    ...  # validate cash/shares, write trades + positions, record snapshot
    # After a full sell: if ticker not in watchlist -> await market.remove_ticker(ticker)
```

**Portfolio valuation**, used by `/api/portfolio`, the 30 s snapshot task and the LLM context:

```python
def position_value(pos, cache) -> tuple[float, float]:
    price = cache.get_price(pos.ticker) or pos.avg_cost   # fallback keeps totals sane
    return price, pos.quantity * price
```

**LLM chat context** is a compact text table built from `cache.get_all()`:

```python
lines = [f"{u.ticker}: ${u.price:.2f} ({u.day_change_percent:+.2f}% today)"
         for u in sorted(cache.get_all().values(), key=lambda u: u.ticker)]
```

| Consumer | Calls |
|---|---|
| `GET /api/watchlist` | `cache.get(t).to_dict()` per DB ticker |
| `POST /api/watchlist` | DB insert → `market.add_ticker` |
| `DELETE /api/watchlist/{t}` | DB delete → `market.remove_ticker` only if no position |
| `POST /api/portfolio/trade` | `cache.get_price` (400 if `None`) |
| `GET /api/portfolio`, snapshot task | `cache.get_price` with `avg_cost` fallback |
| `POST /api/chat` | `cache.get_all()` for context; trades/watchlist changes reuse the functions above |
| `GET /api/health` | `market.status()` |

---

## 13. Tests

All of these pass against the code above (`uv run pytest tests/market -q` → 23 passed, ~1.3 s).

### `tests/market/test_cache.py`

```python
# backend/tests/market/test_cache.py
from app.market import PriceCache


def test_first_update_is_flat():
    cache = PriceCache()
    u = cache.update("aapl", 190.0)
    assert u.ticker == "AAPL"
    assert u.previous_price == 190.0 and u.direction == "flat"
    assert u.session_open == 190.0


def test_direction_and_session_open_carry_over():
    cache = PriceCache()
    cache.update("AAPL", 100.0)
    up = cache.update("AAPL", 101.0)
    assert up.direction == "up" and up.previous_price == 100.0
    assert up.day_change_percent == 1.0
    down = cache.update("AAPL", 99.5)
    assert down.direction == "down" and down.session_open == 100.0


def test_version_and_remove():
    cache = PriceCache()
    v0 = cache.version
    cache.update("MSFT", 420.0)
    assert cache.version == v0 + 1
    cache.remove("MSFT")
    assert "MSFT" not in cache and cache.version == v0 + 2
    cache.remove("MSFT")                 # unknown -> no version bump
    assert cache.version == v0 + 2


def test_to_dict_contract():
    d = PriceCache().update("V", 280.0).to_dict()
    assert set(d) == {"ticker", "price", "previous_price", "session_open", "timestamp",
                      "change", "change_percent", "day_change_percent", "direction"}
```

### `tests/market/test_simulator.py`

```python
# backend/tests/market/test_simulator.py
import asyncio

import numpy as np
import pytest

from app.market import PriceCache
from app.market.simulator import GBMSimulator, SimulatorDataSource, pair_correlation, seed_price_for

TECH = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def test_seed_prices():
    assert GBMSimulator(["AAPL"]).prices["AAPL"] == 190.0
    p = seed_price_for("PYPL")
    assert 50 <= p <= 300 and seed_price_for("PYPL") == p


def test_default_correlation_matrix_is_positive_definite():
    corr = np.array([[pair_correlation(a, b) for b in TECH] for a in TECH])
    assert np.all(np.linalg.eigvalsh(corr) > 0)


def test_prices_stay_positive():
    sim = GBMSimulator(["TSLA", "NVDA"], speed=5000, event_prob=0.05, seed=1)
    for _ in range(10_000):
        sim.step()
    assert all(p > 0 for p in sim.prices.values())


def test_deterministic_with_seed():
    a, b = GBMSimulator(TECH, seed=42), GBMSimulator(TECH, seed=42)
    for _ in range(100):
        assert a.step() == b.step()


def test_gbm_log_return_statistics():
    sim = GBMSimulator(["AAPL"], speed=1, event_prob=0, seed=7)
    mu, sigma = 0.08, 0.25
    prev, rets = sim.prices["AAPL"], []
    for _ in range(20_000):
        cur = sim.step()["AAPL"]
        rets.append(np.log(cur / prev))
        prev = cur
    assert np.std(rets) == pytest.approx(sigma * np.sqrt(sim.dt), rel=0.03)
    assert abs(np.mean(rets) - (mu - sigma**2 / 2) * sim.dt) < 3 * sigma * np.sqrt(sim.dt / 20_000)


def test_correlation_by_sector():
    sim = GBMSimulator(["AAPL", "MSFT", "JPM"], event_prob=0, seed=3)
    hist = {t: [] for t in sim.tickers}
    prev = dict(sim.prices)
    for _ in range(20_000):
        cur = sim.step()
        for t in sim.tickers:
            hist[t].append(np.log(cur[t] / prev[t]))
        prev = cur
    assert np.corrcoef(hist["AAPL"], hist["MSFT"])[0, 1] == pytest.approx(0.60, abs=0.05)
    assert np.corrcoef(hist["AAPL"], hist["JPM"])[0, 1] == pytest.approx(0.25, abs=0.05)


def test_events_move_at_least_two_percent():
    sim = GBMSimulator(["AAPL"], speed=1, event_prob=1.0, seed=5)
    before = sim.prices["AAPL"]
    after = sim.step()["AAPL"]
    assert abs(after / before - 1) >= 0.0199


def test_add_remove_resizes():
    sim = GBMSimulator(["AAPL"])
    sim.add_ticker("PYPL")
    assert sim._chol.shape == (2, 2)
    sim.remove_ticker("AAPL")
    sim.remove_ticker("PYPL")
    assert sim.step() == {}


async def test_data_source_lifecycle():
    cache = PriceCache()
    src = SimulatorDataSource(cache, tick_seconds=0.01, seed=1)
    await src.start(["AAPL", "msft"])
    assert cache.get_price("AAPL") == 190.0 and src.get_tickers() == ["AAPL", "MSFT"]
    v = cache.version
    await asyncio.sleep(0.05)
    assert cache.version > v
    await src.add_ticker("PYPL")
    assert "PYPL" in cache                      # immediate price
    await src.remove_ticker("AAPL")
    assert "AAPL" not in cache and "AAPL" not in src.get_tickers()
    await src.stop()
    await src.stop()                            # idempotent
    assert src.status()["source"] == "simulator"
```

### `tests/market/test_massive.py`

The tests use `httpx.MockTransport`, so they make no network calls and need no API key.

```python
# backend/tests/market/test_massive.py
import asyncio
from datetime import date

import httpx

from app.market import PriceCache
from app.market.massive_client import (
    MassiveDataSource, parse_grouped_daily, parse_snapshot, pick_price, recent_weekdays,
)

SNAPSHOT = {
    "status": "OK",
    "tickers": [
        {"ticker": "AAPL", "lastTrade": {"p": 191.5}, "prevDay": {"c": 190.0}},
        {"ticker": "MSFT", "lastTrade": {"p": 0}, "min": {"c": 421.0}, "prevDay": {"c": 420.0}},
        {"ticker": "BAD", "day": {"c": 0}},
    ],
}
GROUPED = {"results": [{"T": "AAPL", "c": 189.0}, {"T": "MSFT", "c": 419.0}, {"T": "PYPL", "c": 70.0}]}


def test_pick_price_fallback_order():
    assert pick_price({"lastTrade": {"p": 1.5}, "min": {"c": 2}}) == 1.5
    assert pick_price({"lastTrade": {"p": 0}, "min": {"c": 2}}) == 2.0
    assert pick_price({"day": {"c": 3}}) == 3.0
    assert pick_price({"prevDay": {"c": 4}}) == 4.0
    assert pick_price({"lastTrade": None}) is None


def test_parsers():
    assert parse_snapshot(SNAPSHOT) == {"AAPL": (191.5, 190.0), "MSFT": (421.0, 420.0)}
    assert parse_grouped_daily(GROUPED)["PYPL"] == 70.0
    assert parse_grouped_daily({"resultsCount": 0}) == {}


def test_recent_weekdays_skips_weekend():
    monday = date(2026, 9, 28)
    assert recent_weekdays(monday, None, limit=2) == [monday, date(2026, 9, 25)]
    assert recent_weekdays(monday, newer_than=date(2026, 9, 25)) == [monday]


def make_source(handler, **kw):
    calls = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    src = MassiveDataSource(
        PriceCache(), "test-key", transport=httpx.MockTransport(wrapped),
        today=lambda: date(2026, 9, 28), **kw,
    )
    return src, calls


async def test_live_mode_populates_cache():
    src, calls = make_source(lambda r: httpx.Response(200, json=SNAPSHOT))
    await src.start(["AAPL", "MSFT"])
    assert src.mode == "live"
    assert src.cache.get_price("AAPL") == 191.5
    assert src.cache.get("AAPL").session_open == 190.0
    assert calls[0].headers["Authorization"] == "Bearer test-key"
    assert calls[0].url.params["tickers"] == "AAPL,MSFT"
    await src.stop()


async def test_403_falls_back_to_eod_and_add_ticker_uses_cached_closes():
    def handler(r: httpx.Request) -> httpx.Response:
        if "snapshot" in r.url.path:
            return httpx.Response(403, json={"status": "NOT_AUTHORIZED"})
        if r.url.path.endswith("2026-09-28"):
            return httpx.Response(200, json={"resultsCount": 0})  # before close
        return httpx.Response(200, json=GROUPED)

    src, calls = make_source(handler)
    await src.start(["AAPL"])
    assert src.mode == "eod" and src.cache.get_price("AAPL") == 189.0
    n = len(calls)
    await src.add_ticker("PYPL")
    assert src.cache.get_price("PYPL") == 70.0 and len(calls) == n   # no extra request
    await src.stop()


async def test_401_stops_polling():
    src, _ = make_source(lambda r: httpx.Response(401))
    await src.start(["AAPL"])
    assert src.mode == "unauthorized" and not src.status()["healthy"]
    await src.stop()


async def test_429_backs_off_and_network_error_keeps_prices():
    responses = iter([httpx.Response(200, json=SNAPSHOT), httpx.Response(429)])

    def handler(r):
        try:
            return next(responses)
        except StopIteration:
            raise httpx.ConnectTimeout("boom")

    src, _ = make_source(handler, poll_interval=15)
    await src.start(["AAPL"])
    await src._poll_once()
    assert src._backoff == 15
    await src._poll_once()
    assert src.cache.get_price("AAPL") == 191.5 and "ConnectTimeout" in src.last_error
    await src.stop()


async def test_add_ticker_wakes_poller():
    src, calls = make_source(lambda r: httpx.Response(200, json=SNAPSHOT), poll_interval=3600)
    await src.start(["AAPL"])
    await src.add_ticker("MSFT")
    for _ in range(50):
        if src.cache.get_price("MSFT"):
            break
        await asyncio.sleep(0.01)
    assert src.cache.get_price("MSFT") == 421.0 and len(calls) == 2
    await src.remove_ticker("MSFT")
    assert "MSFT" not in src.cache
    await src.stop()
```

### `tests/market/test_factory_and_stream.py`

```python
# backend/tests/market/test_factory_and_stream.py
import json

from app.market import PriceCache, create_market_data_source
from app.market.massive_client import MassiveDataSource
from app.market.simulator import SimulatorDataSource
from app.market.stream import price_events


def test_factory(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)
    monkeypatch.setenv("MASSIVE_API_KEY", "   ")
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)
    monkeypatch.setenv("MASSIVE_API_KEY", "abc")
    assert isinstance(create_market_data_source(PriceCache()), MassiveDataSource)


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
```

### Manual smoke test

```bash
cd backend
uv run uvicorn app.main:app --port 8000 &
curl -s localhost:8000/api/health
curl -sN --max-time 2 localhost:8000/api/stream/prices | head -c 400
```

Expected: `"source":"simulator"`, then `retry: 1000` and about 4 `event: prices` frames in 2 s.

---

## 14. Design decisions and changes from earlier docs

| Topic | Earlier docs | This design | Why |
|---|---|---|---|
| Massive HTTP client | Official `massive` SDK via `asyncio.to_thread` | `httpx.AsyncClient` directly | The SDK is synchronous and raises `BadResponse` carrying only the response body, so 401/403/429 must be guessed by matching strings (the body of a 429 need not contain "429"). httpx gives real status codes, is natively async (no threads), and is testable with `MockTransport`. Only two endpoints are needed, so the SDK adds little. |
| `add_ticker` in Massive live mode | Awaited an inline poll | Sets an `asyncio.Event` that wakes the poll loop | The route returns immediately, and two adds in a row coalesce into one request. Only one coroutine ever polls. |
| `add_ticker` in EOD mode | No price until the next 5 min refresh | Served from the in-memory full-market closes | Instant, and costs no request on a 5/min plan |
| EOD refresh | Walked back up to 7 days on every refresh | Only searches for days newer than the one held, and skips weekends | Bounded at ≤1 request per refresh in steady state |
| 401 handling | Not handled in code | Terminal `unauthorized` mode, shown in `/api/health` | Stops hammering the API with a bad key |
| SSE router | Built inside lifespan with the cache in a closure | Module-level router reading `request.app.state.price_cache` | Routes are registered once at import time (adding them in lifespan is fragile with static mounts). The generator `price_events` is testable without HTTP. |
| SSE keepalive | A comment every 0.5 s when nothing changed | A comment after 15 s of silence | Less noise, and still under typical 30–60 s proxy idle timeouts |
| `session_open` | Optional (`None`) | Always set (falls back to the first price) | Removes `None` checks in the frontend. The JSON includes it so the client can recompute values if needed. |
| Simulator construction | `GBMSimulator` created in `start()` | Created in `__init__` | `add_ticker` before `start()` no longer asserts. `status()` always works. |
| Simulator config parsing | `x or env` | `x if x is not None else env` | `tick_seconds=0` or `seed=0` from tests are respected |
| Event probability | Module constant (needed a monkeypatch) | Constructor argument | Tests set `event_prob=0` / `1.0` directly |

Unchanged from earlier docs: GBM math, speed factor, correlation values, event sizes, seed prices, price-selection order, the env vars, and the "full snapshot per frame" SSE model.

---

## 15. Implementation checklist

1. `cd backend && uv add numpy httpx && uv add --dev pytest pytest-asyncio`. Add the `[tool.pytest.ini_options]` block from §3.
2. Create `app/market/` with the nine files in §4–§11, copied verbatim.
3. Create `tests/market/` with the four test files from §13. Run `uv run pytest tests/market -q`. All should pass.
4. Wire `lifespan`, `stream_router` and `/api/health` into `app/main.py` (§12.1). Mount static files **after** the API routers.
5. Use `normalize_ticker`, `cache.get_price` and `market.add_ticker`/`remove_ticker` in the watchlist, portfolio and chat code exactly as in §12.2.
6. Smoke test: start uvicorn, then `curl` `/api/health` and `/api/stream/prices` (§13).
7. With a real `MASSIVE_API_KEY`: check that `/api/health` reports `"mode": "live"` (paid) or `"eod"` (free) and that prices populate.
8. E2E (Playwright): run with `SIM_SEED=42` for stable starting prices. With default settings, assert that prices change within 2 s.
