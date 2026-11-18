"""The one place orders get placed.

Discord commands call this. A strategy bot or a broker connection would
too, so the trading rules (window, price source) live in one spot.
"""
from core import portfolio
from core.database import get_connection, get_league_settings
from core.market_calendar import (
    SETTLING_MESSAGE,
    WINDOW_MESSAGE,
    closing_prices_settling,
    last_completed_session,
    market_in_session,
    now_eastern,
    trading_window_open,
)
from core.prices import get_execution_price, get_live_price, normalize_symbol

# daily_close: fills at the last close, only while the market is closed
# live_quote:  fills at the live price during the session, last close otherwise
# any_time:    fills at the last close at any hour (for testing)
EXECUTION_MODELS = {"daily_close", "live_quote", "any_time"}


def get_execution_model():
    with get_connection() as connection:
        model = get_league_settings(connection)["execution_model"]

    if model not in EXECUTION_MODELS:
        raise RuntimeError(f"Unknown execution model '{model}'.")

    return model


def set_execution_model(model):
    if model not in EXECUTION_MODELS:
        raise ValueError(f"Model must be one of: {', '.join(sorted(EXECUTION_MODELS))}.")

    with get_connection(write=True) as connection:
        connection.execute("UPDATE league_settings SET execution_model = ?", (model,))


def live_prices_enabled(now=None):
    """True when portfolios should be valued at live quotes right now."""
    return get_execution_model() == "live_quote" and market_in_session(now)


def _check_trading_window(model, now):
    if model == "daily_close" and not trading_window_open(now):
        raise ValueError(WINDOW_MESSAGE)

    if model == "live_quote" and closing_prices_settling(now):
        raise ValueError(SETTLING_MESSAGE)


def _fill_price(symbol, model, now):
    if model == "live_quote" and market_in_session(now):
        return get_live_price(symbol, now)

    return get_execution_price(symbol, now)


def place_order(discord_id, symbol, side, *, quantity=None, amount=None, now=None):
    """Place a market order that fills at the last official close.

    Give either quantity or amount (dollars). A sell may use quantity="all".
    Raises ValueError for anything the user can fix, RuntimeError otherwise.
    """
    now = now or now_eastern()
    side = side.upper()
    symbol = normalize_symbol(symbol)

    if side not in {"BUY", "SELL"}:
        raise ValueError("Side must be BUY or SELL.")

    sell_all = (
        side == "SELL"
        and isinstance(quantity, str)
        and quantity.strip().lower() == "all"
    )

    if not sell_all and (quantity is None) == (amount is None):
        raise ValueError("Give either a quantity or a dollar amount.")

    model = get_execution_model()
    _check_trading_window(model, now)
    price = _fill_price(symbol, model, now)
    args = (discord_id, symbol)
    fill = (price["price"], price["price_date"])

    if side == "BUY" and amount is not None:
        result = portfolio.buy_stock_by_amount(*args, amount, *fill)
    elif side == "BUY":
        result = portfolio.buy_stock(*args, quantity, *fill)
    elif amount is not None:
        result = portfolio.sell_stock_by_amount(*args, amount, *fill)
    else:
        result = portfolio.sell_stock(*args, None if sell_all else quantity, *fill)

    cash_change = result.get("total_cost_cents", result.get("net_proceeds_cents"))

    return {
        **result,
        "side": side,
        "price_date": price["price_date"],
        "filled_live": bool(price.get("live")),
        "cash_change_cents": cash_change,
    }


def register(discord_id, username, now=None):
    """Sign a player up and save a day-zero snapshot so returns have a baseline."""
    user = portfolio.register_user(discord_id, username)

    if user["is_new"]:
        session = last_completed_session(now).isoformat()
        portfolio.save_portfolio_snapshot(discord_id, session)

    return user
