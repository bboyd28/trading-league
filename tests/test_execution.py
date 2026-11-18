from datetime import datetime
from decimal import Decimal

import pytest

import core.database as database
import core.execution as execution
import core.portfolio as portfolio
from core.market_calendar import EASTERN

PLAYER = "123"
CLOSING = datetime(2026, 11, 16, 16, 5, tzinfo=EASTERN)    # market just closed, close not final
EVENING = datetime(2026, 11, 16, 17, 0, tzinfo=EASTERN)    # Monday, market closed
MIDDAY = datetime(2026, 11, 16, 12, 0, tzinfo=EASTERN)     # Monday, market open


@pytest.fixture
def league(setup_database, monkeypatch):
    portfolio.register_user(PLAYER, "Tester")
    monkeypatch.setattr(
        execution, "get_execution_price",
        lambda symbol, now: {
            "symbol": symbol, "price_date": "2026-11-16", "price": Decimal("100"),
        },
    )
    monkeypatch.setattr(
        execution, "get_live_price",
        lambda symbol, now: {
            "symbol": symbol, "price_date": "2026-11-16", "price": Decimal("105"), "live": True,
        },
    )


def set_model(model):
    execution.set_execution_model(model)


def test_buy_by_quantity(league):
    result = execution.place_order(PLAYER, "aapl", "buy", quantity="2", now=EVENING)

    assert result["symbol"] == "AAPL"
    assert result["side"] == "BUY"
    assert result["price_date"] == "2026-11-16"
    assert result["cash_change_cents"] == 20_020


def test_buy_by_amount(league):
    result = execution.place_order(PLAYER, "AAPL", "BUY", amount="500", now=EVENING)

    assert result["quantity"] == Decimal("5")


def test_sell_all(league):
    execution.place_order(PLAYER, "AAPL", "BUY", quantity="3", now=EVENING)
    result = execution.place_order(PLAYER, "AAPL", "SELL", quantity="ALL", now=EVENING)

    assert result["quantity"] == Decimal("3")
    assert portfolio.get_portfolio(PLAYER)["holdings"] == {}


def test_sell_by_amount(league):
    execution.place_order(PLAYER, "AAPL", "BUY", quantity="5", now=EVENING)
    result = execution.place_order(PLAYER, "AAPL", "SELL", amount="200", now=EVENING)

    assert result["quantity"] == Decimal("2")
    assert result["cash_change_cents"] == 19_980


def test_orders_blocked_while_market_is_open(league):
    with pytest.raises(ValueError, match="market is open"):
        execution.place_order(PLAYER, "AAPL", "BUY", quantity="1", now=MIDDAY)

    assert portfolio.get_portfolio(PLAYER)["holdings"] == {}


def test_any_time_model_ignores_the_window(league):
    set_model("any_time")

    result = execution.place_order(PLAYER, "AAPL", "BUY", quantity="1", now=MIDDAY)

    assert result["quantity"] == Decimal("1")
    assert result["filled_live"] is False


def test_unknown_execution_model_is_an_error(league):
    with database.get_connection(write=True) as connection:
        connection.execute("UPDATE league_settings SET execution_model = 'moon_phase'")

    with pytest.raises(RuntimeError, match="Unknown execution model"):
        execution.place_order(PLAYER, "AAPL", "BUY", quantity="1", now=EVENING)


@pytest.mark.parametrize("kwargs", [
    {},
    {"quantity": "1", "amount": "100"},
])
def test_needs_exactly_one_of_quantity_or_amount(league, kwargs):
    with pytest.raises(ValueError, match="either a quantity or a dollar amount"):
        execution.place_order(PLAYER, "AAPL", "BUY", now=EVENING, **kwargs)


def test_all_is_only_for_sells(league):
    with pytest.raises(ValueError, match="must be a number"):
        execution.place_order(PLAYER, "AAPL", "BUY", quantity="all", now=EVENING)


def test_bad_side_and_bad_symbol(league):
    with pytest.raises(ValueError, match="BUY or SELL"):
        execution.place_order(PLAYER, "AAPL", "HOLD", quantity="1", now=EVENING)

    with pytest.raises(ValueError, match="not a valid stock symbol"):
        execution.place_order(PLAYER, "$$$", "BUY", quantity="1", now=EVENING)


def test_bad_number_reaches_the_user_as_value_error(league):
    with pytest.raises(ValueError, match="must be a number"):
        execution.place_order(PLAYER, "AAPL", "BUY", quantity="abc", now=EVENING)


def test_register_saves_a_baseline_snapshot(setup_database):
    user = execution.register("999", "Newbie", now=EVENING)

    assert user["is_new"] is True

    with database.get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM portfolio_snapshots WHERE discord_id = '999'"
        ).fetchone()

    assert row["snapshot_date"] == "2026-11-16"
    assert row["total_value_cents"] == 10_000_000


def test_registering_twice_does_not_add_snapshots(setup_database):
    execution.register("999", "Newbie", now=EVENING)
    execution.register("999", "Renamed", now=EVENING)

    with database.get_connection() as connection:
        count = connection.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0]

    assert count == 1


# ---- live_quote model ----------------------------------------------------

def test_live_quote_fills_at_the_live_price_during_the_session(league):
    set_model("live_quote")

    result = execution.place_order(PLAYER, "AAPL", "BUY", quantity="2", now=MIDDAY)

    assert result["price_per_share"] == Decimal("105")
    assert result["filled_live"] is True


def test_live_quote_uses_the_close_when_the_market_is_shut(league):
    set_model("live_quote")

    result = execution.place_order(PLAYER, "AAPL", "BUY", quantity="2", now=EVENING)

    assert result["price_per_share"] == Decimal("100")
    assert result["filled_live"] is False


def test_live_quote_pauses_while_the_close_settles(league):
    set_model("live_quote")

    with pytest.raises(ValueError, match="being finalized"):
        execution.place_order(PLAYER, "AAPL", "BUY", quantity="1", now=CLOSING)


def test_daily_close_never_uses_live_prices(league):
    set_model("daily_close")

    result = execution.place_order(PLAYER, "AAPL", "BUY", quantity="1", now=EVENING)

    assert result["filled_live"] is False


def test_live_prices_are_only_used_in_session(league):
    set_model("live_quote")
    assert execution.live_prices_enabled(MIDDAY) is True
    assert execution.live_prices_enabled(EVENING) is False

    set_model("daily_close")
    assert execution.live_prices_enabled(MIDDAY) is False


def test_set_execution_model_rejects_unknown_values(league):
    with pytest.raises(ValueError, match="Model must be one of"):
        execution.set_execution_model("moon_phase")

    assert execution.get_execution_model() == "daily_close"


def test_a_live_trade_counts_in_that_days_snapshot(league, monkeypatch):
    """Bought at 105 midday, valued at the 110 close: the day's gain shows up."""
    set_model("live_quote")
    execution.place_order(PLAYER, "AAPL", "BUY", quantity="10", now=MIDDAY)
    monkeypatch.setattr(
        portfolio, "get_prices_on_or_before",
        lambda symbols, date: {s: {"symbol": s, "price_date": date, "price": Decimal("110")}
                               for s in symbols},
    )

    saved = portfolio.save_portfolio_snapshot(PLAYER, "2026-11-16", require_exact_prices=True)

    # 100,000 - 1,050 cost - 1.05 fee + 1,100 market value
    assert saved["total_value"] == Decimal("100048.95")
