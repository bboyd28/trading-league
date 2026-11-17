import pytest

import core.database as database
import core.prices as prices


@pytest.fixture
def setup_database(tmp_path, monkeypatch):
    """A fresh temporary database for each test."""
    test_database = tmp_path / "test_league.db"
    monkeypatch.setattr(database, "DATABASE_PATH", test_database)
    database.initialize_database()
    return test_database


@pytest.fixture(autouse=True)
def reset_refresh_cooldown(monkeypatch):
    monkeypatch.setattr(prices, "_last_refresh", {})
