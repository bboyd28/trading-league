from datetime import datetime
from decimal import Decimal

import pandas as pd
import pytest

import core.database as database
import core.prices as prices
from core.market_calendar import EASTERN

MONDAY_EVENING = datetime(2026, 11, 16, 17, 0, tzinfo=EASTERN)
MONDAY_MIDDAY = datetime(2026, 11, 16, 12, 0, tzinfo=EASTERN)


def make_frame(rows):
    """rows: [(date, close, adj_close)] -> frame shaped like Yahoo's."""
    index = pd.to_datetime([r[0] for r in rows]).tz_localize("America/New_York")
    return pd.DataFrame(
        {"Close": [r[1] for r in rows], "Adj Close": [r[2] for r in rows]},
        index=index,
    )


def add_price(symbol, date, close):
    with database.get_connection(write=True) as connection:
        connection.execute("""
            INSERT INTO price_history (symbol, price_date, close_price, adjusted_close)
            VALUES (?, ?, ?, ?)
        """, (symbol, date, close, close))


class FakeTicker:
    frame = None

    def __init__(self, symbol):
        pass

    def history(self, **kwargs):
        return self.frame


# ---- symbols -------------------------------------------------------------

@pytest.mark.parametrize("raw, clean", [
    ("aapl", "AAPL"), (" spy ", "SPY"), ("brk-b", "BRK-B"), ("BF.B", "BF.B"),
])
def test_normalize_symbol(raw, clean):
    assert prices.normalize_symbol(raw) == clean


@pytest.mark.parametrize("bad", ["", "   ", "^GSPC", "BTC-USD", "TOOLONGX", "A B", "AAPL;"])
def test_normalize_symbol_rejects_junk(bad):
    with pytest.raises(ValueError, match="not a valid stock symbol"):
        prices.normalize_symbol(bad)


# ---- downloading and storing ---------------------------------------------

def test_fetch_drops_unfinished_session(monkeypatch):
    FakeTicker.frame = make_frame([
        ("2026-11-12", 100.0, 100.0),
        ("2026-11-13", 101.0, 101.0),
        ("2026-11-16", 102.0, 102.0),   # today's live bar
    ])
    monkeypatch.setattr(prices.yf, "Ticker", FakeTicker)

    result = prices.fetch_daily_prices("AAPL", now=MONDAY_MIDDAY)

    assert [d.strftime("%Y-%m-%d") for d in result.index] == ["2026-11-12", "2026-11-13"]


def test_fetch_keeps_today_after_the_close_settles(monkeypatch):
    FakeTicker.frame = make_frame([("2026-11-13", 101.0, 101.0), ("2026-11-16", 102.0, 102.0)])
    monkeypatch.setattr(prices.yf, "Ticker", FakeTicker)

    result = prices.fetch_daily_prices("AAPL", now=MONDAY_EVENING)

    assert len(result) == 2


def test_fetch_empty_result_is_a_value_error(monkeypatch):
    FakeTicker.frame = pd.DataFrame()
    monkeypatch.setattr(prices.yf, "Ticker", FakeTicker)

    with pytest.raises(ValueError, match="No price data found"):
        prices.fetch_daily_prices("ZZZZ")


def test_fetch_wraps_provider_errors(monkeypatch):
    class Broken(FakeTicker):
        def history(self, **kwargs):
            raise ConnectionError("offline")

    monkeypatch.setattr(prices.yf, "Ticker", Broken)

    with pytest.raises(RuntimeError, match="Could not reach the price provider"):
        prices.fetch_daily_prices("AAPL")


def test_store_rounds_float_noise_and_handles_missing_adjusted(setup_database):
    frame = make_frame([
        ("2026-11-12", 227.4600067138672, 226.9100036621094),
        ("2026-11-13", 228.0, float("nan")),
    ])

    prices.store_price_history("AAPL", frame)

    with database.get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM price_history ORDER BY price_date"
        ).fetchall()

    assert rows[0]["close_price"] == "227.4600"
    assert rows[0]["adjusted_close"] == "226.9100"
    assert rows[1]["adjusted_close"] is None


def test_store_updates_existing_day(setup_database):
    prices.store_price_history("AAPL", make_frame([("2026-11-13", 100.0, 100.0)]))
    prices.store_price_history("AAPL", make_frame([("2026-11-13", 105.0, 105.0)]))

    assert prices.get_price_on_or_before("AAPL", "2026-11-13")["price"] == Decimal("105.0000")


# ---- lookups -------------------------------------------------------------

def test_price_on_or_before_uses_latest_earlier_close(setup_database):
    add_price("AAPL", "2026-11-12", "100")
    add_price("AAPL", "2026-11-13", "101")

    found = prices.get_price_on_or_before("AAPL", "2026-11-15")

    assert found == {"symbol": "AAPL", "price_date": "2026-11-13", "price": Decimal("101")}


def test_price_lookup_without_history(setup_database):
    with pytest.raises(ValueError, match="No price history found for AAPL"):
        prices.get_price_on_or_before("AAPL", "2026-11-15")


def test_latest_prices_for_several_symbols(setup_database):
    add_price("AAPL", "2026-11-13", "101")
    add_price("MSFT", "2026-11-12", "300")

    found = prices.get_latest_prices(["AAPL", "MSFT"])

    assert found["AAPL"]["price"] == Decimal("101")
    assert found["MSFT"]["price_date"] == "2026-11-12"


# ---- execution price -----------------------------------------------------

def test_execution_price_uses_fresh_history_without_downloading(setup_database, monkeypatch):
    add_price("AAPL", "2026-11-16", "250")

    def no_download(*args, **kwargs):
        raise AssertionError("should not download")

    monkeypatch.setattr(prices, "update_stock_prices", no_download)

    result = prices.get_execution_price("AAPL", MONDAY_EVENING)

    assert result["price"] == Decimal("250")


def test_execution_price_refreshes_stale_history(setup_database, monkeypatch):
    add_price("AAPL", "2026-11-13", "240")
    calls = []

    def fake_update(symbol, period="1mo"):
        calls.append(symbol)
        add_price(symbol, "2026-11-16", "250")
        return 1

    monkeypatch.setattr(prices, "update_stock_prices", fake_update)

    result = prices.get_execution_price("AAPL", MONDAY_EVENING)

    assert calls == ["AAPL"]
    assert result["price_date"] == "2026-11-16"


def test_execution_price_downloads_new_symbols(setup_database, monkeypatch):
    def fake_update(symbol, period="1mo"):
        add_price(symbol, "2026-11-16", "250")

    monkeypatch.setattr(prices, "update_stock_prices", fake_update)

    assert prices.get_execution_price("NVDA", MONDAY_EVENING)["price"] == Decimal("250")


def test_execution_price_refuses_a_stale_close(setup_database, monkeypatch):
    add_price("AAPL", "2026-11-13", "240")
    monkeypatch.setattr(prices, "update_stock_prices", lambda symbol, period="1mo": 0)

    with pytest.raises(ValueError, match="isn't available yet"):
        prices.get_execution_price("AAPL", MONDAY_EVENING)


def test_refresh_cooldown_limits_downloads(setup_database, monkeypatch):
    add_price("AAPL", "2026-11-13", "240")
    calls = []
    monkeypatch.setattr(
        prices, "update_stock_prices",
        lambda symbol, period="1mo": calls.append(symbol),
    )

    for _ in range(3):
        with pytest.raises(ValueError):
            prices.get_execution_price("AAPL", MONDAY_EVENING)

    assert calls == ["AAPL"]
