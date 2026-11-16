import core.market_updates as market_updates
import core.portfolio as portfolio
import core.database as database

def test_update_league_prices(setup_database, monkeypatch):
    # Pretend these are the stocks currently held.
    monkeypatch.setattr(
        market_updates,
        "get_active_symbols",
        lambda: ["AAPL", "MSFT"]
    )

    # Pretend both updates succeed.
    monkeypatch.setattr(
        market_updates,
        "update_stock_prices",
        lambda symbol: 23
    )

    results = market_updates.update_league_prices()

    assert results == {
        "updated": {
            "AAPL": 23,
            "MSFT": 23,
            "SPY": 23
        },
        "failed": {}
    }


def test_update_league_prices_handles_failure(setup_database, monkeypatch):
    monkeypatch.setattr(
        market_updates,
        "get_active_symbols",
        lambda: ["AAPL", "INVALID"]
    )

    def mock_update(symbol):
        if symbol == "INVALID":
            raise ValueError("No price data found.")

        return 23

    monkeypatch.setattr(
        market_updates,
        "update_stock_prices",
        mock_update
    )

    results = market_updates.update_league_prices()

    assert results["updated"] == {"AAPL": 23,
                                  "SPY": 23}

    assert results["failed"] == {
        "INVALID": "No price data found."
    }

def test_run_daily_market_update_success(setup_database, monkeypatch):
    monkeypatch.setattr(
        market_updates,
        "update_league_prices",
        lambda: {"updated": {"AAPL": 23}, "failed": {}}
    )

    monkeypatch.setattr(
        market_updates,
        "get_active_users",
        lambda: ["111", "222"]
    )

    saved_users = []

    def mock_save(discord_id, snapshot_date):
        saved_users.append(discord_id)

    monkeypatch.setattr(
        market_updates,
        "save_portfolio_snapshot",
        mock_save
    )

    results = market_updates.run_daily_market_update("2026-11-14")

    assert results["snapshots_saved"] == ["111", "222"]
    assert results["snapshot_failures"] == {}
    assert results["skipped"] is False
    assert saved_users == ["111", "222"]


def test_run_daily_market_update_skips_on_price_failure(
    setup_database, monkeypatch
):
    monkeypatch.setattr(
        market_updates,
        "update_league_prices",
        lambda: {
            "updated": {"AAPL": 23},
            "failed": {"MSFT": "Price retrieval failed."}
        }
    )

    def unexpected_snapshot(*args):
        raise AssertionError("Snapshots should have been skipped.")

    monkeypatch.setattr(
        market_updates,
        "save_portfolio_snapshot",
        unexpected_snapshot
    )

    results = market_updates.run_daily_market_update("2026-11-14")

    assert results["skipped"] is True
    assert results["snapshots_saved"] == []
    assert results["snapshot_failures"] == {}


def test_run_daily_market_update_handles_snapshot_failure(
    setup_database, monkeypatch
):
    monkeypatch.setattr(
        market_updates,
        "update_league_prices",
        lambda: {"updated": {"AAPL": 23}, "failed": {}}
    )

    monkeypatch.setattr(
        market_updates,
        "get_active_users",
        lambda: ["111", "222", "333"]
    )

    def mock_save(discord_id, snapshot_date):
        if discord_id == "222":
            raise ValueError("User portfolio could not be valued.")

    monkeypatch.setattr(
        market_updates,
        "save_portfolio_snapshot",
        mock_save
    )

    results = market_updates.run_daily_market_update("2026-11-14")

    assert results["snapshots_saved"] == ["111", "333"]

    assert results["snapshot_failures"] == {
        "222": "User portfolio could not be valued."
    }

    assert results["skipped"] is False

def test_spy_updates_without_participants(setup_database, monkeypatch):

    updated_symbols = []

    def fake_update_stock_prices(symbol):
        updated_symbols.append(symbol)
        return 20

    monkeypatch.setattr(
        market_updates,
        "get_active_symbols",
        lambda: []
    )

    monkeypatch.setattr(
        market_updates,
        "update_stock_prices",
        fake_update_stock_prices
    )

    result = market_updates.update_league_prices()

    assert updated_symbols == ["SPY"]
    assert result["updated"] == {"SPY": 20}
    assert result["failed"] == {}