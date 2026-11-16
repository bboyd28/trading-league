import pytest
from decimal import Decimal

import core.portfolio as portfolio
import core.leaderboard as leaderboard
import core.database as database


def test_leaderboard_ranking(setup_database):
    """
    Verify that participants are ranked by total portfolio value.
    """

    portfolio.register_user("101", "Alice")
    portfolio.register_user("102", "Bob")
    portfolio.register_user("103", "Charlie")

    with database.get_connection() as connection:

        snapshots = [
            ("101", "2026-11-14", 5000000, 5500000, 10500000),
            ("102", "2026-11-14", 5000000, 6000000, 11000000),
            ("103", "2026-11-14", 5000000, 4500000, 9500000)
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

    result = leaderboard.get_leaderboard("2026-11-14")

    assert result[0]["username"] == "Bob"
    assert result[1]["username"] == "Alice"
    assert result[2]["username"] == "Charlie"

    assert result[0]["rank"] == 1
    assert result[1]["rank"] == 2
    assert result[2]["rank"] == 3

def test_leaderboard_ties(setup_database):

    portfolio.register_user("101", "Alice")
    portfolio.register_user("102", "Bob")
    portfolio.register_user("103", "Charlie")

    with database.get_connection() as connection:

        snapshots = [
            ("101", "2026-11-14", 5000000, 6000000, 11000000),
            ("102", "2026-11-14", 5000000, 6000000, 11000000),
            ("103", "2026-11-14", 5000000, 5500000, 10500000)
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

    result = leaderboard.get_leaderboard("2026-11-14")

    assert result[0]["rank"] == 1
    assert result[1]["rank"] == 1
    assert result[2]["rank"] == 3