import yfinance as yf
import pandas as pd

from decimal import Decimal
from core.database import get_connection

def fetch_daily_prices(symbol: str, period: str = "1mo") -> pd.DataFrame:
    """
    Retrieve historical daily stock prices from Yahoo Finance.
    Returns closing and adjusted closing prices.
    """

    symbol = symbol.upper().strip()

    if not symbol:
        raise ValueError("Stock symbol is required.")

    ticker = yf.Ticker(symbol)
    prices = ticker.history(
        period=period,
        interval="1d",
        auto_adjust=False,
        actions=False
    )

    if prices.empty:
        raise ValueError("No price data found for {symbol}.")
    required_columns = {"Close", "Adj Close"}
    if not required_columns.issubset(prices.columns):
        raise RuntimeError("Expected price columns were not returned.")

    return prices[["Close", "Adj Close"]].copy()

def store_price_history(symbol: str, prices: pd.DataFrame):
    """
    Store daily closing and adjusted closing prices in the database
    """

    symbol = symbol.upper().strip()

    if not symbol:
        raise ValueError("Stock symbol is required.")

    with get_connection() as connection:
        for date, row in prices.iterrows():
            price_date = date.strftime("%Y-%m-%d")

            close_price = str(Decimal(str(row["Close"])))
            adjusted_close = str(Decimal(str(row["Adj Close"])))

            connection.execute("""
                INSERT INTO price_history (
                    symbol,
                    price_date,
                    close_price,
                    adjusted_close,
                    source
                )
                VALUES (?, ?, ?, ?, 'yfinance')
                
                ON CONFLICT(symbol, price_date)
                DO UPDATE SET
                    close_price = excluded.close_price,
                    adjusted_close = excluded.adjusted_close,
                    source = excluded.source,
                    fetched_at = strftime(
                        '%Y-%m-%dT%H:%M:%fZ',
                        'now'
                    )
                """, (
                    symbol,
                    price_date,
                    close_price,
                    adjusted_close
                ))

def get_latest_price(symbol: str) -> Decimal:
    """
    Retrieve the most recent stored closing price for a stock.
    """

    symbol = symbol.upper().strip()

    if not symbol:
        raise ValueError("Stock symbol is required.")

    with get_connection() as connection:

        price = connection.execute("""
            SELECT close_price
            FROM price_history
            WHERE symbol = ?
            ORDER BY price_date DESC
            LIMIT 1
        """, (symbol,)).fetchone()

        if price is None:
            raise ValueError(f"No price history found for {symbol}.")

        return Decimal(price["close_price"])

def get_historical_prices(
    symbol: str,
    start_date: str,
    end_date: str
) -> pd.DataFrame:
    """
    Retrieve historical daily prices for a stock
    within a specified date range.
    """

    symbol = symbol.upper().strip()

    if not symbol:
        raise ValueError("Stock symbol is required.")

    with get_connection() as connection:

        prices = connection.execute("""
            SELECT
                price_date,
                close_price,
                adjusted_close
            FROM price_history
            WHERE symbol = ?
            AND price_date >= ?
            AND price_date <= ?
            ORDER BY price_date ASC
        """, (symbol, start_date, end_date)).fetchall()

        if not prices:
            raise ValueError(
                f"No price history found for {symbol} "
                f"within the specified date range."
            )

        data = pd.DataFrame(
            [dict(row) for row in prices]
        )

        data["close_price"] = data["close_price"].apply(Decimal)
        data["adjusted_close"] = data["adjusted_close"].apply(Decimal)

        data.set_index("price_date", inplace=True)

        return data

def update_stock_prices(
    symbol: str,
    period: str = "1mo"
) -> int:
    """
    Retrieve recent daily prices and update the database.

    Returns the number of observations retrieved.
    """

    symbol = symbol.upper().strip()

    if not symbol:
        raise ValueError("Stock symbol is required.")

    # Retrieve recent daily prices.
    prices = fetch_daily_prices(symbol, period)

    # Store the retrieved observations.
    store_price_history(symbol, prices)

    return len(prices)