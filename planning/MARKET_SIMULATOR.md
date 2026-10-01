# Market Simulator: Approach and Code Structure

The simulator is the default market data source, used whenever `MASSIVE_API_KEY` is empty. It generates realistic-looking, correlated, occasionally dramatic price action for any set of tickers, entirely in-process. It needs no network and no API key. It implements `MarketDataSource` from `MARKET_INTERFACE.md` and writes into the shared `PriceCache`.

---

## 1. Requirements (from PLAN.md §6)

| Requirement | How it is met |
|---|---|
| Geometric Brownian motion, per-ticker drift and volatility | Exact log-normal GBM step (§2) |
| ~500 ms updates | `SimulatorDataSource` loop, `SIM_TICK_INTERVAL=0.5` |
| Correlated moves (tech moves together) | Sector correlation matrix + Cholesky factor (§3) |
| Occasional 2–5% "events" | Poisson-style random shocks (§4) |
| Realistic seed prices | `seed_prices.py` table (§5) |
| Any ticker, added at runtime | Unknown tickers get a generated seed and default params (§5) |
| No external deps | `numpy` only |

---

## 2. GBM math

For each ticker with price $S$, annual drift $\mu$ and annual volatility $\sigma$, one step of length $\Delta t$ (in **years**) is:

$$
S_{t+\Delta t} = S_t \cdot \exp\!\Big( (\mu - \tfrac{1}{2}\sigma^2)\,\Delta t + \sigma \sqrt{\Delta t}\; Z \Big), \qquad Z \sim \mathcal{N}(0,1)
$$

This is the exact solution of $dS = \mu S\,dt + \sigma S\,dW$. Prices stay strictly positive and returns are log-normal.

**Time step.** A trading year is 252 days × 6.5 h = 5,896,800 s. One 0.5 s tick is:

$$
\Delta t = \frac{0.5}{252 \times 6.5 \times 3600} \approx 8.48 \times 10^{-8}\ \text{years}
$$

**Speed-up factor.** At real-world volatility (σ = 0.25), a 0.5 s tick moves the price by about σ√Δt ≈ 0.007%, or roughly ±$0.01 on a $190 stock. That is realistic, but a sparkline built over a few minutes looks nearly flat. To make the demo lively, `Δt` is multiplied by `SIM_SPEED` (default **50**, so each tick simulates about 25 s of market time). With that setting, AAPL wiggles by about ±$0.10 per tick and drifts visibly over a minute. `SIM_SPEED=1` gives "real-time" realism.

Drift is negligible at these horizons, so price action is dominated by σ. That is the intended behavior.

---

## 3. Correlated moves

Draw independent normals $\mathbf{z} \sim \mathcal{N}(0, I_n)$ each tick and set $\mathbf{Z} = L\mathbf{z}$, where $L$ is the Cholesky factor of the correlation matrix $C$ ($C = LL^\top$). Then $\text{Corr}(Z_i, Z_j) = C_{ij}$.

**Correlation matrix from sectors:**

| Pair | ρ |
|---|---|
| Same sector, `tech` | 0.60 |
| Same sector, `finance` | 0.50 |
| Same sector, other | 0.40 |
| Different sectors | 0.25 |
| Anything involving `TSLA` | 0.20 (idiosyncratic) |
| Diagonal | 1.00 |

This construction (a constant within-group value ≥ a constant cross-group value, all < 1) is positive definite. Even so, the code adds a tiny diagonal jitter and falls back to the identity if `np.linalg.cholesky` ever raises. The matrix is **rebuilt whenever the ticker set changes**, which is cheap at n ≈ 10–50.

---

## 4. Random events

Each tick, each ticker independently has a probability `EVENT_PROB = 0.001` of an event. With 10 tickers at 2 ticks/s, that works out to about one event every 50 s across the board. When an event fires:

```
magnitude = uniform(0.02, 0.05)
sign      = ±1 (50/50)
price    *= 1 + sign * magnitude
```

The shock is applied multiplicatively *after* the GBM step and is not correlated with other tickers. It is a "news" move. Events are logged at DEBUG level, and the source can expose recent events if we later want them in the UI.

---

## 5. Seed data (seed_prices.py)

```python
SEED_PRICES: dict[str, float] = {
    "AAPL": 190.0, "GOOGL": 175.0, "MSFT": 420.0, "AMZN": 185.0, "TSLA": 250.0,
    "NVDA": 120.0, "META": 500.0,  "JPM": 200.0,  "V": 280.0,    "NFLX": 650.0,
}

# (mu, sigma) annualized
TICKER_PARAMS: dict[str, tuple[float, float]] = {
    "AAPL": (0.08, 0.25), "GOOGL": (0.08, 0.28), "MSFT": (0.08, 0.24),
    "AMZN": (0.10, 0.30), "TSLA": (0.10, 0.55), "NVDA": (0.15, 0.50),
    "META": (0.10, 0.35), "JPM": (0.06, 0.20),  "V": (0.06, 0.18),
    "NFLX": (0.10, 0.38),
}
DEFAULT_PARAMS = (0.06, 0.30)

SECTORS: dict[str, str] = {
    "AAPL": "tech", "GOOGL": "tech", "MSFT": "tech", "AMZN": "tech", "NVDA": "tech",
    "META": "tech", "NFLX": "tech", "TSLA": "auto",
    "JPM": "finance", "V": "finance",
}
DEFAULT_SECTOR = "other"
```

**Unknown tickers** (e.g. the user adds `PYPL`) get a seed price drawn uniformly from $50–$300 using a RNG seeded by the ticker string. The same symbol therefore always starts at the same price, which keeps demos and tests stable. They also get `DEFAULT_PARAMS` and sector `other`.

---

## 6. Code: `GBMSimulator` (pure, synchronous)

This class holds all the math. It does no I/O, no asyncio and no clock, so it is trivially unit-testable.

```python
# backend/app/market/simulator.py
from __future__ import annotations

import asyncio
import logging
import os
import zlib

import numpy as np

from .cache import PriceCache
from .interface import MarketDataSource
from .seed_prices import DEFAULT_PARAMS, DEFAULT_SECTOR, SECTORS, SEED_PRICES, TICKER_PARAMS

log = logging.getLogger(__name__)

TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600
EVENT_PROB = 0.001
EVENT_MIN, EVENT_MAX = 0.02, 0.05


def pair_correlation(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if "TSLA" in (a, b):
        return 0.20
    sa, sb = SECTORS.get(a, DEFAULT_SECTOR), SECTORS.get(b, DEFAULT_SECTOR)
    if sa != sb:
        return 0.25
    return {"tech": 0.60, "finance": 0.50}.get(sa, 0.40)


def seed_price_for(ticker: str) -> float:
    if ticker in SEED_PRICES:
        return SEED_PRICES[ticker]
    rng = np.random.default_rng(zlib.crc32(ticker.encode()))
    return round(float(rng.uniform(50, 300)), 2)


class GBMSimulator:
    def __init__(self, tickers: list[str], tick_seconds: float = 0.5, speed: float = 50.0,
                 seed: int | None = None) -> None:
        self.dt = tick_seconds * speed / TRADING_SECONDS_PER_YEAR
        self.rng = np.random.default_rng(seed)
        self.tickers: list[str] = []
        self.prices: dict[str, float] = {}
        self._L = np.eye(0)
        for t in tickers:
            self.add_ticker(t, rebuild=False)
        self._rebuild()

    # --- ticker management -------------------------------------------------
    def add_ticker(self, ticker: str, rebuild: bool = True) -> float:
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
        n = len(self.tickers)
        params = [TICKER_PARAMS.get(t, DEFAULT_PARAMS) for t in self.tickers]
        self._mu = np.array([p[0] for p in params])
        self._sigma = np.array([p[1] for p in params])
        corr = np.array([[pair_correlation(a, b) for b in self.tickers] for a in self.tickers])
        try:
            self._L = np.linalg.cholesky(corr + 1e-10 * np.eye(n)) if n else np.eye(0)
        except np.linalg.LinAlgError:
            log.warning("Correlation matrix not PD; using independent moves")
            self._L = np.eye(n)

    # --- one tick ----------------------------------------------------------
    def step(self) -> dict[str, float]:
        n = len(self.tickers)
        if n == 0:
            return {}
        z = self._L @ self.rng.standard_normal(n)
        drift = (self._mu - 0.5 * self._sigma**2) * self.dt
        shock = self._sigma * np.sqrt(self.dt) * z
        factors = np.exp(drift + shock)

        events = self.rng.random(n) < EVENT_PROB
        if events.any():
            mags = self.rng.uniform(EVENT_MIN, EVENT_MAX, n)
            signs = self.rng.choice([-1.0, 1.0], n)
            factors = np.where(events, factors * (1 + signs * mags), factors)
            for i in np.flatnonzero(events):
                log.debug("Event: %s %+.1f%%", self.tickers[i], signs[i] * mags[i] * 100)

        for i, t in enumerate(self.tickers):
            self.prices[t] = max(0.01, self.prices[t] * float(factors[i]))
        return dict(self.prices)
```

---

## 7. Code: `SimulatorDataSource` (async adapter)

```python
class SimulatorDataSource(MarketDataSource):
    name = "simulator"

    def __init__(self, cache: PriceCache, tick_seconds: float | None = None,
                 speed: float | None = None, seed: int | None = None) -> None:
        super().__init__(cache)
        self.tick_seconds = tick_seconds or float(os.getenv("SIM_TICK_INTERVAL", "0.5"))
        self.speed = speed or float(os.getenv("SIM_SPEED", "50"))
        env_seed = os.getenv("SIM_SEED")
        self.seed = seed if seed is not None else (int(env_seed) if env_seed else None)
        self.sim: GBMSimulator | None = None
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        self.sim = GBMSimulator([t.upper() for t in tickers], self.tick_seconds, self.speed, self.seed)
        for t, p in self.sim.prices.items():       # warm cache with seed prices
            self.cache.update(t, p, session_open=p)
        self._task = asyncio.create_task(self._run(), name="market-simulator")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def add_ticker(self, ticker: str) -> None:
        assert self.sim is not None, "start() first"
        ticker = ticker.upper()
        if ticker not in self.sim.prices:
            p = self.sim.add_ticker(ticker)
            self.cache.update(ticker, p, session_open=p)  # immediate price for the new row

    async def remove_ticker(self, ticker: str) -> None:
        if self.sim:
            self.sim.remove_ticker(ticker.upper())
        self.cache.remove(ticker.upper())

    def get_tickers(self) -> list[str]:
        return list(self.sim.tickers) if self.sim else []

    async def _run(self) -> None:
        while True:
            try:
                for t, p in self.sim.step().items():
                    self.cache.update(t, p)
            except Exception:
                log.exception("Simulator tick failed")  # never let the loop die
            await asyncio.sleep(self.tick_seconds)
```

Design notes:
- **Separation of math and I/O.** `GBMSimulator` is pure and deterministic given a seed. `SimulatorDataSource` only handles scheduling and cache writes.
- **Single writer.** Add and remove run on the same event loop as `_run`, so the simulator's internal lists never mutate mid-step. No locking is needed inside `GBMSimulator`.
- **Rounding.** The simulator keeps full float precision internally. `PriceCache.update` rounds to cents for display. Small ticks that round to the same cent show as `flat`, which is realistic.
- **`session_open`** is the seed price, so the watchlist "daily change %" means "change since the app started (or since the ticker was added)".
- **Numpy** must be listed in `backend/pyproject.toml` (`uv add numpy`).

---

## 8. Configuration

| Env var | Default | Meaning |
|---|---|---|
| `SIM_TICK_INTERVAL` | `0.5` | Seconds between ticks |
| `SIM_SPEED` | `50` | Market-time multiplier (1 = realistic, higher = livelier) |
| `SIM_SEED` | unset | Fixed RNG seed for reproducible runs |

---

## 9. Tests (`backend/tests/market/test_simulator.py`)

| Test | Assertion |
|---|---|
| Seed prices | `GBMSimulator(["AAPL"]).prices["AAPL"] == 190.0`. Unknown tickers land in [50, 300] and are stable across instances. |
| Positivity | 10,000 steps with high σ: all prices > 0 |
| Determinism | Two sims with `seed=42` produce identical sequences |
| GBM statistics | With `speed=1`, events disabled (monkeypatch `EVENT_PROB=0`), and a single ticker over many steps: the mean of log-returns ≈ (μ−σ²/2)Δt and the std ≈ σ√Δt, within tolerance |
| Correlation | For AAPL/MSFT over 20k steps, the empirical correlation of log-returns ≈ 0.6 (±0.05). AAPL/JPM ≈ 0.25. |
| Events | Monkeypatch `EVENT_PROB=1`: every step moves each price by ≥ ~2% |
| Add/remove | Adding a ticker grows `tickers`, `prices` and the shape of `_L`. Removing shrinks them. `step()` still works with 0 tickers. |
| Data source | `start()` warms the cache. After about 3 ticks (`tick_seconds=0.01`) the cache version has advanced. `add_ticker` puts a price in the cache immediately. `remove_ticker` drops it. `stop()` is idempotent. |
