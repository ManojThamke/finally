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
