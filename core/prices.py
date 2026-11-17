"""Daily price download (Yahoo Finance) and stored price lookups.

fetch_daily_prices is the only function that talks to Yahoo. To switch to
another data source later, replace that one function.
"""
import logging
import re
import time
from decimal import Decimal

import pandas as pd
import yfinance as yf

from core.database import get_connection
from core.market_calendar import last_completed_session

logger = logging.getLogger(__name__)

SYMBOL_PATTERN = re.compile(r"^[A-Z]{1,5}([.-][A-Z]{1,2})?$")
PRICE_PLACES = Decimal("0.0001")
REFRESH_COOLDOWN_SECONDS = 300

_last_refresh = {}


def normalize_symbol(symbol):
    cleaned = str(symbol).upper().strip()

    if not SYMBOL_PATTERN.match(cleaned):
        raise ValueError(f"'{symbol}' is not a valid stock symbol.")

    return cleaned


def fetch_daily_prices(symbol, period="1mo", now=None):
    """Download daily closes, leaving out any session that isn't final yet."""
    symbol = normalize_symbol(symbol)

    try:
        prices = yf.Ticker(symbol).history(
            period=period, interval="1d", auto_adjust=False, actions=False
        )
    except Exception as error:
        raise RuntimeError(f"Could not reach the price provider: {error}") from error

    if prices.empty:
        raise ValueError(f"No price data found for {symbol}.")

    if not {"Close", "Adj Close"}.issubset(prices.columns):
        raise RuntimeError("Expected price columns were not returned.")

    prices = prices[["Close", "Adj Close"]].dropna(subset=["Close"])

    # While the market is open Yahoo includes today's unfinished bar.
    cutoff = last_completed_session(now)
    prices = prices[[stamp.date() <= cutoff for stamp in prices.index]]

    if prices.empty:
        raise ValueError(f"No completed daily prices found for {symbol}.")

    return prices.copy()


def _to_price_text(value):
    return str(Decimal(str(value)).quantize(PRICE_PLACES))


def store_price_history(symbol, prices):
    symbol = normalize_symbol(symbol)

    rows = [
        (
            symbol,
            stamp.strftime("%Y-%m-%d"),
            _to_price_text(row["Close"]),
            None if pd.isna(row["Adj Close"]) else _to_price_text(row["Adj Close"]),
        )
        for stamp, row in prices.iterrows()
    ]

    with get_connection(write=True) as connection:
        connection.executemany("""
            INSERT INTO price_history (symbol, price_date, close_price, adjusted_close, source)
            VALUES (?, ?, ?, ?, 'yfinance')
            ON CONFLICT(symbol, price_date) DO UPDATE SET
                close_price = excluded.close_price,
                adjusted_close = excluded.adjusted_close,
                source = excluded.source,
                fetched_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """, rows)


def update_stock_prices(symbol, period="1mo"):
    """Download recent prices and store them. Returns the number of days."""
    symbol = normalize_symbol(symbol)
    prices = fetch_daily_prices(symbol, period)
    store_price_history(symbol, prices)
    return len(prices)


def get_prices_on_or_before(symbols, target_date):
    """Latest stored close on or before target_date, for several symbols.

    Returns {symbol: {"symbol", "price_date", "price"}}.
    """
    found = {}

    with get_connection() as connection:
        for symbol in symbols:
            symbol = normalize_symbol(symbol)
            row = connection.execute("""
                SELECT price_date, close_price
                FROM price_history
                WHERE symbol = ? AND price_date <= ?
                ORDER BY price_date DESC
                LIMIT 1
            """, (symbol, target_date)).fetchone()

            if row is None:
                raise ValueError(
                    f"No price history found for {symbol} on or before {target_date}."
                )

            found[symbol] = {
                "symbol": symbol,
                "price_date": row["price_date"],
                "price": Decimal(row["close_price"]),
            }

    return found


def get_price_on_or_before(symbol, target_date):
    symbol = normalize_symbol(symbol)
    return get_prices_on_or_before([symbol], target_date)[symbol]


def get_latest_prices(symbols):
    return get_prices_on_or_before(symbols, "9999-12-31")


def _refresh_symbol(symbol):
    """Download fresh prices, but not more than once per cooldown per symbol."""
    elapsed = time.monotonic() - _last_refresh.get(symbol, float("-inf"))

    if elapsed < REFRESH_COOLDOWN_SECONDS:
        return

    _last_refresh[symbol] = time.monotonic()
    update_stock_prices(symbol)


def get_execution_price(symbol, now=None):
    """Official close of the last completed session, downloading it if needed.

    Raises if that close isn't available yet, so nobody trades on a stale price.
    """
    symbol = normalize_symbol(symbol)
    session = last_completed_session(now).isoformat()

    try:
        latest = get_price_on_or_before(symbol, session)
    except ValueError:
        latest = None

    if latest is None or latest["price_date"] < session:
        _refresh_symbol(symbol)
        latest = get_price_on_or_before(symbol, session)

    if latest["price_date"] < session:
        raise ValueError(
            f"The {session} close for {symbol} isn't available yet "
            f"(latest is {latest['price_date']}). Try again in a few minutes."
        )

    return latest
