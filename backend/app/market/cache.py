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
