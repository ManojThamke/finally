from app.market import PriceCache, PriceUpdate


def test_first_update_is_flat():
    cache = PriceCache()
    u = cache.update("aapl", 190.0)
    assert u.ticker == "AAPL"
    assert u.previous_price == 190.0 and u.direction == "flat"
    assert u.session_open == 190.0


def test_direction_and_session_open_carry_over():
    cache = PriceCache()
    cache.update("AAPL", 100.0)
    up = cache.update("AAPL", 101.0)
    assert up.direction == "up" and up.previous_price == 100.0
    assert up.day_change_percent == 1.0
    down = cache.update("AAPL", 99.5)
    assert down.direction == "down" and down.session_open == 100.0


def test_session_open_override_and_rounding():
    cache = PriceCache()
    u = cache.update("AAPL", 190.004, session_open=189.5)
    assert u.price == 190.0 and u.session_open == 189.5
    assert cache.update("AAPL", 191.0).session_open == 189.5


def test_version_and_remove():
    cache = PriceCache()
    v0 = cache.version
    cache.update("MSFT", 420.0)
    assert cache.version == v0 + 1
    cache.remove("MSFT")
    assert "MSFT" not in cache and cache.version == v0 + 2
    cache.remove("MSFT")                 # unknown -> no version bump
    assert cache.version == v0 + 2


def test_getters_are_case_insensitive():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    assert cache.get_price("aapl") == 190.0
    assert cache.get("nope") is None and cache.get_price("nope") is None
    assert len(cache) == 1 and list(cache.get_all()) == ["AAPL"]


def test_get_all_returns_copy():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.get_all().clear()
    assert "AAPL" in cache


def test_to_dict_contract():
    d = PriceCache().update("V", 280.0).to_dict()
    assert set(d) == {"ticker", "price", "previous_price", "session_open", "timestamp",
                      "change", "change_percent", "day_change_percent", "direction"}


def test_price_update_zero_reference_guards():
    u = PriceUpdate("X", 1.0, 0.0, 0.0, 1.0)
    assert u.change_percent == 0.0 and u.day_change_percent == 0.0
