"""Standings built from saved daily snapshots."""
from datetime import date, timedelta
from decimal import Decimal

from core.database import get_connection, get_league_settings


def get_latest_snapshot_date(on_or_before=None):
    """Most recent date that has snapshots, or None if there are none."""
    query = "SELECT MAX(snapshot_date) AS snapshot_date FROM portfolio_snapshots"
    params = ()

    if on_or_before is not None:
        query += " WHERE snapshot_date <= ?"
        params = (on_or_before,)

    with get_connection() as connection:
        return connection.execute(query, params).fetchone()["snapshot_date"]


def _rank(entries):
    """Sort by return (best first) and give tied players the same rank."""
    entries.sort(key=lambda e: (-e["return_percentage"], e["username"]))

    previous = None
    rank = 0

    for position, entry in enumerate(entries, start=1):
        if entry["return_percentage"] != previous:
            rank = position
        previous = entry["return_percentage"]
        entry["rank"] = rank

    return entries


def get_leaderboard(snapshot_date):
    """Active players ranked by return since they joined, as of one date."""
    with get_connection() as connection:
        default_start = get_league_settings(connection)["starting_balance_cents"]

        rows = connection.execute("""
            SELECT users.discord_id, users.username, users.starting_balance_cents,
                   s.cash_balance_cents, s.total_value_cents
            FROM portfolio_snapshots AS s
            JOIN users ON s.discord_id = users.discord_id
            WHERE s.snapshot_date = ? AND users.is_active = 1
        """, (snapshot_date,)).fetchall()

    entries = []

    for row in rows:
        start = Decimal(row["starting_balance_cents"] or default_start) / 100
        total = Decimal(row["total_value_cents"]) / 100

        entries.append({
            "discord_id": row["discord_id"],
            "username": row["username"],
            "total_value": total,
            "cash_balance": Decimal(row["cash_balance_cents"]) / 100,
            "return_percentage": (total - start) / start * 100,
        })

    return _rank(entries)


def get_period_leaderboard(start_date, end_date):
    """Players ranked by return between two dates (for weekly or monthly boards).

    A player's baseline is their last snapshot on or before start_date, or
    their first snapshot if they joined later.
    """
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT users.discord_id, users.username,
                   s.snapshot_date, s.total_value_cents
            FROM portfolio_snapshots AS s
            JOIN users ON s.discord_id = users.discord_id
            WHERE s.snapshot_date <= ? AND users.is_active = 1
            ORDER BY s.snapshot_date
        """, (end_date,)).fetchall()

    by_user = {}

    for row in rows:
        by_user.setdefault(row["discord_id"], {"name": row["username"], "rows": []})
        by_user[row["discord_id"]]["rows"].append(row)

    entries = []

    for discord_id, data in by_user.items():
        history = data["rows"]
        before = [r for r in history if r["snapshot_date"] <= start_date]
        baseline = before[-1] if before else history[0]
        latest = history[-1]
        start = Decimal(baseline["total_value_cents"]) / 100
        total = Decimal(latest["total_value_cents"]) / 100

        entries.append({
            "discord_id": discord_id,
            "username": data["name"],
            "total_value": total,
            "return_percentage": (total - start) / start * 100,
        })

    return _rank(entries)


PERIOD_DAYS = {"week": 7, "month": 30}


def get_standings(period="all"):
    """Standings as of the latest snapshot. period is 'all', 'week', or 'month'.

    Returns None when no snapshots exist yet.
    """
    if period != "all" and period not in PERIOD_DAYS:
        raise ValueError("Period must be all, week, or month.")

    latest = get_latest_snapshot_date()

    if latest is None:
        return None

    if period == "all":
        rows = get_leaderboard(latest)
    else:
        start = date.fromisoformat(latest) - timedelta(days=PERIOD_DAYS[period])
        rows = get_period_leaderboard(start.isoformat(), latest)

    return {"as_of": latest, "period": period, "rows": rows}
