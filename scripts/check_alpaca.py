"""Check your Alpaca keys and data access. Run from the project root:

    python -m scripts.check_alpaca

Reads ALPACA_API_KEY and ALPACA_API_SECRET from .env. Nothing is saved.
"""
import sys

from dotenv import load_dotenv

from core.market_calendar import last_completed_session, now_eastern
from core.providers import get_provider


def step(name, action):
    try:
        result = action()
    except Exception as error:
        print(f"FAIL  {name}: {error}")
        return None

    print(f"ok    {name}")
    return result


def main():
    load_dotenv()
    provider = step("load keys", get_provider)

    if provider is None or provider.name != "alpaca":
        print("\nSet ALPACA_API_KEY and ALPACA_API_SECRET in .env first.")
        return 1

    now = now_eastern()
    expected = last_completed_session(now)

    bars = step("daily bars for SPY", lambda: provider.daily_bars("SPY", "5d"))
    if bars is not None:
        last = bars.index[-1].date()
        print(f"      last bar: {last}, close {bars['Close'].iloc[-1]}")
        print(f"      expected last completed session: {expected}")
        if last < expected:
            print("      Heads up: the newest close isn't available yet.")

    quote = step("live price for AAPL", lambda: provider.latest_price("AAPL"))
    if quote is not None:
        price, quoted_at = quote
        age = (now - quoted_at).total_seconds()
        print(f"      price {price}, quoted {age:.0f} seconds ago")
        print("      (outside market hours this is the last IEX quote, so it will be old)")

    step("unknown symbol is rejected cleanly", lambda: _expect_value_error(provider))
    return 0


def _expect_value_error(provider):
    try:
        provider.daily_bars("ZZZZZ", "5d")
    except ValueError:
        return
    raise RuntimeError("an unknown symbol did not raise ValueError")


if __name__ == "__main__":
    sys.exit(main())
