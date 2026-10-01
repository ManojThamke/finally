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
