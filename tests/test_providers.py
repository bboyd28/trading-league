from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import requests

import core.providers as providers


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self.body = body or {}

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def alpaca(response, **options):
    session = FakeSession(response)
    return providers.AlpacaProvider("key", "secret", session=session, **options), session


# ---- daily bars ----------------------------------------------------------

def test_bars_become_a_frame_indexed_by_eastern_date():
    provider, session = alpaca(FakeResponse(body={"bars": {"AAPL": [
        {"t": "2026-11-12T05:00:00Z", "c": 99.5},     # winter: midnight ET is 05:00Z
        {"t": "2026-11-13T05:00:00Z", "c": 100.25},
    ]}}))

    frame = provider.daily_bars("AAPL", "1mo")

    assert [d.strftime("%Y-%m-%d") for d in frame.index] == ["2026-11-12", "2026-11-13"]
    assert list(frame["Close"]) == [99.5, 100.25]
    assert frame["Adj Close"].isna().all()


def test_summer_bars_land_on_the_right_date():
    provider, _ = alpaca(FakeResponse(body={"bars": {"AAPL": [
        {"t": "2026-07-14T04:00:00Z", "c": 200.0},    # summer: midnight ET is 04:00Z
    ]}}))

    assert provider.daily_bars("AAPL", "5d").index[0].strftime("%Y-%m-%d") == "2026-07-14"


def test_bars_request_is_raw_daily_and_authenticated():
    provider, session = alpaca(
        FakeResponse(body={"bars": {"AAPL": [{"t": "2026-11-13T05:00:00Z", "c": 1}]}}),
        bars_feed="iex",
    )

    provider.daily_bars("AAPL", "1mo")
    call = session.calls[0]

    assert call["url"].endswith("/v2/stocks/bars")
    assert call["params"]["timeframe"] == "1Day"
    assert call["params"]["adjustment"] == "raw"
    assert call["params"]["feed"] == "iex"
    assert call["headers"] == {"APCA-API-KEY-ID": "key", "APCA-API-SECRET-KEY": "secret"}

    end = datetime.fromisoformat(call["params"]["end"])
    assert datetime.now(timezone.utc) - end >= timedelta(minutes=15)


@pytest.mark.parametrize("body", [{"bars": {}}, {"bars": None}, {}])
def test_empty_bars_are_a_value_error(body):
    provider, _ = alpaca(FakeResponse(body=body))

    with pytest.raises(ValueError, match="No price data found for ZZZZ"):
        provider.daily_bars("ZZZZ", "1mo")


# ---- error handling ------------------------------------------------------

@pytest.mark.parametrize("status, error, message", [
    (401, RuntimeError, "API keys"),
    (403, RuntimeError, "API keys"),
    (429, RuntimeError, "rate limiting"),
    (500, RuntimeError, "error \\(500\\)"),
    (400, ValueError, "could not find"),
    (404, ValueError, "could not find"),
])
def test_http_errors_map_to_clear_messages(status, error, message):
    provider, _ = alpaca(FakeResponse(status))

    with pytest.raises(error, match=message):
        provider.daily_bars("AAPL", "1mo")


def test_network_failure_is_a_runtime_error():
    provider, _ = alpaca(requests.ConnectionError("offline"))

    with pytest.raises(RuntimeError, match="Could not reach Alpaca"):
        provider.latest_price("AAPL")


# ---- live price ----------------------------------------------------------

def snapshot(bid=None, ask=None, trade=None, quote_time="2026-11-16T15:00:00.123456789Z"):
    body = {}
    if bid is not None:
        body["latestQuote"] = {"bp": bid, "ap": ask, "t": quote_time}
    if trade is not None:
        body["latestTrade"] = {"p": trade, "t": "2026-11-16T14:59:00Z"}
    return FakeResponse(body=body)


def test_live_price_is_the_quote_midpoint():
    provider, session = alpaca(snapshot(bid=100.00, ask=100.10, trade=99.0))

    price, quoted_at = provider.latest_price("AAPL")

    assert price == Decimal("100.05")
    assert quoted_at == datetime(2026, 11, 16, 15, 0, 0, 123456, tzinfo=timezone.utc)
    assert session.calls[0]["url"].endswith("/AAPL/snapshot")
    assert session.calls[0]["params"] == {"feed": "iex"}


def test_wide_spread_falls_back_to_the_last_trade():
    provider, _ = alpaca(snapshot(bid=90.0, ask=110.0, trade=99.0))

    assert provider.latest_price("AAPL")[0] == Decimal("99.0")


def test_missing_quote_falls_back_to_the_last_trade():
    provider, _ = alpaca(snapshot(trade=99.0))

    assert provider.latest_price("AAPL")[0] == Decimal("99.0")


def test_no_quote_and_no_trade_is_a_value_error():
    provider, _ = alpaca(FakeResponse(body={}))

    with pytest.raises(ValueError, match="No live price"):
        provider.latest_price("AAPL")


# ---- choosing a provider -------------------------------------------------

def test_yahoo_is_the_default():
    assert isinstance(providers.get_provider(), providers.YahooProvider)


def test_keys_switch_to_alpaca(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    monkeypatch.setenv("ALPACA_BARS_FEED", "iex")

    provider = providers.get_provider()

    assert isinstance(provider, providers.AlpacaProvider)
    assert provider.bars_feed == "iex"
    assert provider.live_feed == "iex"


def test_provider_is_built_once():
    assert providers.get_provider() is providers.get_provider()


def test_alpaca_without_keys_is_an_error(monkeypatch):
    monkeypatch.setenv("PRICE_PROVIDER", "alpaca")

    with pytest.raises(RuntimeError, match="needs ALPACA_API_KEY"):
        providers.get_provider()


def test_unknown_provider_is_an_error(monkeypatch):
    monkeypatch.setenv("PRICE_PROVIDER", "bloomberg")

    with pytest.raises(RuntimeError, match="Unknown PRICE_PROVIDER"):
        providers.get_provider()


def test_yahoo_cannot_give_live_prices():
    with pytest.raises(ValueError, match="Live prices need Alpaca"):
        providers.YahooProvider().latest_price("AAPL")
