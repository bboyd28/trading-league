import pytest
from decimal import Decimal

import core.portfolio as portfolio
import core.analytics as analytics
import core.database as database

def test_daily_returns(setup_database):

    portfolio.register_user("101", "Alice")

    with database.get_connection() as connection:

        snapshots = [
            ("101", "2026-11-12", 5000000, 5000000, 10000000),
            ("101", "2026-11-13", 5000000, 5200000, 10200000),
            ("101", "2026-11-14", 5000000, 5100000, 10100000)
        ]

        connection.executemany("""
            INSERT INTO portfolio_snapshots (
                discord_id,
                snapshot_date,
                cash_balance_cents,
                holdings_value_cents,
                total_value_cents
            )
            VALUES (?, ?, ?, ?, ?)
        """, snapshots)

    result = analytics.get_daily_returns("101")

    assert len(result) == 2

    assert result[0]["date"] == "2026-11-13"
    assert result[0]["daily_return"] == Decimal("2")

    assert result[1]["date"] == "2026-11-14"
    assert result[1]["daily_return"] == (
        Decimal("-100") / Decimal("10200")
    ) * 100

def test_daily_returns_single_snapshot(setup_database):

    portfolio.register_user("101", "Alice")

    with database.get_connection() as connection:

        connection.execute("""
            INSERT INTO portfolio_snapshots (
                discord_id,
                snapshot_date,
                cash_balance_cents,
                holdings_value_cents,
                total_value_cents
            )
            VALUES (?, ?, ?, ?, ?)
        """, ("101", "2026-11-14", 10000000, 0, 10000000))

    result = analytics.get_daily_returns("101")

    assert result == []

def test_daily_returns_no_snapshots(setup_database):

    portfolio.register_user("101", "Alice")

    result = analytics.get_daily_returns("101")

    assert result == []


def test_cumulative_returns(setup_database):

    portfolio.register_user("101", "Alice")

    with database.get_connection() as connection:

        snapshots = [
            ("101", "2026-11-12", 5000000, 5000000, 10000000),
            ("101", "2026-11-13", 5000000, 5200000, 10200000),
            ("101", "2026-11-14", 5000000, 5100000, 10100000)
        ]

        connection.executemany("""
            INSERT INTO portfolio_snapshots (
                discord_id,
                snapshot_date,
                cash_balance_cents,
                holdings_value_cents,
                total_value_cents
            )
            VALUES (?, ?, ?, ?, ?)
        """, snapshots)

    result = analytics.get_cumulative_returns("101")

    assert len(result) == 2

    assert result[0]["date"] == "2026-11-13"
    assert result[0]["cumulative_return"] == Decimal("2")

    assert result[1]["date"] == "2026-11-14"
    assert result[1]["cumulative_return"] == (
        Decimal("1.01") - Decimal("1")
    ) * 100


def test_benchmark_daily_returns(setup_database):

    with database.get_connection() as connection:

        prices = [
            ("SPY", "2026-11-12", "100", "100", "yfinance"),
            ("SPY", "2026-11-13", "102", "102", "yfinance"),
            ("SPY", "2026-11-14", "101", "101", "yfinance")
        ]

        connection.executemany("""
            INSERT INTO price_history (
                symbol,
                price_date,
                close_price,
                adjusted_close,
                source
            )
            VALUES (?, ?, ?, ?, ?)
        """, prices)

    result = analytics.get_benchmark_daily_returns(
        "2026-11-12",
        "2026-11-14"
    )

    assert len(result) == 2

    assert result[0]["date"] == "2026-11-13"
    assert result[0]["daily_return"] == Decimal("2")

    assert result[1]["date"] == "2026-11-14"

    expected_return = (
        (Decimal("101") - Decimal("102"))
        / Decimal("102")
    ) * 100

    assert result[1]["daily_return"] == expected_return

def test_benchmark_cumulative_returns(setup_database):

    with database.get_connection() as connection:

        prices = [
            ("SPY", "2026-11-12", "100", "100", "yfinance"),
            ("SPY", "2026-11-13", "102", "102", "yfinance"),
            ("SPY", "2026-11-14", "101", "101", "yfinance")
        ]

        connection.executemany("""
            INSERT INTO price_history (
                symbol,
                price_date,
                close_price,
                adjusted_close,
                source
            )
            VALUES (?, ?, ?, ?, ?)
        """, prices)

    result = analytics.get_benchmark_cumulative_returns(
        "2026-11-12",
        "2026-11-14"
    )

    assert len(result) == 2

    assert result[0]["cumulative_return"] == Decimal("2")

    expected_return = (
        (Decimal("101") / Decimal("100")) - Decimal("1")
    ) * Decimal("100")

    assert result[1]["cumulative_return"] == expected_return


def test_compare_portfolio_to_benchmark(setup_database):

    portfolio.register_user("101", "Alice")

    with database.get_connection() as connection:

        snapshots = [
            ("101", "2026-11-12", 5000000, 5000000, 10000000),
            ("101", "2026-11-13", 5000000, 5200000, 10200000),
            ("101", "2026-11-14", 5000000, 5100000, 10100000)
        ]

        connection.executemany("""
            INSERT INTO portfolio_snapshots (
                discord_id,
                snapshot_date,
                cash_balance_cents,
                holdings_value_cents,
                total_value_cents
            )
            VALUES (?, ?, ?, ?, ?)
        """, snapshots)

        prices = [
            ("SPY", "2026-11-12", "100", "100", "yfinance"),
            ("SPY", "2026-11-13", "101", "101", "yfinance"),
            ("SPY", "2026-11-14", "103", "103", "yfinance")
        ]

        connection.executemany("""
            INSERT INTO price_history (
                symbol,
                price_date,
                close_price,
                adjusted_close,
                source
            )
            VALUES (?, ?, ?, ?, ?)
        """, prices)

    result = analytics.compare_portfolio_to_benchmark("101")

    assert len(result) == 2

    assert result[0]["date"] == "2026-11-13"
    assert result[0]["portfolio_return"] == Decimal("2")
    assert result[0]["benchmark_return"] == Decimal("1")
    assert result[0]["excess_return"] == Decimal("1")

    assert result[1]["date"] == "2026-11-14"
    assert result[1]["portfolio_return"] == Decimal("1")
    assert result[1]["benchmark_return"] == Decimal("3")
    assert result[1]["excess_return"] == Decimal("-2")

def test_portfolio_volatility(setup_database):

    portfolio.register_user("101", "Alice")

    with database.get_connection() as connection:

        snapshots = [
            ("101", "2026-11-10", 5000000, 5000000, 10000000),
            ("101", "2026-11-11", 5000000, 5100000, 10100000),
            ("101", "2026-11-12", 5000000, 5000000, 10000000),
            ("101", "2026-11-13", 5000000, 5200000, 10200000)
        ]

        connection.executemany("""
            INSERT INTO portfolio_snapshots (
                discord_id,
                snapshot_date,
                cash_balance_cents,
                holdings_value_cents,
                total_value_cents
            )
            VALUES (?, ?, ?, ?, ?)
        """, snapshots)

    result = analytics.get_portfolio_volatility("101")

    assert result is not None
    assert result > 0

def test_sharpe_ratio(setup_database):

    portfolio.register_user("101", "Alice")

    with database.get_connection() as connection:

        snapshots = [
            ("101", "2026-11-10", 5000000, 5000000, 10000000),
            ("101", "2026-11-11", 5000000, 5100000, 10100000),
            ("101", "2026-11-12", 5000000, 5000000, 10000000),
            ("101", "2026-11-13", 5000000, 5200000, 10200000)
        ]

        connection.executemany("""
            INSERT INTO portfolio_snapshots (
                discord_id,
                snapshot_date,
                cash_balance_cents,
                holdings_value_cents,
                total_value_cents
            )
            VALUES (?, ?, ?, ?, ?)
        """, snapshots)

    result = analytics.get_sharpe_ratio("101")

    assert result is not None
    assert result > 0


def test_max_drawdown(setup_database):

    portfolio.register_user("101", "Alice")

    with database.get_connection() as connection:

        snapshots = [
            ("101", "2026-11-10", 5000000, 5000000, 10000000),
            ("101", "2026-11-11", 5000000, 5500000, 10500000),
            ("101", "2026-11-12", 5000000, 5000000, 9500000),
            ("101", "2026-11-13", 5000000, 4500000, 9000000),
            ("101", "2026-11-16", 5000000, 5200000, 10200000)
        ]

        connection.executemany("""
            INSERT INTO portfolio_snapshots (
                discord_id,
                snapshot_date,
                cash_balance_cents,
                holdings_value_cents,
                total_value_cents
            )
            VALUES (?, ?, ?, ?, ?)
        """, snapshots)

    result = analytics.get_max_drawdown("101")

    assert result == Decimal("-14.28571428571428571428571429")


def test_portfolio_beta(setup_database):

    portfolio.register_user("101", "Alice")

    with database.get_connection() as connection:

        snapshots = [
            ("101", "2026-11-10", 5000000, 5000000, 10000000),
            ("101", "2026-11-11", 5000000, 5100000, 10100000),
            ("101", "2026-11-12", 5000000, 4900000, 9900000),
            ("101", "2026-11-13", 5000000, 5200000, 10200000),
            ("101", "2026-11-16", 5000000, 5000000, 10000000)
        ]

        connection.executemany("""
            INSERT INTO portfolio_snapshots (
                discord_id,
                snapshot_date,
                cash_balance_cents,
                holdings_value_cents,
                total_value_cents
            )
            VALUES (?, ?, ?, ?, ?)
        """, snapshots)

        prices = [
            ("SPY", "2026-11-10", "100", "100", "test"),
            ("SPY", "2026-11-11", "101", "101", "test"),
            ("SPY", "2026-11-12", "100", "100", "test"),
            ("SPY", "2026-11-13", "102", "102", "test"),
            ("SPY", "2026-11-16", "101", "101", "test")
        ]

        connection.executemany("""
            INSERT INTO price_history (
                symbol,
                price_date,
                close_price,
                adjusted_close,
                source
            )
            VALUES (?, ?, ?, ?, ?)
        """, prices)

    result = analytics.get_portfolio_beta("101")

    assert result is not None
    assert result > 0