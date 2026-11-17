import sqlite3

import pytest

import core.database as database


def test_foreign_keys_are_enforced(setup_database):
    with pytest.raises(sqlite3.IntegrityError):
        with database.get_connection(write=True) as connection:
            connection.execute("""
                INSERT INTO trades (
                    discord_id, symbol, side, quantity, price_per_share,
                    gross_amount_cents, fee_cents, price_date
                )
                VALUES ('nobody', 'AAPL', 'BUY', '1', '100', 10000, 10, '2026-11-13')
            """)


def test_failed_transaction_rolls_back(setup_database):
    with pytest.raises(RuntimeError):
        with database.get_connection(write=True) as connection:
            connection.execute("UPDATE league_settings SET fee_rate_bps = 999")
            raise RuntimeError("boom")

    with database.get_connection() as connection:
        assert database.get_league_settings(connection)["fee_rate_bps"] == 10


def test_initialize_is_safe_to_run_twice(setup_database):
    database.initialize_database()

    with database.get_connection() as connection:
        count = connection.execute("SELECT COUNT(*) FROM league_settings").fetchone()[0]

    assert count == 1


def test_old_database_is_migrated(tmp_path, monkeypatch):
    """A database made before per-user starting balances gets the new column."""
    legacy = tmp_path / "legacy.db"
    monkeypatch.setattr(database, "DATABASE_PATH", legacy)

    connection = sqlite3.connect(legacy)
    connection.executescript("""
        CREATE TABLE league_settings (
            setting_id INTEGER PRIMARY KEY CHECK (setting_id = 1),
            starting_balance_cents INTEGER NOT NULL,
            fee_rate_bps INTEGER NOT NULL,
            execution_model TEXT NOT NULL
        );
        INSERT INTO league_settings VALUES (1, 5000000, 10, 'daily_close');
        CREATE TABLE users (
            discord_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            cash_balance_cents INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT 'x',
            is_active INTEGER NOT NULL DEFAULT 1
        );
        INSERT INTO users (discord_id, username, cash_balance_cents)
        VALUES ('1', 'Old', 4000000);
    """)
    connection.commit()
    connection.close()

    database.initialize_database()

    with database.get_connection() as connection:
        user = connection.execute("SELECT * FROM users").fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert user["starting_balance_cents"] == 5_000_000
    assert user["cash_balance_cents"] == 4_000_000
    assert version == database.SCHEMA_VERSION
