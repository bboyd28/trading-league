import pytest

import core.database as database
import core.prices as prices
import core.providers as providers


@pytest.fixture
def setup_database(tmp_path, monkeypatch):
    """A fresh temporary database for each test."""
    test_database = tmp_path / "test_league.db"
    monkeypatch.setattr(database, "DATABASE_PATH", test_database)
    database.initialize_database()
    return test_database


@pytest.fixture(autouse=True)
def clean_price_state(monkeypatch):
    """No leftover cooldowns, quotes, or provider settings between tests."""
    monkeypatch.setattr(prices, "_last_refresh", {})
    monkeypatch.setattr(prices, "_quote_cache", {})

    for name in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "PRICE_PROVIDER",
                 "ALPACA_BARS_FEED", "ALPACA_LIVE_FEED"):
        monkeypatch.delenv(name, raising=False)

    providers.reset_provider()
    yield
    providers.reset_provider()
