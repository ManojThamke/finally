import pytest

PORTFOLIO_KEYS = {"cash_balance", "positions_value", "total_value", "unrealized_pnl",
                  "unrealized_pnl_percent", "positions"}
POSITION_KEYS = {"ticker", "quantity", "avg_cost", "current_price", "market_value",
                 "unrealized_pnl", "unrealized_pnl_percent", "weight"}


def price_of(client, ticker):
    return client.app.state.price_cache.get_price(ticker)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["source"] == "simulator" and body["tickers"] == 10


def test_get_portfolio_fresh(client):
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == PORTFOLIO_KEYS
    assert body["cash_balance"] == 10000.0 and body["total_value"] == 10000.0
    assert body["positions"] == []


def test_buy(client):
    price = price_of(client, "AAPL")
    r = client.post("/api/portfolio/trade", json={"ticker": "aapl", "quantity": 2, "side": "buy"})
    assert r.status_code == 200
    body = r.json()
    assert set(body["trade"]) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
    assert body["trade"]["ticker"] == "AAPL" and body["trade"]["price"] == price
    p = body["portfolio"]
    assert set(p) == PORTFOLIO_KEYS
    assert p["cash_balance"] == pytest.approx(round(10000 - 2 * price, 2))
    assert len(p["positions"]) == 1 and set(p["positions"][0]) == POSITION_KEYS
    assert client.get("/api/portfolio").json() == p


def test_sell_all_removes_position(client):
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1.5, "side": "buy"})
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1.5, "side": "sell"})
    assert r.status_code == 200
    assert r.json()["portfolio"]["positions"] == []
    assert r.json()["portfolio"]["cash_balance"] == pytest.approx(10000.0)


def test_sell_at_a_loss(client):
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 10, "side": "buy"})
    cost = price_of(client, "AAPL")
    client.app.state.price_cache.update("AAPL", cost - 10)
    pos = client.get("/api/portfolio").json()["positions"][0]
    assert pos["unrealized_pnl"] == pytest.approx(-100.0)
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 10, "side": "sell"})
    assert r.status_code == 200
    assert r.json()["portfolio"]["cash_balance"] == pytest.approx(9900.0)


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"ticker": "AAPL", "quantity": 1_000_000, "side": "buy"}, "Insufficient cash"),
        ({"ticker": "AAPL", "quantity": 1, "side": "sell"}, "Insufficient shares"),
        ({"ticker": "AAPL", "quantity": 0, "side": "buy"}, "Quantity must be positive"),
        ({"ticker": "ZZZZ", "quantity": 1, "side": "buy"}, "No price available"),
    ],
)
def test_trade_rejected(client, body, detail):
    r = client.post("/api/portfolio/trade", json=body)
    assert r.status_code == 400
    assert detail in r.json()["detail"]
    assert client.get("/api/portfolio").json()["cash_balance"] == 10000.0


@pytest.mark.parametrize(
    "body",
    [{"ticker": "AAPL", "quantity": 1, "side": "short"}, {"ticker": "AAPL", "side": "buy"},
     {"ticker": "AAPL", "quantity": "lots", "side": "buy"}],
)
def test_trade_malformed_body(client, body):
    assert client.post("/api/portfolio/trade", json=body).status_code == 422


def test_history(client):
    assert client.get("/api/portfolio/history").json() == {"snapshots": []}
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1, "side": "buy"})
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1, "side": "sell"})
    snaps = client.get("/api/portfolio/history").json()["snapshots"]
    assert len(snaps) == 2
    assert set(snaps[0]) == {"total_value", "recorded_at"}
    assert snaps[0]["recorded_at"] <= snaps[1]["recorded_at"]
