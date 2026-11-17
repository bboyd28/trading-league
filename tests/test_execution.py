from datetime import datetime
from decimal import Decimal

import pytest

import core.database as database
import core.execution as execution
import core.portfolio as portfolio
from core.market_calendar import EASTERN

PLAYER = "123"
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


def set_model(model):
    with database.get_connection(write=True) as connection:
        connection.execute("UPDATE league_settings SET execution_model = ?", (model,))


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


def test_unknown_execution_model_is_an_error(league):
    set_model("moon_phase")

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
