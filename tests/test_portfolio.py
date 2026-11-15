import pytest
from decimal import Decimal

import core.database as database
import core.portfolio as portfolio


@pytest.fixture
def setup_database(tmp_path, monkeypatch):
    """
    Create a fresh temporary database for each test.
    """

    test_database = tmp_path / "test_league.db"

    monkeypatch.setattr(database, "DATABASE_PATH", test_database)

    database.initialize_database()

    return test_database

def test_register_user(setup_database):
    user = portfolio.register_user(
        "123456789",
        "TestPlayer"
    )

    assert user["discord_id"] == "123456789"
    assert user["username"] == "TestPlayer"
    assert user["cash_balance_cents"] == 10_000_000

def test_register_existing_user(setup_database):
    
    portfolio.register_user("123456789", "TestPlayer")

    
    portfolio.buy_stock(
        "123456789",
        "AAPL",
        Decimal("2"),
        Decimal("100"),
        "2026-11-14"
    )

    
    user = portfolio.register_user(
        "123456789",
        "UpdatedPlayer"
    )

    
    assert user["username"] == "UpdatedPlayer"

    
    assert user["cash_balance_cents"] == 9_979_980

def test_buy_stock(setup_database):
    portfolio.register_user("123456789", "TestPlayer")

    result = portfolio.buy_stock(
        "123456789",
        "AAPL",
        Decimal("2.5"),
        Decimal("100"),
        "2026-11-14"
    )

    assert result["symbol"] == "AAPL"
    assert result["quantity"] == Decimal("2.5")
    assert result["gross_amount_cents"] == 25_000
    assert result["fee_cents"] == 25
    assert result["total_cost_cents"] == 25_025

    user_portfolio = portfolio.get_portfolio("123456789")

    assert user_portfolio["cash_balance"] == Decimal("99749.75")
    assert user_portfolio["holdings"]["AAPL"] == Decimal("2.5")

def test_buy_stock_insufficient_funds(setup_database):
    portfolio.register_user("123456789", "TestPlayer")

    with pytest.raises(ValueError, match="Insufficient funds"):
        portfolio.buy_stock(
            "123456789",
            "AAPL",
            Decimal("2000"),
            Decimal("100"),
            "2026-11-14"
        )

    user_portfolio = portfolio.get_portfolio("123456789")

    assert user_portfolio["cash_balance"] == Decimal("100000")
    assert user_portfolio["holdings"] == {}


def test_sell_stock(setup_database):
    portfolio.register_user("123456789", "TestPlayer")


    portfolio.buy_stock(
        "123456789",
        "AAPL",
        Decimal("2.5"),
        Decimal("100"),
        "2026-11-14"
    )


    result = portfolio.sell_stock(
        "123456789",
        "AAPL",
        Decimal("1"),
        Decimal("110"),
        "2026-11-15"
    )

    assert result["gross_amount_cents"] == 11_000
    assert result["fee_cents"] == 11
    assert result["net_proceeds_cents"] == 10_989


    user_portfolio = portfolio.get_portfolio("123456789")

    assert user_portfolio["cash_balance"] == Decimal("99859.64")
    assert user_portfolio["holdings"]["AAPL"] == Decimal("1.5")


def test_sell_stock_insufficient_shares(setup_database):
    portfolio.register_user("123456789", "TestPlayer")

    # Purchase 1.5 shares.
    portfolio.buy_stock(
        "123456789",
        "AAPL",
        Decimal("1.5"),
        Decimal("100"),
        "2026-11-14"
    )

    # Attempt to sell 2 shares.
    with pytest.raises(ValueError, match="Insufficient shares"):
        portfolio.sell_stock(
            "123456789",
            "AAPL",
            Decimal("2"),
            Decimal("110"),
            "2026-11-15"
        )

    # Verify that the failed sale changed nothing.
    user_portfolio = portfolio.get_portfolio("123456789")

    assert user_portfolio["cash_balance"] == Decimal("99849.85")
    assert user_portfolio["holdings"]["AAPL"] == Decimal("1.5")


def test_sell_all_shares(setup_database):
    portfolio.register_user("123456789", "TestPlayer")

    portfolio.buy_stock(
        "123456789",
        "AAPL",
        Decimal("2"),
        Decimal("100"),
        "2026-11-14"
    )

    portfolio.sell_stock(
        "123456789",
        "AAPL",
        Decimal("2"),
        Decimal("110"),
        "2026-11-15"
    )

    user_portfolio = portfolio.get_portfolio("123456789")

    assert user_portfolio["holdings"] == {}


def test_multiple_stock_holdings(setup_database):
    portfolio.register_user("123456789", "TestPlayer")

    portfolio.buy_stock(
        "123456789",
        "AAPL",
        Decimal("2"),
        Decimal("100"),
        "2026-11-14"
    )

    portfolio.buy_stock(
        "123456789",
        "MSFT",
        Decimal("3"),
        Decimal("200"),
        "2026-11-14"
    )

    # Sell half a share of AAPL.
    portfolio.sell_stock(
        "123456789",
        "AAPL",
        Decimal("0.5"),
        Decimal("110"),
        "2026-11-15"
    )

    user_portfolio = portfolio.get_portfolio("123456789")

    assert user_portfolio["holdings"]["AAPL"] == Decimal("1.5")
    assert user_portfolio["holdings"]["MSFT"] == Decimal("3")