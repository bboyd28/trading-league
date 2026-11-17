from decimal import Decimal

import pytest

import core.database as database
import core.leaderboard as leaderboard
import core.portfolio as portfolio


def add_snapshots(rows):
    """rows: (discord_id, date, total_value_cents)"""
    with database.get_connection(write=True) as connection:
        connection.executemany("""
            INSERT INTO portfolio_snapshots (
                discord_id, snapshot_date, cash_balance_cents,
                holdings_value_cents, total_value_cents
            )
            VALUES (?, ?, 5000000, ? - 5000000, ?)
        """, [(i, d, v, v) for i, d, v in rows])


def test_ranking_by_return(setup_database):
    for discord_id, name in [("101", "Alice"), ("102", "Bob"), ("103", "Charlie")]:
        portfolio.register_user(discord_id, name)

    add_snapshots([
        ("101", "2026-11-13", 10_500_000),
        ("102", "2026-11-13", 11_000_000),
        ("103", "2026-11-13", 9_500_000),
    ])

    result = leaderboard.get_leaderboard("2026-11-13")

    assert [p["username"] for p in result] == ["Bob", "Alice", "Charlie"]
    assert [p["rank"] for p in result] == [1, 2, 3]
    assert result[0]["total_value"] == Decimal("110000")
    assert result[0]["return_percentage"] == Decimal("10")
    assert result[2]["return_percentage"] == Decimal("-5")


def test_ties_share_a_rank(setup_database):
    for discord_id, name in [("101", "Alice"), ("102", "Bob"), ("103", "Charlie")]:
        portfolio.register_user(discord_id, name)

    add_snapshots([
        ("101", "2026-11-13", 11_000_000),
        ("102", "2026-11-13", 11_000_000),
        ("103", "2026-11-13", 10_500_000),
    ])

    result = leaderboard.get_leaderboard("2026-11-13")

    assert [p["rank"] for p in result] == [1, 1, 3]
    assert [p["username"] for p in result[:2]] == ["Alice", "Bob"]


def test_inactive_players_are_left_out(setup_database):
    portfolio.register_user("101", "Alice")
    portfolio.register_user("102", "Bob")
    add_snapshots([("101", "2026-11-13", 10_000_000), ("102", "2026-11-13", 12_000_000)])

    with database.get_connection(write=True) as connection:
        connection.execute("UPDATE users SET is_active = 0 WHERE discord_id = '102'")

    assert [p["username"] for p in leaderboard.get_leaderboard("2026-11-13")] == ["Alice"]


def test_return_uses_each_players_own_starting_balance(setup_database):
    portfolio.register_user("101", "Alice")

    with database.get_connection(write=True) as connection:
        connection.execute("UPDATE users SET starting_balance_cents = 5000000")

    add_snapshots([("101", "2026-11-13", 5_500_000)])

    assert leaderboard.get_leaderboard("2026-11-13")[0]["return_percentage"] == Decimal("10")


def test_empty_date_returns_nothing(setup_database):
    assert leaderboard.get_leaderboard("2026-11-13") == []


def test_latest_snapshot_date(setup_database):
    portfolio.register_user("101", "Alice")
    assert leaderboard.get_latest_snapshot_date() is None

    add_snapshots([("101", "2026-11-12", 10_000_000), ("101", "2026-11-16", 10_000_000)])

    assert leaderboard.get_latest_snapshot_date() == "2026-11-16"
    assert leaderboard.get_latest_snapshot_date("2026-11-14") == "2026-11-12"


def test_period_leaderboard_measures_the_period_only(setup_database):
    portfolio.register_user("101", "Alice")
    portfolio.register_user("102", "Bob")
    portfolio.register_user("103", "Newbie")

    add_snapshots([
        # Alice was up 50% before the week, then flat. Bob gained 10% this week.
        ("101", "2026-11-06", 15_000_000), ("101", "2026-11-13", 15_000_000),
        ("102", "2026-11-06", 10_000_000), ("102", "2026-11-13", 11_000_000),
        # Newbie joined mid-week and gained 5% from their first snapshot.
        ("103", "2026-11-10", 10_000_000), ("103", "2026-11-13", 10_500_000),
    ])

    result = leaderboard.get_period_leaderboard("2026-11-06", "2026-11-13")

    assert [p["username"] for p in result] == ["Bob", "Newbie", "Alice"]
    assert result[0]["return_percentage"] == Decimal("10")
    assert result[1]["return_percentage"] == Decimal("5")
    assert result[2]["return_percentage"] == Decimal("0")


def test_standings_for_each_period(setup_database):
    portfolio.register_user("101", "Alice")
    add_snapshots([("101", "2026-11-06", 10_000_000), ("101", "2026-11-13", 10_400_000)])

    everything = leaderboard.get_standings("all")
    week = leaderboard.get_standings("week")

    assert everything["as_of"] == "2026-11-13"
    assert everything["rows"][0]["return_percentage"] == Decimal("4")
    assert week["rows"][0]["return_percentage"] == Decimal("4")


def test_standings_without_data_or_with_a_bad_period(setup_database):
    assert leaderboard.get_standings() is None

    with pytest.raises(ValueError, match="all, week, or month"):
        leaderboard.get_standings("decade")
