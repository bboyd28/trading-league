"""Stored daily closes, plus live quotes while the market is open.

All network calls go through the provider in core/providers.py.
"""
import logging
import re
import time
from decimal import Decimal

import pandas as pd

from core.database import get_connection
from core.market_calendar import last_completed_session, now_eastern
from core.providers import get_provider

logger = logging.getLogger(__name__)

SYMBOL_PATTERN = re.compile(r"^[A-Z]{1,5}([.-][A-Z]{1,2})?$")
PRICE_PLACES = Decimal("0.0001")
REFRESH_COOLDOWN_SECONDS = 300
QUOTE_CACHE_SECONDS = 5
MAX_QUOTE_AGE_SECONDS = 600

_last_refresh = {}
_quote_cache = {}


def normalize_symbol(symbol):
    cleaned = str(symbol).upper().strip()

    if not SYMBOL_PATTERN.match(cleaned):
        raise ValueError(f"'{symbol}' is not a valid stock symbol.")

    return cleaned


def fetch_daily_prices(symbol, period="1mo", now=None):
    """Download daily closes, leaving out any session that isn't final yet."""
    symbol = normalize_symbol(symbol)
    prices = get_provider().daily_bars(symbol, period)
    prices = prices.dropna(subset=["Close"])

    # Providers can include today's unfinished bar while the market is open.
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


def get_live_price(symbol, now=None):
    """Current price while the market is open, cached for a few seconds.

    Raises if the quote is too old to trust (quiet stocks on a one-exchange
    feed can go minutes without an update).
    """
    symbol = normalize_symbol(symbol)
    now = now or now_eastern()
    cached = _quote_cache.get(symbol)

    if cached and time.monotonic() - cached["fetched"] < QUOTE_CACHE_SECONDS:
        return cached["result"]

    price, quoted_at = get_provider().latest_price(symbol)
    age = (now - quoted_at).total_seconds()

    if age > MAX_QUOTE_AGE_SECONDS:
        raise ValueError(
            f"The latest {symbol} price is {age / 60:.0f} minutes old. "
            "Try again shortly, or pick a more actively traded stock."
        )

    result = {
        "symbol": symbol,
        "price": price.quantize(PRICE_PLACES),
        "price_date": now.date().isoformat(),
        "live": True,
    }
    _quote_cache[symbol] = {"fetched": time.monotonic(), "result": result}
    return result


def get_live_prices(symbols, now=None):
    return {symbol: get_live_price(symbol, now) for symbol in symbols}
