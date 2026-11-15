import pytest

import core.database as database


@pytest.fixture
def setup_database(tmp_path, monkeypatch):
    """
    Create a fresh temporary database for each test.
    """

    test_database = tmp_path / "test_league.db"

    monkeypatch.setattr(
        database,
        "DATABASE_PATH",
        test_database
    )

    database.initialize_database()

    return test_database