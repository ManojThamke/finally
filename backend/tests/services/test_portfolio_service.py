import pytest

from app import db
from app.services.portfolio import TradeError, build_portfolio, execute_trade, record_snapshot


def test_fresh_portfolio(conn, price_cache):
    p = build_portfolio(conn, price_cache)
    assert p == {
        "cash_balance": 10000.0, "positions_value": 0.0, "total_value": 10000.0,
        "unrealized_pnl": 0.0, "unrealized_pnl_percent": 0.0, "positions": [],
    }


def test_buy_creates_position_and_debits_cash(conn, price_cache):
    trade = execute_trade(conn, price_cache, "aapl", "buy", 10)
    assert trade["ticker"] == "AAPL" and trade["side"] == "buy"
    assert trade["quantity"] == 10 and trade["price"] == 100.0
    assert db.get_cash(conn) == pytest.approx(9000.0)
    assert db.get_position(conn, "AAPL")["quantity"] == 10
    assert len(db.list_trades(conn)) == 1
    assert len(db.list_snapshots(conn)) == 1  # snapshot recorded after the trade


def test_weighted_average_cost(conn, price_cache):
    execute_trade(conn, price_cache, "AAPL", "buy", 10)
    price_cache.update("AAPL", 130.0)
    execute_trade(conn, price_cache, "AAPL", "buy", 5)
    pos = db.get_position(conn, "AAPL")
    assert pos["quantity"] == 15
    assert pos["avg_cost"] == pytest.approx((10 * 100 + 5 * 130) / 15)


def test_fractional_shares(conn, price_cache):
    execute_trade(conn, price_cache, "AAPL", "buy", 0.5)
    assert db.get_position(conn, "AAPL")["quantity"] == 0.5
    assert db.get_cash(conn) == pytest.approx(9950.0)


def test_sell_partial_keeps_avg_cost(conn, price_cache):
    execute_trade(conn, price_cache, "AAPL", "buy", 10)
    price_cache.update("AAPL", 120.0)
    execute_trade(conn, price_cache, "AAPL", "sell", 4)
    pos = db.get_position(conn, "AAPL")
    assert pos["quantity"] == 6 and pos["avg_cost"] == 100.0
    assert db.get_cash(conn) == pytest.approx(9000.0 + 480.0)


def test_sell_all_removes_position(conn, price_cache):
    execute_trade(conn, price_cache, "AAPL", "buy", 0.1)
    execute_trade(conn, price_cache, "AAPL", "buy", 0.2)  # 0.1 + 0.2 != 0.3 in floats
    execute_trade(conn, price_cache, "AAPL", "sell", 0.3)
    assert db.get_position(conn, "AAPL") is None
    assert db.get_cash(conn) == pytest.approx(10000.0)


def test_sell_at_a_loss(conn, price_cache):
    execute_trade(conn, price_cache, "AAPL", "buy", 10)
    price_cache.update("AAPL", 80.0)
    p = build_portfolio(conn, price_cache)
    assert p["unrealized_pnl"] == -200.0
    assert p["positions"][0]["unrealized_pnl_percent"] == -20.0
    execute_trade(conn, price_cache, "AAPL", "sell", 10)
    assert db.get_cash(conn) == pytest.approx(9800.0)
    assert build_portfolio(conn, price_cache)["total_value"] == 9800.0


@pytest.mark.parametrize(
    ("ticker", "side", "qty", "message"),
    [
        ("AAPL", "buy", 101, "Insufficient cash"),
        ("AAPL", "sell", 1, "Insufficient shares"),
        ("ZZZZ", "buy", 1, "No price available for ZZZZ"),
        ("AAPL", "buy", 0, "Quantity must be positive"),
        ("AAPL", "buy", -3, "Quantity must be positive"),
        ("AAPL", "buy", float("nan"), "Quantity must be positive"),
        ("AAPL", "hold", 1, "Invalid side"),
        ("", "buy", 1, "Invalid ticker"),
        ("AA PL1", "buy", 1, "Invalid ticker"),
    ],
)
def test_trade_validation(conn, price_cache, ticker, side, qty, message):
    with pytest.raises(TradeError, match=message):
        execute_trade(conn, price_cache, ticker, side, qty)
    assert db.get_cash(conn) == 10000.0
    assert db.list_trades(conn) == []


def test_insufficient_cash_message_is_user_facing(conn, price_cache):
    with pytest.raises(TradeError) as exc:
        execute_trade(conn, price_cache, "MSFT", "buy", 30)
    assert str(exc.value) == "Insufficient cash: need $12,000.00, have $10,000.00"


def test_build_portfolio_values_and_weights(conn, price_cache):
    execute_trade(conn, price_cache, "AAPL", "buy", 10)   # 1000
    execute_trade(conn, price_cache, "MSFT", "buy", 5)    # 2000
    price_cache.update("AAPL", 110.0)
    p = build_portfolio(conn, price_cache)
    assert p["cash_balance"] == 7000.0
    assert p["positions_value"] == 3100.0
    assert p["total_value"] == 10100.0
    assert p["unrealized_pnl"] == 100.0
    assert p["unrealized_pnl_percent"] == pytest.approx(3.33)
    aapl = next(x for x in p["positions"] if x["ticker"] == "AAPL")
    assert aapl == {
        "ticker": "AAPL", "quantity": 10.0, "avg_cost": 100.0, "current_price": 110.0,
        "market_value": 1100.0, "unrealized_pnl": 100.0, "unrealized_pnl_percent": 10.0,
        "weight": round(1100 / 10100 * 100, 2),
    }


def test_missing_price_falls_back_to_avg_cost(conn, price_cache):
    execute_trade(conn, price_cache, "AAPL", "buy", 10)
    price_cache.remove("AAPL")
    pos = build_portfolio(conn, price_cache)["positions"][0]
    assert pos["current_price"] == 100.0 and pos["unrealized_pnl"] == 0.0


def test_record_snapshot(conn, price_cache):
    snap = record_snapshot(conn, price_cache)
    assert snap["total_value"] == 10000.0
    assert db.list_snapshots(conn)[-1]["total_value"] == 10000.0
