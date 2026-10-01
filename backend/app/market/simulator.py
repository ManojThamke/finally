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
