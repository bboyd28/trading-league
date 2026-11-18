"""Accounts, trades, and portfolio valuation.

Money is stored as integer cents. Share quantities are stored as decimal
text with 8 places. The trades table is the ledger: holdings and cash can
always be rebuilt from it (see find_cash_mismatches).
"""
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP

from core.database import get_connection, get_league_settings
from core.prices import (
    get_latest_prices,
    get_live_prices,
    get_prices_on_or_before,
    normalize_symbol,
)

QUANTITY_PLACES = Decimal("0.00000001")
MIN_BUY_CENTS = 100


# ---- small helpers -------------------------------------------------------

def to_decimal(value, name="Value"):
    """Parse user input into a finite Decimal, or raise ValueError."""
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f"{name} must be a number.") from None

    if not number.is_finite():
        raise ValueError(f"{name} must be a number.")

    return number


def to_cents(amount):
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _fee_cents(gross_cents, fee_rate_bps):
    fee = Decimal(gross_cents) * fee_rate_bps / 10_000
    return int(fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _to_quantity(value, name="Quantity"):
    quantity = to_decimal(value, name).quantize(QUANTITY_PLACES, rounding=ROUND_DOWN)

    if quantity <= 0:
        raise ValueError(f"{name} must be greater than zero.")

    return quantity


def _to_price(value):
    price = to_decimal(value, "Price")

    if price <= 0:
        raise ValueError("Price must be greater than zero.")

    return price


def _text(number):
    return format(number.normalize(), "f")


def _active_user(connection, discord_id):
    user = connection.execute("""
        SELECT cash_balance_cents FROM users
        WHERE discord_id = ? AND is_active = 1
    """, (discord_id,)).fetchone()

    if user is None:
        raise ValueError("User does not exist or is inactive.")

    return user


def _replay(connection, discord_id, as_of=None):
    """Replay a user's trades. Returns (net cash change in cents, holdings)."""
    query = """
        SELECT symbol, side, quantity, gross_amount_cents, fee_cents
        FROM trades WHERE discord_id = ?
    """
    params = [discord_id]

    if as_of is not None:
        query += " AND price_date <= ?"
        params.append(as_of)

    cash_change = 0
    holdings = {}

    for trade in connection.execute(query + " ORDER BY trade_id", params):
        quantity = Decimal(trade["quantity"])

        if trade["side"] == "BUY":
            cash_change -= trade["gross_amount_cents"] + trade["fee_cents"]
        else:
            cash_change += trade["gross_amount_cents"] - trade["fee_cents"]
            quantity = -quantity

        holdings[trade["symbol"]] = holdings.get(trade["symbol"], Decimal(0)) + quantity

    holdings = {s: q for s, q in holdings.items() if q > 0}
    return cash_change, holdings


def _insert_trade(connection, discord_id, symbol, side, quantity, price,
                  gross_cents, fee_cents, price_date):
    connection.execute("""
        INSERT INTO trades (
            discord_id, symbol, side, quantity, price_per_share,
            gross_amount_cents, fee_cents, price_date
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (discord_id, symbol, side, _text(quantity), _text(price),
          gross_cents, fee_cents, price_date))


# ---- accounts ------------------------------------------------------------

def register_user(discord_id, username):
    """Create a league account. Re-registering only updates the username."""
    if not discord_id or not username:
        raise ValueError("Discord ID and username are required.")

    with get_connection(write=True) as connection:
        starting_balance = get_league_settings(connection)["starting_balance_cents"]

        is_new = connection.execute(
            "SELECT 1 FROM users WHERE discord_id = ?", (discord_id,)
        ).fetchone() is None

        connection.execute("""
            INSERT INTO users (
                discord_id, username, cash_balance_cents, starting_balance_cents
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET username = excluded.username
        """, (discord_id, username, starting_balance, starting_balance))

        user = connection.execute(
            "SELECT * FROM users WHERE discord_id = ?", (discord_id,)
        ).fetchone()

    return {**dict(user), "is_new": is_new}


def get_active_users():
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT discord_id FROM users WHERE is_active = 1 ORDER BY discord_id"
        ).fetchall()

    return [row["discord_id"] for row in rows]


# ---- trading -------------------------------------------------------------

def buy_stock(discord_id, symbol, quantity, price_per_share, price_date):
    """Buy (fractional) shares. Cash drops by the cost plus the fee."""
    symbol = normalize_symbol(symbol)
    quantity = _to_quantity(quantity)
    price = _to_price(price_per_share)

    gross_cents = to_cents(quantity * price)

    if gross_cents < MIN_BUY_CENTS:
        raise ValueError("Minimum purchase is $1.00.")

    with get_connection(write=True) as connection:
        cash = _active_user(connection, discord_id)["cash_balance_cents"]
        fee_cents = _fee_cents(
            gross_cents, get_league_settings(connection)["fee_rate_bps"]
        )
        total_cost = gross_cents + fee_cents

        if total_cost > cash:
            raise ValueError("Insufficient funds.")

        connection.execute("""
            UPDATE users SET cash_balance_cents = cash_balance_cents - ?
            WHERE discord_id = ?
        """, (total_cost, discord_id))

        _insert_trade(connection, discord_id, symbol, "BUY", quantity, price,
                      gross_cents, fee_cents, price_date)

    return {
        "symbol": symbol,
        "quantity": quantity,
        "price_per_share": price,
        "gross_amount_cents": gross_cents,
        "fee_cents": fee_cents,
        "total_cost_cents": total_cost,
    }


def buy_stock_by_amount(discord_id, symbol, dollar_amount, price_per_share, price_date):
    """Buy as many shares as the amount covers. The fee is charged on top."""
    amount = to_decimal(dollar_amount, "Dollar amount")
    price = _to_price(price_per_share)

    if amount <= 0:
        raise ValueError("Dollar amount must be greater than zero.")

    quantity = (amount / price).quantize(QUANTITY_PLACES, rounding=ROUND_DOWN)
    return buy_stock(discord_id, symbol, quantity, price, price_date)


def _sell(discord_id, symbol, quantity, dollar_amount, price_per_share, price_date):
    symbol = normalize_symbol(symbol)
    price = _to_price(price_per_share)

    if dollar_amount is not None:
        amount = to_decimal(dollar_amount, "Sale amount")

        if amount <= 0:
            raise ValueError("Sale amount must be greater than zero.")

        quantity = (amount / price).quantize(QUANTITY_PLACES, rounding=ROUND_DOWN)

        if quantity <= 0:
            raise ValueError("Sale amount is too small.")

    elif quantity is not None:
        quantity = _to_quantity(quantity)

    with get_connection(write=True) as connection:
        _active_user(connection, discord_id)
        owned = _replay(connection, discord_id)[1].get(symbol, Decimal(0))

        if owned <= 0:
            raise ValueError(f"You do not own any shares of {symbol}.")

        sells_everything = quantity is None or quantity == owned

        if quantity is None:
            quantity = owned

        if quantity > owned:
            if dollar_amount is not None:
                raise ValueError(
                    f"Insufficient shares. Your {symbol} position is worth "
                    f"approximately ${owned * price:,.2f}."
                )
            raise ValueError(f"Insufficient shares. You own {_text(owned)} shares.")

        gross_cents = to_cents(quantity * price)

        # A partial sale that rounds to $0 would just destroy shares.
        if gross_cents < 1 and not sells_everything:
            raise ValueError("Sale amount is too small.")

        fee_cents = _fee_cents(
            gross_cents, get_league_settings(connection)["fee_rate_bps"]
        )
        net_proceeds = gross_cents - fee_cents

        connection.execute("""
            UPDATE users SET cash_balance_cents = cash_balance_cents + ?
            WHERE discord_id = ?
        """, (net_proceeds, discord_id))

        _insert_trade(connection, discord_id, symbol, "SELL", quantity, price,
                      gross_cents, fee_cents, price_date)

    return {
        "symbol": symbol,
        "quantity": quantity,
        "price_per_share": price,
        "gross_amount_cents": gross_cents,
        "fee_cents": fee_cents,
        "net_proceeds_cents": net_proceeds,
    }


def sell_stock(discord_id, symbol, quantity, price_per_share, price_date):
    """Sell shares. Pass quantity=None to sell the whole position."""
    return _sell(discord_id, symbol, quantity, None, price_per_share, price_date)


def sell_stock_by_amount(discord_id, symbol, dollar_amount, price_per_share, price_date):
    """Sell enough shares to raise the gross dollar amount."""
    return _sell(discord_id, symbol, None, dollar_amount, price_per_share, price_date)


# ---- reading portfolios --------------------------------------------------

def get_portfolio(discord_id):
    """Cash and share counts. Holdings come from the trade ledger."""
    with get_connection() as connection:
        user = connection.execute("""
            SELECT discord_id, username, cash_balance_cents
            FROM users WHERE discord_id = ?
        """, (discord_id,)).fetchone()

        if user is None:
            raise ValueError("User does not exist.")

        holdings = _replay(connection, discord_id)[1]

    return {
        "discord_id": user["discord_id"],
        "username": user["username"],
        "cash_balance": Decimal(user["cash_balance_cents"]) / 100,
        "holdings": holdings,
    }


def _value_holdings(holdings, prices):
    valued = {}

    for symbol, quantity in holdings.items():
        price = prices[symbol]
        valued[symbol] = {
            "quantity": quantity,
            "price": price["price"],
            "price_date": price["price_date"],
            "live": price.get("live", False),
            "market_value": quantity * price["price"],
        }

    return valued


def get_valued_portfolio(discord_id, live=False):
    """Portfolio valued at the latest stored closes, or live prices if asked.

    If live quotes can't be had, it falls back to the stored closes.
    """
    portfolio = get_portfolio(discord_id)
    symbols = portfolio["holdings"]
    prices = None

    if live and symbols:
        try:
            prices = get_live_prices(symbols)
        except (ValueError, RuntimeError):
            prices = None

    if prices is None:
        prices = get_latest_prices(symbols)

    holdings = _value_holdings(portfolio["holdings"], prices)
    holdings_value = sum((h["market_value"] for h in holdings.values()), Decimal(0))

    return {
        "discord_id": portfolio["discord_id"],
        "username": portfolio["username"],
        "cash_balance": portfolio["cash_balance"],
        "holdings": holdings,
        "holdings_value": holdings_value,
        "total_value": portfolio["cash_balance"] + holdings_value,
    }


def get_historical_valued_portfolio(discord_id, target_date, require_exact_prices=False):
    """Rebuild a portfolio as of target_date from the ledger.

    With require_exact_prices, every holding must have a close on that exact
    date. Snapshots use this so a missing price can't quietly become a
    stale one.
    """
    with get_connection() as connection:
        user = connection.execute("""
            SELECT discord_id, username, starting_balance_cents
            FROM users WHERE discord_id = ?
        """, (discord_id,)).fetchone()

        if user is None:
            raise ValueError("User does not exist.")

        start = user["starting_balance_cents"]
        if start is None:
            start = get_league_settings(connection)["starting_balance_cents"]

        net_cash, holdings = _replay(connection, discord_id, target_date)

    prices = get_prices_on_or_before(holdings, target_date)

    if require_exact_prices:
        for symbol, price in prices.items():
            if price["price_date"] != target_date:
                raise ValueError(f"No {symbol} close for {target_date}.")

    valued = _value_holdings(holdings, prices)
    holdings_value = sum((h["market_value"] for h in valued.values()), Decimal(0))
    cash_balance = Decimal(start + net_cash) / 100

    return {
        "discord_id": user["discord_id"],
        "username": user["username"],
        "snapshot_date": target_date,
        "cash_balance": cash_balance,
        "holdings": valued,
        "holdings_value": holdings_value,
        "total_value": cash_balance + holdings_value,
    }


def save_portfolio_snapshot(discord_id, snapshot_date, require_exact_prices=False):
    """Save (or recalculate) a user's end-of-day snapshot and position rows."""
    portfolio = get_historical_valued_portfolio(
        discord_id, snapshot_date, require_exact_prices
    )

    cash_cents = to_cents(portfolio["cash_balance"])
    holdings_cents = to_cents(portfolio["holdings_value"])
    total_cents = cash_cents + holdings_cents

    with get_connection(write=True) as connection:
        connection.execute("""
            INSERT INTO portfolio_snapshots (
                discord_id, snapshot_date, cash_balance_cents,
                holdings_value_cents, total_value_cents
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(discord_id, snapshot_date) DO UPDATE SET
                cash_balance_cents = excluded.cash_balance_cents,
                holdings_value_cents = excluded.holdings_value_cents,
                total_value_cents = excluded.total_value_cents
        """, (discord_id, snapshot_date, cash_cents, holdings_cents, total_cents))

        connection.execute("""
            DELETE FROM position_snapshots
            WHERE discord_id = ? AND snapshot_date = ?
        """, (discord_id, snapshot_date))

        connection.executemany("""
            INSERT INTO position_snapshots (
                discord_id, snapshot_date, symbol, quantity, price, market_value_cents
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, [
            (discord_id, snapshot_date, symbol, _text(h["quantity"]),
             _text(h["price"]), to_cents(h["market_value"]))
            for symbol, h in portfolio["holdings"].items()
        ])

    return {
        "discord_id": discord_id,
        "snapshot_date": snapshot_date,
        "cash_balance": Decimal(cash_cents) / 100,
        "holdings_value": Decimal(holdings_cents) / 100,
        "total_value": Decimal(total_cents) / 100,
    }


def get_active_symbols():
    """Symbols currently held by at least one active user."""
    with get_connection() as connection:
        user_ids = [
            row["discord_id"]
            for row in connection.execute(
                "SELECT discord_id FROM users WHERE is_active = 1"
            )
        ]
        symbols = set()

        for discord_id in user_ids:
            symbols.update(_replay(connection, discord_id)[1])

    return sorted(symbols)


def get_recent_trades(discord_id, limit=10):
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT symbol, side, quantity, price_per_share,
                   gross_amount_cents, fee_cents, price_date, executed_at
            FROM trades WHERE discord_id = ?
            ORDER BY trade_id DESC LIMIT ?
        """, (discord_id, limit)).fetchall()

    return [dict(row) for row in rows]


def find_cash_mismatches():
    """Users whose stored cash doesn't match what the ledger says it should be."""
    mismatches = []

    with get_connection() as connection:
        default_start = get_league_settings(connection)["starting_balance_cents"]

        for user in connection.execute("SELECT * FROM users").fetchall():
            start = user["starting_balance_cents"]
            start = default_start if start is None else start
            expected = start + _replay(connection, user["discord_id"])[0]

            if expected != user["cash_balance_cents"]:
                mismatches.append({
                    "discord_id": user["discord_id"],
                    "username": user["username"],
                    "stored_cents": user["cash_balance_cents"],
                    "expected_cents": expected,
                })

    return mismatches
