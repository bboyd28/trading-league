from core.portfolio import (
 get_active_symbols,
 get_active_users,
 save_portfolio_snapshot
)
from core.prices import update_stock_prices


def update_league_prices():
    """
    Update daily price history for every stock
    currently held by an active league participant.

    Returns a report of successful updates and failures.
    """

    symbols = get_active_symbols()

    results = {
        "updated": {},
        "failed": {}
    }

    for symbol in symbols:

        try:
            count = update_stock_prices(symbol)

            results["updated"][symbol] = count

        except Exception as error:
            results["failed"][symbol] = str(error)

    return results

def run_daily_market_update(snapshot_date: str):
    """
    Run the complete daily market update process.

    Updates stock prices first, then saves portfolio
    snapshots for every active participant.
    """

    # First, update all stock prices.
    price_results = update_league_prices()

    # Do not save snapshots if any price update failed.
    if price_results["failed"]:
        return {
            "price_updates": price_results,
            "snapshots_saved": [],
            "snapshot_failures": {},
            "skipped": True
        }

    # Retrieve all active participants.
    users = get_active_users()

    results = {
        "price_updates": price_results,
        "snapshots_saved": [],
        "snapshot_failures": {},
        "skipped": False
    }

    # Save a snapshot for every participant.
    for discord_id in users:

        try:
            save_portfolio_snapshot(discord_id, snapshot_date)

            results["snapshots_saved"].append(discord_id)

        except Exception as error:
            results["snapshot_failures"][discord_id] = str(error)

    return results