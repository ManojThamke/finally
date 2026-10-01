import asyncio

import numpy as np
import pytest

from app.market import MarketDataSource, PriceCache
from app.market.simulator import GBMSimulator, SimulatorDataSource, pair_correlation, seed_price_for

TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def test_seed_prices():
    assert GBMSimulator(["AAPL"]).prices["AAPL"] == 190.0
    p = seed_price_for("PYPL")
    assert 50 <= p <= 300 and seed_price_for("PYPL") == p


def test_pair_correlation_values():
    assert pair_correlation("AAPL", "AAPL") == 1.0
    assert pair_correlation("AAPL", "MSFT") == 0.60
    assert pair_correlation("JPM", "V") == 0.50
    assert pair_correlation("AAPL", "JPM") == 0.25
    assert pair_correlation("TSLA", "AAPL") == 0.20
    assert pair_correlation("PYPL", "XYZ") == 0.40


def test_default_correlation_matrix_is_positive_definite():
    corr = np.array([[pair_correlation(a, b) for b in TICKERS] for a in TICKERS])
    assert np.all(np.linalg.eigvalsh(corr) > 0)


def test_prices_stay_positive():
    sim = GBMSimulator(["TSLA", "NVDA"], speed=5000, event_prob=0.05, seed=1)
    for _ in range(10_000):
        sim.step()
    assert all(p > 0 for p in sim.prices.values())


def test_deterministic_with_seed():
    a, b = GBMSimulator(TICKERS, seed=42), GBMSimulator(TICKERS, seed=42)
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


def test_no_events_when_probability_zero():
    sim = GBMSimulator(["AAPL"], speed=1, event_prob=0, seed=5)
    for _ in range(1000):
        before = sim.prices["AAPL"]
        assert abs(sim.step()["AAPL"] / before - 1) < 0.01


def test_add_remove_resizes():
    sim = GBMSimulator(["AAPL"])
    sim.add_ticker("PYPL")
    assert sim._chol.shape == (2, 2) and len(sim.prices) == 2
    sim.add_ticker("PYPL")  # duplicate is a no-op
    assert sim.tickers == ["AAPL", "PYPL"]
    sim.remove_ticker("AAPL")
    assert sim._chol.shape == (1, 1)
    sim.remove_ticker("PYPL")
    sim.remove_ticker("PYPL")  # unknown is a no-op
    assert sim.step() == {}


def test_non_positive_definite_falls_back_to_identity(monkeypatch):
    monkeypatch.setattr("app.market.simulator.pair_correlation", lambda a, b: 1.0 if a == b else 2.0)
    sim = GBMSimulator(["AAPL", "MSFT"])
    assert np.array_equal(sim._chol, np.eye(2))


async def test_data_source_lifecycle():
    cache = PriceCache()
    src = SimulatorDataSource(cache, tick_seconds=0.01, seed=1)
    assert isinstance(src, MarketDataSource)
    await src.start(["AAPL", "msft"])
    assert cache.get_price("AAPL") == 190.0 and src.get_tickers() == ["AAPL", "MSFT"]
    v = cache.version
    await asyncio.sleep(0.05)
    assert cache.version > v and src.status()["ticks"] > 0
    await src.add_ticker("PYPL")
    assert "PYPL" in cache                      # immediate price
    await src.remove_ticker("AAPL")
    assert "AAPL" not in cache and "AAPL" not in src.get_tickers()
    await src.stop()
    await src.stop()                            # idempotent
    assert src.status()["source"] == "simulator"


async def test_add_before_start_and_empty_start():
    src = SimulatorDataSource(PriceCache(), tick_seconds=0.01)
    await src.add_ticker("aapl")
    await src.start([])
    assert src.get_tickers() == ["AAPL"]
    await src.stop()


def test_env_configuration(monkeypatch):
    monkeypatch.setenv("SIM_TICK_INTERVAL", "0.1")
    monkeypatch.setenv("SIM_SPEED", "2")
    monkeypatch.setenv("SIM_SEED", "9")
    src = SimulatorDataSource(PriceCache())
    assert (src.tick_seconds, src.speed, src.seed) == (0.1, 2.0, 9)
    # explicit zero values are respected, not replaced by env/default
    src = SimulatorDataSource(PriceCache(), seed=0)
    assert src.seed == 0
