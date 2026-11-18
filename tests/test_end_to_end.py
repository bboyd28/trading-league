"""Register, trade, run the daily job, then read standings and stats.

Only Yahoo and the clock are faked. Everything else is the real code.
"""
from datetime import date, datetime
from decimal import Decimal

import pandas as pd

import core.analytics as analytics
import core.execution as execution
import core.leaderboard as leaderboard
import core.market_updates as market_updates
import core.portfolio as portfolio
import core.prices as prices
import core.providers as providers
from core.market_calendar import EASTERN

FRIDAY_EVENING = datetime(2026, 11, 13, 17, 0, tzinfo=EASTERN)
MONDAY_EVENING = datetime(2026, 11, 16, 17, 0, tzinfo=EASTERN)

CLOSES = {
    "AAPL": [("2026-11-12", 99.0), ("2026-11-13", 100.0), ("2026-11-16", 110.0)],
    "SPY": [("2026-11-12", 500.0), ("2026-11-13", 500.0), ("2026-11-16", 505.0)],
}


class FakeYahoo:
    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, **kwargs):
        rows = CLOSES[self.symbol]
        index = pd.to_datetime([d for d, _ in rows]).tz_localize("America/New_York")
        closes = [c for _, c in rows]
        return pd.DataFrame({"Close": closes, "Adj Close": closes}, index=index)


def test_a_full_league_day(setup_database, monkeypatch):
    monkeypatch.setattr(providers.yf, "Ticker", FakeYahoo)
    monkeypatch.setattr(prices, "last_completed_session", lambda now=None: date(2026, 11, 16))

    # Friday evening: join and get a day-zero snapshot.
    execution.register("1", "Alice", now=FRIDAY_EVENING)

    # Monday evening: buy at Monday's close, then the daily job runs.
    result = execution.place_order("1", "AAPL", "BUY", quantity="10", now=MONDAY_EVENING)
    assert result["price_date"] == "2026-11-16"
    assert result["price_per_share"] == Decimal("110")

    update = market_updates.run_daily_market_update("2026-11-16")
    assert update["snapshots_saved"] == ["1"]
    assert update["snapshot_failures"] == {}

    # Standings and stats come out of the saved snapshots.
    standings = leaderboard.get_standings("all")
    assert standings["as_of"] == "2026-11-16"
    assert standings["rows"][0]["username"] == "Alice"
    assert standings["rows"][0]["total_value"] == Decimal("99998.90")   # fee only

    summary = analytics.get_performance_summary("1")
    assert summary["observations"] == 1
    assert summary["benchmark_return_pct"] == Decimal("1")
    assert summary["total_return_pct"] < 0

    assert portfolio.find_cash_mismatches() == []
