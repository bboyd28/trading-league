from datetime import datetime

import core.database as database
import core.market_updates as market_updates
from core.market_calendar import EASTERN

TRADING_DAY = "2026-11-13"   # Friday
SATURDAY = "2026-11-14"


def stub_prices(monkeypatch, held, failing=()):
    monkeypatch.setattr(market_updates, "get_active_symbols", lambda: held)

    def fake_update(symbol, period="1mo"):
        if symbol in failing:
            raise ValueError("No price data found.")
        return 23

    monkeypatch.setattr(market_updates, "update_stock_prices", fake_update)


def stub_snapshots(monkeypatch, users, failing=()):
    saved = []
    monkeypatch.setattr(market_updates, "get_active_users", lambda: users)

    def fake_save(discord_id, snapshot_date, require_exact_prices=False):
        assert require_exact_prices is True
        if discord_id in failing:
            raise ValueError("User portfolio could not be valued.")
        saved.append((discord_id, snapshot_date))

    monkeypatch.setattr(market_updates, "save_portfolio_snapshot", fake_save)
    return saved


def test_update_league_prices_always_includes_benchmark(monkeypatch):
    stub_prices(monkeypatch, ["AAPL", "MSFT"])

    results = market_updates.update_league_prices()

    assert results == {
        "updated": {"AAPL": 23, "MSFT": 23, "SPY": 23},
        "failed": {},
    }


def test_update_league_prices_reports_failures(monkeypatch):
    stub_prices(monkeypatch, ["AAPL", "INVALID"], failing={"INVALID"})

    results = market_updates.update_league_prices()

    assert results["updated"] == {"AAPL": 23, "SPY": 23}
    assert results["failed"] == {"INVALID": "No price data found."}


def test_spy_updates_without_participants(monkeypatch):
    stub_prices(monkeypatch, [])

    assert market_updates.update_league_prices()["updated"] == {"SPY": 23}


def test_daily_update_saves_snapshots(monkeypatch):
    stub_prices(monkeypatch, ["AAPL"])
    saved = stub_snapshots(monkeypatch, ["111", "222"])

    result = market_updates.run_daily_market_update(TRADING_DAY)

    assert result["snapshots_saved"] == ["111", "222"]
    assert result["snapshot_failures"] == {}
    assert result["skipped"] is False
    assert saved == [("111", TRADING_DAY), ("222", TRADING_DAY)]


def test_daily_update_skips_non_trading_days(monkeypatch):
    stub_prices(monkeypatch, ["AAPL"])
    saved = stub_snapshots(monkeypatch, ["111"])

    result = market_updates.run_daily_market_update(SATURDAY)

    assert result["skipped"] is True
    assert saved == []


def test_daily_update_defaults_to_last_completed_session(monkeypatch):
    stub_prices(monkeypatch, [])
    saved = stub_snapshots(monkeypatch, ["111"])
    saturday_noon = datetime(2026, 11, 14, 12, 0, tzinfo=EASTERN)

    market_updates.run_daily_market_update(now=saturday_noon)

    assert saved == [("111", TRADING_DAY)]


def test_one_bad_snapshot_does_not_stop_the_others(monkeypatch):
    stub_prices(monkeypatch, ["AAPL"])
    stub_snapshots(monkeypatch, ["111", "222", "333"], failing={"222"})

    result = market_updates.run_daily_market_update(TRADING_DAY)

    assert result["snapshots_saved"] == ["111", "333"]
    assert result["snapshot_failures"] == {"222": "User portfolio could not be valued."}


def test_failed_benchmark_does_not_block_snapshots(monkeypatch):
    stub_prices(monkeypatch, [], failing={"SPY"})
    stub_snapshots(monkeypatch, ["111"])

    result = market_updates.run_daily_market_update(TRADING_DAY)

    assert result["snapshots_saved"] == ["111"]
    assert "SPY" in result["price_updates"]["failed"]


def test_backfill_covers_each_trading_day(monkeypatch):
    stub_prices(monkeypatch, [])
    saved = stub_snapshots(monkeypatch, ["111"])

    result = market_updates.backfill_snapshots("2026-11-12", "2026-11-16")

    assert [day for _, day in saved] == ["2026-11-12", "2026-11-13", "2026-11-16"]
    assert list(result["days"]) == ["2026-11-12", "2026-11-13", "2026-11-16"]


def add_snapshot(date):
    with database.get_connection(write=True) as connection:
        connection.execute("""
            INSERT INTO users (discord_id, username, cash_balance_cents)
            VALUES ('111', 'Alice', 10000000)
        """)
        connection.execute("""
            INSERT INTO portfolio_snapshots VALUES ('111', ?, 10000000, 0, 10000000)
        """, (date,))


def test_catch_up_fills_missed_days(setup_database, monkeypatch):
    add_snapshot("2026-11-12")
    calls = []
    monkeypatch.setattr(
        market_updates, "backfill_snapshots",
        lambda start, end: calls.append((start, end)) or "filled",
    )

    now = datetime(2026, 11, 16, 17, 0, tzinfo=EASTERN)

    assert market_updates.catch_up_snapshots(now) == "filled"
    assert calls == [("2026-11-13", "2026-11-16")]


def test_catch_up_does_nothing_when_current(setup_database, monkeypatch):
    add_snapshot("2026-11-16")
    monkeypatch.setattr(market_updates, "backfill_snapshots", lambda *a: 1 / 0)

    now = datetime(2026, 11, 16, 17, 0, tzinfo=EASTERN)

    assert market_updates.catch_up_snapshots(now) is None


def test_catch_up_does_nothing_without_any_snapshots(setup_database):
    assert market_updates.catch_up_snapshots() is None
