"""Shared fixtures: an isolated DB per test and a TestClient running the full app lifespan."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.market import PriceCache


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "finally.db"
    monkeypatch.setenv("FINALLY_DB_PATH", str(path))
    return path


@pytest.fixture
def conn(db_path):
    from app.db import get_connection

    with get_connection(db_path) as connection:
        yield connection


@pytest.fixture
def price_cache():
    cache = PriceCache()
    cache.update("AAPL", 100.0)
    cache.update("MSFT", 400.0)
    return cache


@pytest.fixture
def client(db_path, tmp_path, monkeypatch):
    # Simulator with frozen prices (no ticks during a test), mocked LLM, no frontend build.
    monkeypatch.setenv("MASSIVE_API_KEY", "")
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.setenv("SIM_TICK_INTERVAL", "3600")
    monkeypatch.setenv("SIM_SEED", "42")
    monkeypatch.setenv("FINALLY_STATIC_DIR", str(tmp_path / "static"))
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
