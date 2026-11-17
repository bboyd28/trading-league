import pytest
from decimal import Decimal

import core.database as database
import core.portfolio as portfolio


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

def test_save_portfolio_snapshot(setup_database, monkeypatch):
    portfolio.register_user("123456789", "TestUser")

    portfolio.buy_stock(
        "123456789",
        "AAPL",
        Decimal("2"),
        Decimal("100"),
        "2026-11-14"
    )

    # Pretend AAPL's latest stored price is $110.
    monkeypatch.setattr(
        portfolio,
        "get_price_on_or_before",
        lambda symbol, target_date: {
            "symbol": symbol,
            "price_date": "2026-11-13",
            "price": Decimal("110")
        }
    )

    result = portfolio.save_portfolio_snapshot(
        "123456789",
        "2026-11-14"
    )

    assert result["cash_balance"] == Decimal("99799.80")
    assert result["holdings_value"] == Decimal("220")
    assert result["total_value"] == Decimal("100019.80")


def test_update_existing_snapshot(setup_database, monkeypatch):
    portfolio.register_user("123456789", "TestUser")

    portfolio.buy_stock(
        "123456789",
        "AAPL",
        Decimal("2"),
        Decimal("100"),
        "2026-11-14"
    )

    # First snapshot: AAPL is worth $110.
    monkeypatch.setattr(
        portfolio,
        "get_price_on_or_before",
        lambda symbol, target_date: {
            "symbol": symbol,
            "price_date": "2026-11-13",
            "price": Decimal("110")
        }
    )

    portfolio.save_portfolio_snapshot(
        "123456789",
        "2026-11-14"
    )

    # Second snapshot: AAPL is now worth $120.
    monkeypatch.setattr(
        portfolio,
        "get_price_on_or_before",
        lambda symbol, target_date: {
            "symbol": symbol,
            "price_date": "2026-11-14",
            "price": Decimal("120")
        }
    )

    result = portfolio.save_portfolio_snapshot(
        "123456789",
        "2026-11-14"
    )

    assert result["holdings_value"] == Decimal("220")
    assert result["total_value"] == Decimal("100019.80")

    with database.get_connection() as connection:
        snapshots = connection.execute("""
            SELECT *
            FROM portfolio_snapshots
            WHERE discord_id = ?
            AND snapshot_date = ?
        """, ("123456789", "2026-11-14")).fetchall()

    assert len(snapshots) == 1
def test_get_active_symbols(setup_database):
    portfolio.register_user("111", "Alice")
    portfolio.register_user("222", "Bob")

    # Alice buys AAPL and MSFT.
    portfolio.buy_stock(
        "111", "AAPL", Decimal("5"), Decimal("100"), "2026-11-14"
    )

    portfolio.buy_stock(
        "111", "MSFT", Decimal("2"), Decimal("100"), "2026-11-14"
    )

    # Alice sells all her MSFT shares.
    portfolio.sell_stock(
        "111", "MSFT", Decimal("2"), Decimal("100"), "2026-11-14"
    )

    # Bob also buys AAPL and buys NVDA.
    portfolio.buy_stock(
        "222", "AAPL", Decimal("3"), Decimal("100"), "2026-11-14"
    )

    portfolio.buy_stock(
        "222", "NVDA", Decimal("1"), Decimal("100"), "2026-11-14"
    )

    assert portfolio.get_active_symbols() == ["AAPL", "NVDA"]


def test_get_active_users(setup_database):
    portfolio.register_user("111", "Alice")
    portfolio.register_user("222", "Bob")

    with database.get_connection() as connection:
        connection.execute("""
            UPDATE users
            SET is_active = 0
            WHERE discord_id = '222'
        """)

    assert portfolio.get_active_users() == ["111"]


def test_historical_valuation(setup_database, monkeypatch):
    """
    Verify that a portfolio is valued using historical prices
    and only includes trades on or before the target date.
    """

    # Register a test participant.
    portfolio.register_user("123", "TestPlayer")

    # Simulate a purchase on November 14.
    portfolio.buy_stock(
        "123",
        "AAPL",
        Decimal("2"),
        Decimal("100"),
        "2026-11-14"
    )

    # Mock the historical price lookup.
    def mock_historical_price(symbol, target_date):
        return {
            "symbol": symbol,
            "price_date": "2026-11-13",
            "price": Decimal("110")
        }

    monkeypatch.setattr(
        portfolio,
        "get_price_on_or_before",
        mock_historical_price
    )

    # Value the portfolio as of November 13.
    earlier = portfolio.get_historical_valued_portfolio(
        "123",
        "2026-11-13"
    )

    assert earlier["cash_balance"] == Decimal("100000")
    assert earlier["holdings"] == {}
    assert earlier["total_value"] == Decimal("100000")

    # Value the portfolio as of November 14.
    later = portfolio.get_historical_valued_portfolio(
        "123",
        "2026-11-14"
    )

    assert later["cash_balance"] == Decimal("99799.80")
    assert later["holdings"]["AAPL"]["quantity"] == Decimal("2")
    assert later["holdings"]["AAPL"]["price"] == Decimal("110")
    assert later["holdings_value"] == Decimal("220")
    assert later["total_value"] == Decimal("100019.80")

def test_historical_valuation_after_sale(setup_database, monkeypatch):
    """
    Verify that historical valuation correctly accounts
    for purchases and sales.
    """

    portfolio.register_user("123", "TestPlayer")

    # Purchase 4 shares at $100 each.
    portfolio.buy_stock(
        "123",
        "AAPL",
        Decimal("4"),
        Decimal("100"),
        "2026-11-13"
    )

    # Sell 1 share at $120.
    portfolio.sell_stock(
        "123",
        "AAPL",
        Decimal("1"),
        Decimal("120"),
        "2026-11-14"
    )

    # Mock the historical price lookup.
    def mock_historical_price(symbol, target_date):
        prices = {
            "2026-11-13": Decimal("110"),
            "2026-11-14": Decimal("125")
        }

        return {
            "symbol": symbol,
            "price_date": target_date,
            "price": prices[target_date]
        }

    monkeypatch.setattr(
        portfolio,
        "get_price_on_or_before",
        mock_historical_price
    )

    # Before the sale: all 4 shares should be held.
    before_sale = portfolio.get_historical_valued_portfolio(
        "123",
        "2026-11-13"
    )

    assert before_sale["holdings"]["AAPL"]["quantity"] == Decimal("4")
    assert before_sale["cash_balance"] == Decimal("99599.60")
    assert before_sale["total_value"] == Decimal("100039.60")

    # After the sale: only 3 shares should remain.
    after_sale = portfolio.get_historical_valued_portfolio(
        "123",
        "2026-11-14"
    )

    assert after_sale["holdings"]["AAPL"]["quantity"] == Decimal("3")
    assert after_sale["cash_balance"] == Decimal("99719.48")
    assert after_sale["holdings_value"] == Decimal("375")
    assert after_sale["total_value"] == Decimal("100094.48")


def test_historical_valuation_multiple_stocks(setup_database, monkeypatch):
    """
    Verify that multiple stocks are independently valued
    using their respective historical prices.
    """

    portfolio.register_user("123", "TestPlayer")

    portfolio.buy_stock(
        "123",
        "AAPL",
        Decimal("2"),
        Decimal("100"),
        "2026-11-13"
    )

    portfolio.buy_stock(
        "123",
        "MSFT",
        Decimal("3"),
        Decimal("200"),
        "2026-11-13"
    )

    # Provide different historical prices for each stock.
    def mock_historical_price(symbol, target_date):
        prices = {
            "AAPL": Decimal("110"),
            "MSFT": Decimal("190")
        }

        return {
            "symbol": symbol,
            "price_date": target_date,
            "price": prices[symbol]
        }

    monkeypatch.setattr(
        portfolio,
        "get_price_on_or_before",
        mock_historical_price
    )

    result = portfolio.get_historical_valued_portfolio(
        "123",
        "2026-11-13"
    )

    assert result["holdings"]["AAPL"]["market_value"] == Decimal("220")
    assert result["holdings"]["MSFT"]["market_value"] == Decimal("570")

    assert result["holdings_value"] == Decimal("790")
    assert result["cash_balance"] == Decimal("99199.20")
    assert result["total_value"] == Decimal("99989.20")

def test_recalculate_portfolio_snapshot(setup_database, monkeypatch):
    """
    Verify that an existing snapshot can be intentionally recalculated.
    """

    portfolio.register_user("123", "TestPlayer")

    portfolio.buy_stock(
        "123",
        "AAPL",
        Decimal("2"),
        Decimal("100"),
        "2026-11-14"
    )

    # Initial historical price: $110.
    monkeypatch.setattr(
        portfolio,
        "get_price_on_or_before",
        lambda symbol, target_date: {
            "symbol": symbol,
            "price_date": "2026-11-13",
            "price": Decimal("110")
        }
    )

    portfolio.save_portfolio_snapshot("123", "2026-11-14")

    # Corrected historical price: $120.
    monkeypatch.setattr(
        portfolio,
        "get_price_on_or_before",
        lambda symbol, target_date: {
            "symbol": symbol,
            "price_date": "2026-11-13",
            "price": Decimal("120")
        }
    )

    result = portfolio.recalculate_portfolio_snapshot(
        "123",
        "2026-11-14"
    )

    assert result["holdings_value"] == Decimal("240")
    assert result["total_value"] == Decimal("100039.80")

def test_recalculate_nonexistent_snapshot(setup_database):
    """
    Verify that recalculation fails when no snapshot exists.
    """

    portfolio.register_user("123", "TestPlayer")

    with pytest.raises(
        ValueError,
        match="Cannot recalculate a snapshot that does not exist."
    ):
        portfolio.recalculate_portfolio_snapshot(
            "123",
            "2026-11-14"
        )


def test_buy_stock_by_amount(setup_database):
    portfolio.register_user("123456789", "TestPlayer")

    result = portfolio.buy_stock_by_amount(
        "123456789",
        "AAPL",
        Decimal("500"),
        Decimal("200"),
        "2026-11-16"
    )

    assert result["quantity"] == Decimal("2.5")
    assert result["gross_amount_cents"] == 50_000
    assert result["fee_cents"] == 50
    assert result["total_cost_cents"] == 50_050

    user_portfolio = portfolio.get_portfolio("123456789")

    assert user_portfolio["cash_balance"] == Decimal("99499.50")
    assert user_portfolio["holdings"]["AAPL"] == Decimal("2.5")

def test_sell_stock_by_amount(setup_database):
    portfolio.register_user("123456789", "TestPlayer")

    portfolio.buy_stock(
        "123456789",
        "AAPL",
        Decimal("5"),
        Decimal("100"),
        "2026-11-14"
    )

    result = portfolio.sell_stock_by_amount(
        "123456789",
        "AAPL",
        Decimal("200"),
        Decimal("110"),
        "2026-11-15"
    )

    assert result["gross_amount_cents"] == 20_000
    assert result["fee_cents"] == 20
    assert result["net_proceeds_cents"] == 19_980

    user_portfolio = portfolio.get_portfolio("123456789")

    assert user_portfolio["holdings"]["AAPL"] < Decimal("5")
    assert user_portfolio["cash_balance"] == Decimal("99699.30")


def test_sell_stock_by_amount_insufficient_shares(setup_database):
    portfolio.register_user("123456789", "TestPlayer")

    portfolio.buy_stock(
        "123456789",
        "AAPL",
        Decimal("2"),
        Decimal("100"),
        "2026-11-14"
    )

    with pytest.raises(ValueError, match="Insufficient shares"):
        portfolio.sell_stock_by_amount(
            "123456789",
            "AAPL",
            Decimal("500"),
            Decimal("110"),
            "2026-11-15"
        )

    user_portfolio = portfolio.get_portfolio("123456789")

    assert user_portfolio["holdings"]["AAPL"] == Decimal("2")