from __future__ import annotations

import sqlite3
import threading

import pytest

import app.db as db
from app.db import connection


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "nested" / "finally.db"


@pytest.fixture
def conn(db_path):
    with db.get_connection(db_path) as c:
        yield c


# --- init / seed / connection ------------------------------------------------

def test_init_creates_dirs_tables_and_seed(db_path):
    db.init_db(db_path)
    assert db_path.exists()
    with db.get_connection(db_path) as c:
        tables = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"users_profile", "watchlist", "positions", "trades",
                "portfolio_snapshots", "chat_messages"} <= tables
        assert db.get_cash(c) == 10000.0
        assert db.list_watchlist(c) == list(db.DEFAULT_TICKERS)
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert isinstance(c.execute("SELECT 1 AS x").fetchone(), sqlite3.Row)


def test_init_is_idempotent_and_preserves_data(db_path):
    db.init_db(db_path)
    with db.get_connection(db_path) as c:
        db.set_cash(c, 123.0)
        db.remove_watchlist_ticker(c, "AAPL")
    db.init_db(db_path)
    db.init_db(db_path)
    with db.get_connection(db_path) as c:
        assert db.get_cash(c) == 123.0
        assert "AAPL" not in db.list_watchlist(c)
        assert c.execute("SELECT COUNT(*) FROM users_profile").fetchone()[0] == 1


def test_emptied_watchlist_is_not_reseeded(db_path):
    with db.get_connection(db_path) as c:
        for t in db.list_watchlist(c):
            db.remove_watchlist_ticker(c, t)
    db.init_db(db_path)
    with db.get_connection(db_path) as c:
        assert db.list_watchlist(c) == []


def test_get_connection_lazily_inits_and_reinits_deleted_file(db_path):
    with db.get_connection(db_path) as c:
        assert db.get_cash(c) == 10000.0
    db_path.unlink()
    for suffix in ("-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    with db.get_connection(db_path) as c:
        assert len(db.list_watchlist(c)) == 10


def test_commit_on_success_rollback_on_error(db_path):
    with db.get_connection(db_path) as c:
        db.set_cash(c, 500.0)
    with pytest.raises(RuntimeError):
        with db.get_connection(db_path) as c:
            db.set_cash(c, 1.0)
            raise RuntimeError("boom")
    with db.get_connection(db_path) as c:
        assert db.get_cash(c) == 500.0


def test_env_var_db_path(tmp_path, monkeypatch):
    target = tmp_path / "env" / "x.db"
    monkeypatch.setenv("FINALLY_DB_PATH", str(target))
    assert connection.default_db_path() == target
    with db.get_connection() as c:
        assert db.get_cash(c) == 10000.0
    assert target.exists()


def test_default_path_is_repo_db_dir(monkeypatch):
    monkeypatch.delenv("FINALLY_DB_PATH", raising=False)
    p = connection.default_db_path()
    assert p.name == "finally.db" and p.parent.name == "db"
    assert (p.parent.parent / "backend").is_dir()


def test_concurrent_connections_from_threads(db_path):
    db.init_db(db_path)
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            for j in range(5):
                with db.get_connection(db_path) as c:
                    db.insert_trade(c, "AAPL", "buy", 1, 100.0 + i + j)
        except Exception as e:  # pragma: no cover - surfaced by assert below
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with db.get_connection(db_path) as c:
        assert len(db.list_trades(c, limit=100)) == 40


# --- cash --------------------------------------------------------------------

def test_cash_set_get(conn):
    db.set_cash(conn, 4321.5)
    assert db.get_cash(conn) == 4321.5


def test_cash_other_user_isolated(conn):
    assert db.get_cash(conn, user_id="alice") == 10000.0
    db.set_cash(conn, 1.0, user_id="alice")
    assert db.get_cash(conn) == 10000.0
    assert db.get_cash(conn, user_id="alice") == 1.0


# --- watchlist -----------------------------------------------------------------

def test_watchlist_add_remove(conn):
    assert db.add_watchlist_ticker(conn, "pypl") is True
    assert db.list_watchlist(conn)[-1] == "PYPL"
    assert db.add_watchlist_ticker(conn, "PYPL") is False
    assert db.remove_watchlist_ticker(conn, "PYPL") is True
    assert db.remove_watchlist_ticker(conn, "PYPL") is False
    assert "PYPL" not in db.list_watchlist(conn)


def test_watchlist_ordered_by_insertion(conn):
    for t in ("ZZZ", "AAA", "MMM"):
        db.add_watchlist_ticker(conn, t)
    assert db.list_watchlist(conn)[-3:] == ["ZZZ", "AAA", "MMM"]


def test_watchlist_unique_constraint(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES ('x', 'default', 'AAPL', 'now')"
        )


def test_watchlist_per_user(conn):
    assert db.add_watchlist_ticker(conn, "AAPL", user_id="bob") is True
    assert db.list_watchlist(conn, user_id="bob") == ["AAPL"]


# --- positions -----------------------------------------------------------------

def test_positions_crud(conn):
    assert db.list_positions(conn) == []
    assert db.get_position(conn, "AAPL") is None
    db.upsert_position(conn, "aapl", 10, 190.0)
    pos = db.get_position(conn, "AAPL")
    assert set(pos) == {"ticker", "quantity", "avg_cost", "updated_at"}
    assert (pos["ticker"], pos["quantity"], pos["avg_cost"]) == ("AAPL", 10.0, 190.0)

    db.upsert_position(conn, "AAPL", 15.5, 195.0)
    assert db.get_position(conn, "AAPL")["quantity"] == 15.5
    assert conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 1

    db.upsert_position(conn, "MSFT", 2, 400.0)
    assert [p["ticker"] for p in db.list_positions(conn)] == ["AAPL", "MSFT"]

    db.delete_position(conn, "AAPL")
    assert db.get_position(conn, "AAPL") is None
    db.delete_position(conn, "AAPL")  # no-op
    assert [p["ticker"] for p in db.list_positions(conn)] == ["MSFT"]


def test_positions_unique_constraint(conn):
    db.upsert_position(conn, "AAPL", 1, 1.0)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
            "VALUES ('x', 'default', 'AAPL', 1, 1, 'now')"
        )


# --- trades --------------------------------------------------------------------

def test_insert_and_list_trades_newest_first(conn):
    t1 = db.insert_trade(conn, "aapl", "buy", 1.5, 190.0)
    assert set(t1) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
    assert t1["ticker"] == "AAPL"
    t2 = db.insert_trade(conn, "MSFT", "sell", 2, 400.0)
    t3 = db.insert_trade(conn, "TSLA", "buy", 3, 250.0)
    trades = db.list_trades(conn)
    assert [t["id"] for t in trades] == [t3["id"], t2["id"], t1["id"]]
    assert trades[-1] == t1
    assert [t["id"] for t in db.list_trades(conn, limit=2)] == [t3["id"], t2["id"]]


def test_trade_side_check(conn):
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_trade(conn, "AAPL", "hold", 1, 1.0)


# --- snapshots -----------------------------------------------------------------

def test_snapshots_oldest_first_and_limit(conn):
    assert db.list_snapshots(conn) == []
    snaps = [db.insert_snapshot(conn, v) for v in (10000.0, 10050.0, 9990.0, 10100.0)]
    assert set(snaps[0]) == {"id", "total_value", "recorded_at"}
    assert db.list_snapshots(conn) == snaps
    assert db.list_snapshots(conn, limit=2) == snaps[-2:]


# --- chat ----------------------------------------------------------------------

def test_chat_actions_round_trip(conn):
    actions = {
        "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10, "status": "executed",
                    "price": 190.1, "error": None}],
        "watchlist_changes": [{"ticker": "PYPL", "action": "add", "status": "failed", "error": "x"}],
    }
    u = db.insert_chat_message(conn, "user", "buy 10 AAPL")
    a = db.insert_chat_message(conn, "assistant", "Done.", actions)
    lst = db.insert_chat_message(conn, "assistant", "list", [1, "two"])
    assert set(u) == {"id", "role", "content", "actions", "created_at"}
    msgs = db.list_chat_messages(conn)
    assert [m["id"] for m in msgs] == [u["id"], a["id"], lst["id"]]
    assert msgs[0]["actions"] is None
    assert msgs[1]["actions"] == actions
    assert msgs[2]["actions"] == [1, "two"]
    assert msgs[1] == a


def test_chat_limit_returns_most_recent_oldest_first(conn):
    ids = [db.insert_chat_message(conn, "user", f"m{i}")["id"] for i in range(30)]
    msgs = db.list_chat_messages(conn, limit=5)
    assert [m["id"] for m in msgs] == ids[-5:]
    assert len(db.list_chat_messages(conn)) == 20


def test_chat_role_check(conn):
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_chat_message(conn, "system", "nope")


def test_repository_does_not_commit(db_path):
    with db.get_connection(db_path) as c:
        pass
    c1 = connection._connect(db_path.resolve())
    try:
        db.insert_trade(c1, "AAPL", "buy", 1, 1.0)
        with db.get_connection(db_path) as c2:
            assert db.list_trades(c2) == []
        c1.rollback()
    finally:
        c1.close()
