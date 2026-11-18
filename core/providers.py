"""Market data sources: Yahoo Finance and Alpaca.

A provider has two methods:
    daily_bars(symbol, period)  -> DataFrame with "Close" and "Adj Close"
                                   columns, indexed by Eastern-time dates
    latest_price(symbol)        -> (price as Decimal, when it was quoted)

Providers raise ValueError for problems with the request (unknown symbol)
and RuntimeError for problems with the service (down, rate limited, bad keys).
"""
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
import requests
import yfinance as yf

PERIOD_DAYS = {"5d": 8, "1mo": 35, "3mo": 100}
MAX_SPREAD = Decimal("0.02")


class YahooProvider:
    name = "yahoo"

    def daily_bars(self, symbol, period):
        try:
            prices = yf.Ticker(symbol).history(
                period=period, interval="1d", auto_adjust=False, actions=False
            )
        except Exception as error:
            raise RuntimeError(f"Could not reach Yahoo Finance: {error}") from error

        if prices.empty:
            raise ValueError(f"No price data found for {symbol}.")

        if not {"Close", "Adj Close"}.issubset(prices.columns):
            raise RuntimeError("Expected price columns were not returned.")

        return prices[["Close", "Adj Close"]]

    def latest_price(self, symbol):
        raise ValueError(
            "Live prices need Alpaca keys. Set ALPACA_API_KEY and "
            "ALPACA_API_SECRET, or use the 'daily_close' execution model."
        )


class AlpacaProvider:
    name = "alpaca"
    base_url = "https://data.alpaca.markets/v2/stocks"

    def __init__(self, key, secret, bars_feed="sip", live_feed="iex", session=None):
        self.bars_feed = bars_feed
        self.live_feed = live_feed
        self.session = session or requests.Session()
        self.headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

    def _get(self, path, params):
        try:
            response = self.session.get(
                f"{self.base_url}{path}", params=params,
                headers=self.headers, timeout=10,
            )
        except requests.RequestException as error:
            raise RuntimeError(f"Could not reach Alpaca: {error}") from error

        if response.status_code in (401, 403):
            raise RuntimeError(
                "Alpaca rejected the request. Check your API keys, and if bars "
                "fail, set ALPACA_BARS_FEED=iex (your plan may not include SIP data)."
            )
        if response.status_code == 429:
            raise RuntimeError("Alpaca is rate limiting us. Try again in a minute.")
        if response.status_code in (400, 404, 422):
            raise ValueError("Alpaca could not find that stock symbol.")
        if response.status_code >= 400:
            raise RuntimeError(f"Alpaca returned an error ({response.status_code}).")

        return response.json()

    def daily_bars(self, symbol, period):
        now = datetime.now(timezone.utc)
        data = self._get("/bars", {
            "symbols": symbol,
            "timeframe": "1Day",
            "start": (now - timedelta(days=PERIOD_DAYS[period])).date().isoformat(),
            # The free plan can't see SIP data from the last 15 minutes.
            "end": (now - timedelta(minutes=16)).isoformat(),
            "adjustment": "raw",
            "feed": self.bars_feed,
            "sort": "asc",
            "limit": 1000,
        })

        bars = (data.get("bars") or {}).get(symbol) or []

        if not bars:
            raise ValueError(f"No price data found for {symbol}.")

        index = pd.to_datetime([bar["t"] for bar in bars]).tz_convert("America/New_York")
        return pd.DataFrame(
            {"Close": [bar["c"] for bar in bars], "Adj Close": float("nan")},
            index=index,
        )

    def latest_price(self, symbol):
        data = self._get(f"/{symbol}/snapshot", {"feed": self.live_feed})
        quote = data.get("latestQuote") or {}
        trade = data.get("latestTrade") or {}

        bid = Decimal(str(quote.get("bp") or 0))
        ask = Decimal(str(quote.get("ap") or 0))

        # The midpoint is a fairer fill than the last print, but only when
        # the quote is sane. IEX quotes on quiet stocks can be very wide.
        if bid > 0 and ask >= bid and (ask - bid) / ((ask + bid) / 2) <= MAX_SPREAD:
            return (bid + ask) / 2, _as_datetime(quote["t"])

        if trade.get("p"):
            return Decimal(str(trade["p"])), _as_datetime(trade["t"])

        raise ValueError(f"No live price is available for {symbol} right now.")


_provider = None


def _as_datetime(stamp):
    """Alpaca timestamps have nanoseconds. Python datetimes stop at microseconds."""
    return pd.Timestamp(stamp).floor("us").to_pydatetime()


def get_provider():
    """Alpaca if keys are set (or PRICE_PROVIDER=alpaca), otherwise Yahoo."""
    global _provider

    if _provider is None:
        key = os.getenv("ALPACA_API_KEY")
        secret = os.getenv("ALPACA_API_SECRET")
        choice = os.getenv("PRICE_PROVIDER", "alpaca" if key and secret else "yahoo")

        if choice == "alpaca":
            if not (key and secret):
                raise RuntimeError("PRICE_PROVIDER=alpaca needs ALPACA_API_KEY and ALPACA_API_SECRET.")
            _provider = AlpacaProvider(
                key, secret,
                bars_feed=os.getenv("ALPACA_BARS_FEED", "sip"),
                live_feed=os.getenv("ALPACA_LIVE_FEED", "iex"),
            )
        elif choice == "yahoo":
            _provider = YahooProvider()
        else:
            raise RuntimeError(f"Unknown PRICE_PROVIDER '{choice}'. Use 'alpaca' or 'yahoo'.")

    return _provider


def reset_provider():
    global _provider
    _provider = None
