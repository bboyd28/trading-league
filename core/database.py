"""SQLite connection handling and schema setup."""
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "data" / "league.db"
SCHEMA_VERSION = 2


@contextmanager
def get_connection(write=False):
    """Open a connection and run everything inside one transaction.

    Use write=True for any code that reads and then writes (balance checks,
    trades). It takes the write lock up front, so two writers can't both
    pass the same check.
    """
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")

    try:
        connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield connection
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def get_league_settings(connection):
    settings = connection.execute(
        "SELECT * FROM league_settings WHERE setting_id = 1"
    ).fetchone()

    if settings is None:
        raise RuntimeError("League settings have not been initialized.")

    return settings


TABLES = [
    """
    CREATE TABLE IF NOT EXISTS league_settings (
        setting_id INTEGER PRIMARY KEY CHECK (setting_id = 1),
        starting_balance_cents INTEGER NOT NULL,
        fee_rate_bps INTEGER NOT NULL,
        -- 'daily_close': fills at the last close, only while the market is closed
        -- 'any_time': fills at the last close at any hour (for testing)
        execution_model TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        discord_id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        cash_balance_cents INTEGER NOT NULL,
        starting_balance_cents INTEGER,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trades (
        trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
        quantity TEXT NOT NULL,
        price_per_share TEXT NOT NULL,
        gross_amount_cents INTEGER NOT NULL,
        fee_cents INTEGER NOT NULL,
        price_date TEXT NOT NULL,
        executed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        FOREIGN KEY (discord_id) REFERENCES users(discord_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS price_history (
        symbol TEXT NOT NULL,
        price_date TEXT NOT NULL,
        close_price TEXT NOT NULL,
        adjusted_close TEXT,
        source TEXT NOT NULL DEFAULT 'yfinance',
        fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        PRIMARY KEY (symbol, price_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
        discord_id TEXT NOT NULL,
        snapshot_date TEXT NOT NULL,
        cash_balance_cents INTEGER NOT NULL,
        holdings_value_cents INTEGER NOT NULL,
        total_value_cents INTEGER NOT NULL,
        PRIMARY KEY (discord_id, snapshot_date),
        FOREIGN KEY (discord_id) REFERENCES users(discord_id)
    )
    """,
    # Per-position rows. Needed later for attribution, risk, and sector reports.
    """
    CREATE TABLE IF NOT EXISTS position_snapshots (
        discord_id TEXT NOT NULL,
        snapshot_date TEXT NOT NULL,
        symbol TEXT NOT NULL,
        quantity TEXT NOT NULL,
        price TEXT NOT NULL,
        market_value_cents INTEGER NOT NULL,
        PRIMARY KEY (discord_id, snapshot_date, symbol),
        FOREIGN KEY (discord_id) REFERENCES users(discord_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trades_user_symbol ON trades (discord_id, symbol)",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_date ON portfolio_snapshots (snapshot_date)",
]


def _migrate(connection):
    """Bring a database created by an older version up to date."""
    version = connection.execute("PRAGMA user_version").fetchone()[0]

    if version < 2:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(users)")
        }
        if "starting_balance_cents" not in columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN starting_balance_cents INTEGER"
            )
        connection.execute("""
            UPDATE users
            SET starting_balance_cents = (
                SELECT starting_balance_cents FROM league_settings
                WHERE setting_id = 1
            )
            WHERE starting_balance_cents IS NULL
        """)

    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def initialize_database():
    with get_connection(write=True) as connection:
        for statement in TABLES:
            connection.execute(statement)

        connection.execute("""
            INSERT OR IGNORE INTO league_settings (
                setting_id, starting_balance_cents, fee_rate_bps, execution_model
            )
            VALUES (1, 10000000, 10, 'daily_close')
        """)

        _migrate(connection)

    logger.info("League database ready at %s", DATABASE_PATH)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    initialize_database()
