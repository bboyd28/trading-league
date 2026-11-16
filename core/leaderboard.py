from decimal import Decimal

from core.database import get_connection

def get_leaderboard(snapshot_date: str):
    """
    Generate a leaderboard for a specific historical date.

    Ranks active participants by total portfolio value.
    """

    with get_connection() as connection:

        # Retrieve the league's starting balance.
        settings = connection.execute("""
            SELECT starting_balance_cents
            FROM league_settings
            WHERE setting_id = 1
        """).fetchone()

        if settings is None:
            raise RuntimeError("League settings have not been initialized.")

        starting_balance = Decimal(
            settings["starting_balance_cents"]
        ) / 100

        # Retrieve snapshots for all active participants.
        snapshots = connection.execute("""
            SELECT
                users.discord_id,
                users.username,
                portfolio_snapshots.cash_balance_cents,
                portfolio_snapshots.total_value_cents
            FROM portfolio_snapshots
            JOIN users
                ON portfolio_snapshots.discord_id = users.discord_id
            WHERE portfolio_snapshots.snapshot_date = ?
            AND users.is_active = 1
            ORDER BY
                portfolio_snapshots.total_value_cents DESC,
                users.username ASC
        """, (snapshot_date,)).fetchall()

    leaderboard = []

    # Calculate returns and assign rankings.
    previous_value = None
    current_rank = 0

    for position, snapshot in enumerate(snapshots, start=1):

        total_value = Decimal(
            snapshot["total_value_cents"]
        ) / 100

        if total_value != previous_value:
            current_rank = position

        previous_value = total_value

        total_value = Decimal(
            snapshot["total_value_cents"]
        ) / 100

        cash_balance = Decimal(
            snapshot["cash_balance_cents"]
        ) / 100

        return_percentage = (
            (total_value - starting_balance)
            / starting_balance
        ) * 100

        leaderboard.append({
            "rank": current_rank,
            "discord_id": snapshot["discord_id"],
            "username": snapshot["username"],
            "total_value": total_value,
            "cash_balance": cash_balance,
            "return_percentage": return_percentage
        })

    return leaderboard