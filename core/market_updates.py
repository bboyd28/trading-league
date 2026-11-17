"""Daily job: download prices, then save every player's snapshot."""
import logging
from datetime import date, timedelta

from core.leaderboard import get_latest_snapshot_date
from core.market_calendar import (
    is_trading_day,
    last_completed_session,
    trading_days_between,
)
from core.portfolio import get_active_symbols, get_active_users, save_portfolio_snapshot
from core.prices import update_stock_prices

logger = logging.getLogger(__name__)

BENCHMARK = "SPY"


def update_league_prices(period="1mo"):
    """Download prices for every held stock plus the benchmark."""
    symbols = sorted(set(get_active_symbols()) | {BENCHMARK})
    results = {"updated": {}, "failed": {}}

    for symbol in symbols:
        try:
            results["updated"][symbol] = update_stock_prices(symbol, period=period)
        except Exception as error:
            logger.warning("Price update failed for %s: %s", symbol, error)
            results["failed"][symbol] = str(error)

    return results


def _save_snapshots(snapshot_date):
    """Snapshot every active player. A player is skipped if any price is missing."""
    saved = []
    failures = {}

    for discord_id in get_active_users():
        try:
            save_portfolio_snapshot(discord_id, snapshot_date, require_exact_prices=True)
            saved.append(discord_id)
        except Exception as error:
            logger.warning("Snapshot failed for %s: %s", discord_id, error)
            failures[discord_id] = str(error)

    return saved, failures


def run_daily_market_update(snapshot_date=None, now=None):
    """Update prices, then save snapshots for one trading day.

    Defaults to the last completed session. A failed benchmark download does
    not block snapshots; a failed price only affects players who hold it.
    """
    snapshot_date = snapshot_date or last_completed_session(now).isoformat()

    if not is_trading_day(date.fromisoformat(snapshot_date)):
        return {
            "snapshot_date": snapshot_date,
            "price_updates": {"updated": {}, "failed": {}},
            "snapshots_saved": [],
            "snapshot_failures": {},
            "skipped": True,
        }

    price_updates = update_league_prices()
    saved, failures = _save_snapshots(snapshot_date)

    return {
        "snapshot_date": snapshot_date,
        "price_updates": price_updates,
        "snapshots_saved": saved,
        "snapshot_failures": failures,
        "skipped": False,
    }


def backfill_snapshots(start_date, end_date):
    """Save snapshots for every trading day in a range (after downtime)."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    price_updates = update_league_prices(period="3mo")
    days = {}

    for day in trading_days_between(start, end):
        saved, failures = _save_snapshots(day.isoformat())
        days[day.isoformat()] = {"saved": saved, "failures": failures}

    return {"price_updates": price_updates, "days": days}


def catch_up_snapshots(now=None):
    """If the bot missed days, fill in snapshots up to the last session."""
    latest = get_latest_snapshot_date()
    last_session = last_completed_session(now)

    if latest is None or date.fromisoformat(latest) >= last_session:
        return None

    start = date.fromisoformat(latest) + timedelta(days=1)
    return backfill_snapshots(start.isoformat(), last_session.isoformat())
