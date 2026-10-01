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
