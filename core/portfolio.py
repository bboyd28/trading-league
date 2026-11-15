from decimal import Decimal, ROUND_HALF_UP

from core.database import get_connection
from core.prices import get_latest_price


def register_user(discord_id: str, username: str):
    """
    Register a new league participant.

    Existing users keep their current balance.
    Only their username is updated if they register again.
    """

    if not discord_id or not username:
        raise ValueError("Discord ID and username are required.")

    with get_connection() as connection:

        settings = connection.execute("""
            SELECT starting_balance_cents
            FROM league_settings
            WHERE setting_id = 1
        """).fetchone()

        if settings is None:
            raise RuntimeError("League settings have not been initialized.")

        starting_balance = settings["starting_balance_cents"]


        connection.execute("""
            INSERT INTO users (
                discord_id,
                username,
                cash_balance_cents
            )
            VALUES (?, ?, ?)

            ON CONFLICT(discord_id)
            DO UPDATE SET username = excluded.username
        """, (discord_id, username, starting_balance))


        user = connection.execute("""
            SELECT *
            FROM users
            WHERE discord_id = ?
        """, (discord_id,)).fetchone()

        return dict(user)


def buy_stock(
    discord_id: str,
    symbol: str,
    quantity: Decimal,
    price_per_share: Decimal,
    price_date: str
):
    """
    Purchase fractional shares of a stock.

    Deducts the purchase amount and transaction fee
    from the user's cash balance.
    """

    quantity = Decimal(str(quantity))
    price_per_share = Decimal(str(price_per_share))

    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")

    if price_per_share <= 0:
        raise ValueError("Price must be greater than zero.")

    symbol = symbol.upper().strip()

    if not symbol:
        raise ValueError("Stock symbol is required.")

    # Calculate the gross purchase amount.
    gross_amount = quantity * price_per_share

    gross_cents = int(
        (gross_amount * 100).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP
        )
    )

    with get_connection() as connection:

        # Retrieve the user's cash balance.
        user = connection.execute("""
            SELECT cash_balance_cents
            FROM users
            WHERE discord_id = ?
            AND is_active = 1
        """, (discord_id,)).fetchone()

        if user is None:
            raise ValueError("User does not exist or is inactive.")

        # Retrieve the league's transaction fee.
        settings = connection.execute("""
            SELECT fee_rate_bps
            FROM league_settings
            WHERE setting_id = 1
        """).fetchone()

        if settings is None:
            raise RuntimeError("League settings have not been initialized.")

        fee_rate = Decimal(settings["fee_rate_bps"]) / Decimal("10000")

        fee_cents = int(
            (Decimal(gross_cents) * fee_rate).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP
            )
        )

        total_cost = gross_cents + fee_cents

        # Prevent purchases that exceed available cash.
        if total_cost > user["cash_balance_cents"]:
            raise ValueError("Insufficient funds.")

        # Deduct the purchase amount and fee.
        connection.execute("""
            UPDATE users
            SET cash_balance_cents = cash_balance_cents - ?
            WHERE discord_id = ?
        """, (total_cost, discord_id))

        # Record the completed purchase.
        connection.execute("""
            INSERT INTO trades (
                discord_id,
                symbol,
                side,
                quantity,
                price_per_share,
                gross_amount_cents,
                fee_cents,
                price_date
            )
            VALUES (?, ?, 'BUY', ?, ?, ?, ?, ?)
        """, (
            discord_id,
            symbol,
            str(quantity),
            str(price_per_share),
            gross_cents,
            fee_cents,
            price_date
        ))

    return {
        "symbol": symbol,
        "quantity": quantity,
        "price_per_share": price_per_share,
        "gross_amount_cents": gross_cents,
        "fee_cents": fee_cents,
        "total_cost_cents": total_cost
    }


def sell_stock(
    discord_id: str,
    symbol: str,
    quantity: Decimal,
    price_per_share: Decimal,
    price_date: str
):
    """
    Sell fractional shares of a stock.

    Adds the sale proceeds, minus transaction fees,
    to the user's cash balance.
    """


    quantity = Decimal(str(quantity))
    price_per_share = Decimal(str(price_per_share))

    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    if price_per_share <= 0:
        raise ValueError("Price must be greater than zero.")


    symbol = symbol.upper().strip()

    if not symbol:
        raise ValueError("Stock symbol is required.")

    with get_connection() as connection:

        user = connection.execute("""
            SELECT cash_balance_cents
            FROM users
            WHERE discord_id = ?
            AND is_active = 1
        """, (discord_id,)).fetchone()

        if user is None:
            raise ValueError("User does not exist or is inactive.")

        trades = connection.execute("""
            SELECT side, quantity
            FROM trades
            WHERE discord_id = ?
            AND symbol = ?
        """, (discord_id, symbol)).fetchall()

        owned_shares = Decimal("0")

        for trade in trades:
            trade_quantity = Decimal(trade["quantity"])

            if trade["side"] == "BUY":
                owned_shares += trade_quantity
            else:
                owned_shares -= trade_quantity


        if quantity > owned_shares:
            raise ValueError(
                f"Insufficient shares. You own {owned_shares} shares."
        )



        gross_amount = quantity * price_per_share

        gross_cents = int(
            (gross_amount * 100).quantize(
                Decimal("1"),
                rounding = ROUND_HALF_UP
            )
        )

        settings = connection.execute("""
            SELECT fee_rate_bps
            FROM league_settings
            WHERE setting_id = 1
        """).fetchone()

        if settings is None:
            raise RuntimeError("League settings have not been initialized.")

        fee_rate = Decimal(settings["fee_rate_bps"]) / Decimal("10000")

        fee_cents = int(
            (Decimal(gross_cents) * fee_rate).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP
            )
        )

        net_proceeds = gross_cents - fee_cents

        connection.execute("""
            UPDATE users
            SET cash_balance_cents = cash_balance_cents + ?
            WHERE discord_id = ?
        """, (net_proceeds, discord_id))

        connection.execute("""
                INSERT INTO trades (
                    discord_id,
                    symbol,
                    side,
                    quantity,
                    price_per_share,
                    gross_amount_cents,
                    fee_cents,
                    price_date
                )
                VALUES (?, ?, 'SELL', ?, ?, ?, ?, ?)
            """, (
                discord_id,
                symbol,
                str(quantity),
                str(price_per_share),
                gross_cents,
                fee_cents,
                price_date
            ))

        return {
            "symbol": symbol,
            "quantity": quantity,
            "price_per_share": price_per_share,
            "gross_amount_cents": gross_cents,
            "fee_cents": fee_cents,
            "net_proceeds_cents": net_proceeds
    }
def get_portfolio(discord_id: str):
    """
    Retrieve a user's cash balance and current stock holdings.
    Holdings are reconstructed from the trade ledger.
    """

    with get_connection() as connection:

        user = connection.execute("""
            SELECT discord_id, username, cash_balance_cents
            FROM users
            WHERE discord_id = ?
        """, (discord_id,)).fetchone()

        if user is None:
            raise ValueError("User does not exist.")

        trades = connection.execute("""
            SELECT symbol, side, quantity
            FROM trades
            WHERE discord_id = ?
        """, (discord_id,)).fetchall()


        holdings = {}

        for trade in trades:
            symbol = trade["symbol"]
            quantity = Decimal(trade["quantity"])

            if symbol not in holdings:
                holdings[symbol] = Decimal("0")

            if trade["side"] == "BUY":
                holdings[symbol] += quantity
            else:
                holdings[symbol] -= quantity

        holdings = {
            symbol: quantity
            for symbol, quantity in holdings.items()
            if quantity > 0
        }

        return {
            "discord_id": user["discord_id"],
            "username": user["username"],
            "cash_balance": Decimal(user["cash_balance_cents"]) / 100,
            "holdings": holdings
        }

def get_valued_portfolio(discord_id: str):
    """
    Retrieve a user's portfolio with current stored market prices.

    Calculates individual holding values and total portfolio value.
    """

    # Retrieve the user's existing portfolio.
    portfolio = get_portfolio(discord_id)

    holdings_value = Decimal("0")
    valued_holdings = {}

    # Calculate the market value of each holding.
    for symbol, quantity in portfolio["holdings"].items():

        price = get_latest_price(symbol)

        market_value = quantity * price

        valued_holdings[symbol] = {
            "quantity": quantity,
            "price": price,
            "market_value": market_value
        }

        holdings_value += market_value

    # Calculate total portfolio value.
    total_value = portfolio["cash_balance"] + holdings_value

    return {
        "discord_id": portfolio["discord_id"],
        "username": portfolio["username"],
        "cash_balance": portfolio["cash_balance"],
        "holdings": valued_holdings,
        "holdings_value": holdings_value,
        "total_value": total_value
    }

def save_portfolio_snapshot(discord_id: str, snapshot_date: str):
    """
    Save a daily snapshot of a user's portfolio.

    Records cash, holdings value, and total portfolio value.
    """

    # Retrieve the user's current portfolio valuation.
    portfolio = get_valued_portfolio(discord_id)

    # Convert dollar values into integer cents.
    cash_cents = int(
        (portfolio["cash_balance"] * 100).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP
        )
    )

    holdings_cents = int(
        (portfolio["holdings_value"] * 100).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP
        )
    )

    total_cents = cash_cents + holdings_cents

    with get_connection() as connection:

        connection.execute("""
            INSERT INTO portfolio_snapshots (
                discord_id,
                snapshot_date,
                cash_balance_cents,
                holdings_value_cents,
                total_value_cents
            )
            VALUES (?, ?, ?, ?, ?)

            ON CONFLICT(discord_id, snapshot_date)
            DO UPDATE SET
                cash_balance_cents = excluded.cash_balance_cents,
                holdings_value_cents = excluded.holdings_value_cents,
                total_value_cents = excluded.total_value_cents
        """, (
            discord_id,
            snapshot_date,
            cash_cents,
            holdings_cents,
            total_cents
        ))

    return {
        "discord_id": discord_id,
        "snapshot_date": snapshot_date,
        "cash_balance": Decimal(cash_cents) / 100,
        "holdings_value": Decimal(holdings_cents) / 100,
        "total_value": Decimal(total_cents) / 100
    }

def get_active_symbols():
    """
    Retrieve every stock currently held by at least
    one active league participant.
    """

    with get_connection() as connection:

        trades = connection.execute("""
            SELECT
                trades.discord_id,
                trades.symbol,
                trades.side,
                trades.quantity
            FROM trades
            JOIN users
                ON trades.discord_id = users.discord_id
            WHERE users.is_active = 1
        """).fetchall()

        holdings = {}

        for trade in trades:
            key = (trade["discord_id"], trade["symbol"])

            if key not in holdings:
                holdings[key] = Decimal("0")

            quantity = Decimal(trade["quantity"])

            if trade["side"] == "BUY":
                holdings[key] += quantity
            else:
                holdings[key] -= quantity

        symbols = {
            symbol
            for (discord_id, symbol), quantity in holdings.items()
            if quantity > 0
        }

        return sorted(symbols)


def get_active_users():
    """
    Retrieve the Discord IDs of all active league participants.
    """

    with get_connection() as connection:

        users = connection.execute("""
            SELECT discord_id
            FROM users
            WHERE is_active = 1
            ORDER BY discord_id
        """).fetchall()

        return [user["discord_id"] for user in users]