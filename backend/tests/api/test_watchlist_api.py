DEFAULT = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def tickers(client):
    return [row["ticker"] for row in client.get("/api/watchlist").json()["tickers"]]


def test_get_watchlist(client):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    rows = r.json()["tickers"]
    assert [row["ticker"] for row in rows] == DEFAULT
    assert all(isinstance(row["price"], float) for row in rows)
    assert set(rows[0]) == {"ticker", "price", "previous_price", "change", "change_percent",
                            "day_change_percent", "direction"}


def test_add_and_remove(client):
    r = client.post("/api/watchlist", json={"ticker": " pypl "})
    assert r.status_code == 201 and r.json() == {"ticker": "PYPL", "added": True}
    assert tickers(client)[-1] == "PYPL"
    assert client.app.state.price_cache.get_price("PYPL") is not None

    r = client.delete("/api/watchlist/pypl")
    assert r.status_code == 200 and r.json() == {"ticker": "PYPL", "removed": True}
    assert "PYPL" not in tickers(client)
    assert "PYPL" not in client.app.state.market_source.get_tickers()


def test_add_duplicate_409(client):
    r = client.post("/api/watchlist", json={"ticker": "AAPL"})
    assert r.status_code == 409 and "detail" in r.json()


def test_add_invalid_400(client):
    for bad in ["", "   ", "AB12", "WAYTOOLONGTICKER"]:
        r = client.post("/api/watchlist", json={"ticker": bad})
        assert r.status_code == 400, bad
    assert client.post("/api/watchlist", json={}).status_code == 422


def test_remove_missing_404(client):
    r = client.delete("/api/watchlist/ZZZZ")
    assert r.status_code == 404 and "detail" in r.json()


def test_remove_held_ticker_keeps_price(client):
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1, "side": "buy"})
    assert client.delete("/api/watchlist/AAPL").status_code == 200
    pos = client.get("/api/portfolio").json()["positions"][0]
    assert pos["ticker"] == "AAPL"
    assert client.app.state.price_cache.get_price("AAPL") is not None


def test_watchlist_persists_across_restart(client):
    from fastapi.testclient import TestClient

    client.post("/api/watchlist", json={"ticker": "PYPL"})
    with TestClient(client.app) as again:
        assert "PYPL" in tickers(again)
        assert "PYPL" in again.app.state.market_source.get_tickers()
