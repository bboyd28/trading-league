import sqlite3
from pathlib import Path
from contextlib import contextmanager

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATABASE_PATH = PROJECT_ROOT / "data" / "league.db"

@contextmanager
def get_connection():
    """
    Create and return a connection to the league database
    """
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row

    try:
        yield connection
        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()
def create_league_settings_table(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS league_settings (
            setting_id INTEGER PRIMARY KEY CHECK (setting_id = 1),
            starting_balance_cents INTEGER NOT NULL,
            fee_rate_bps INTEGER NOT NULL,
            execution_model TEXT NOT NULL
        )
    """)

def create_users_table(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            discord_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            cash_balance_cents INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),
            is_active INTEGER NOT NULL DEFAULT 1
                CHECK (is_active IN (0, 1))
        )
    """)

def create_trades_table(connection):
    connection.execute("""
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
            executed_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),

            FOREIGN KEY (discord_id)
                REFERENCES users(discord_id)
        )
    """)

def create_price_history_table(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            symbol TEXT NOT NULL,
            price_date TEXT NOT NULL,
            close_price TEXT NOT NULL,
            adjusted_close TEXT,
            source TEXT NOT NULL DEFAULT 'yfinance',
            fetched_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),

            PRIMARY KEY (symbol, price_date)
        )
    """)

def create_portfolio_snapshots_table(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            discord_id TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            cash_balance_cents INTEGER NOT NULL,
            holdings_value_cents INTEGER NOT NULL,
            total_value_cents INTEGER NOT NULL,

            PRIMARY KEY (discord_id, snapshot_date),

            FOREIGN KEY (discord_id)
                REFERENCES users(discord_id)
        )
    """)

def initialize_database():
    with get_connection() as connection:
        create_league_settings_table(connection)
        create_users_table(connection)
        create_trades_table(connection)
        create_price_history_table(connection)
        create_portfolio_snapshots_table(connection)

        connection.execute("""
            INSERT OR IGNORE INTO league_settings (
                setting_id,
                starting_balance_cents,
                fee_rate_bps,
                execution_model
            )
            VALUES (1, 10000000, 10, 'daily_close')
        """)

    print("League database initialized successfully.")


if __name__ == "__main__":
    initialize_database()