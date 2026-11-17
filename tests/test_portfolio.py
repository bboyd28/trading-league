from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

import pytest

import core.database as database
import core.portfolio as portfolio

PLAYER = "123456789"


def register(discord_id=PLAYER, name="TestPlayer"):
    return portfolio.register_user(discord_id, name)


def buy(quantity, price, date="2026-11-13", symbol="AAPL", discord_id=PLAYER):
    return portfolio.buy_stock(
        discord_id, symbol, Decimal(quantity), Decimal(price), date
    )


def sell(quantity, price, date="2026-11-16", symbol="AAPL", discord_id=PLAYER):
    return portfolio.sell_stock(
        discord_id, symbol, Decimal(quantity), Decimal(price), date
    )


def fake_prices(monkeypatch, price_for):
    """Replace the stored-price lookup. price_for(symbol, date) -> (date, price)."""
    def lookup(symbols, target_date):
        found = {}
        for symbol in symbols:
            price_date, price = price_for(symbol, target_date)
            found[symbol] = {
                "symbol": symbol,
                "price_date": price_date,
                "price": Decimal(price),
            }
        return found

    monkeypatch.setattr(portfolio, "get_prices_on_or_before", lookup)


# ---- accounts ------------------------------------------------------------

def test_register_user(setup_database):
    user = register()

    assert user["discord_id"] == PLAYER
    assert user["username"] == "TestPlayer"
    assert user["cash_balance_cents"] == 10_000_000
    assert user["starting_balance_cents"] == 10_000_000
    assert user["is_new"] is True


def test_register_existing_user_keeps_balance(setup_database):
    register()
    buy("2", "100")

    user = register(name="UpdatedPlayer")

    assert user["username"] == "UpdatedPlayer"
    assert user["cash_balance_cents"] == 9_979_980
    assert user["is_new"] is False


def test_register_requires_id_and_name(setup_database):
    with pytest.raises(ValueError):
        portfolio.register_user("", "Nobody")


# ---- buying --------------------------------------------------------------

def test_buy_stock(setup_database):
    register()
    result = buy("2.5", "100")

    assert result["symbol"] == "AAPL"
    assert result["quantity"] == Decimal("2.5")
    assert result["gross_amount_cents"] == 25_000
    assert result["fee_cents"] == 25
    assert result["total_cost_cents"] == 25_025

    user = portfolio.get_portfolio(PLAYER)
    assert user["cash_balance"] == Decimal("99749.75")
    assert user["holdings"]["AAPL"] == Decimal("2.5")


def test_buy_stock_insufficient_funds(setup_database):
    register()

    with pytest.raises(ValueError, match="Insufficient funds"):
        buy("2000", "100")

    user = portfolio.get_portfolio(PLAYER)
    assert user["cash_balance"] == Decimal("100000")
    assert user["holdings"] == {}


def test_buy_rejects_tiny_trades(setup_database):
    register()

    with pytest.raises(ValueError, match="Minimum purchase"):
        buy("0.00001", "100")

    assert portfolio.get_portfolio(PLAYER)["holdings"] == {}


def test_buy_normalizes_symbol_and_rejects_bad_ones(setup_database):
    register()
    assert buy("1", "100", symbol=" aapl ")["symbol"] == "AAPL"

    with pytest.raises(ValueError, match="not a valid stock symbol"):
        buy("1", "100", symbol="^GSPC")


@pytest.mark.parametrize("bad", ["abc", "nan", "inf", ""])
def test_bad_numbers_raise_value_error(setup_database, bad):
    register()

    with pytest.raises(ValueError, match="must be a number"):
        portfolio.buy_stock(PLAYER, "AAPL", bad, Decimal("100"), "2026-11-13")


def test_unknown_user_cannot_trade(setup_database):
    with pytest.raises(ValueError, match="does not exist"):
        buy("1", "100")


def test_buy_stock_by_amount(setup_database):
    register()
    result = portfolio.buy_stock_by_amount(
        PLAYER, "AAPL", Decimal("500"), Decimal("200"), "2026-11-16"
    )

    assert result["quantity"] == Decimal("2.5")
    assert result["gross_amount_cents"] == 50_000
    assert result["fee_cents"] == 50
    assert result["total_cost_cents"] == 50_050

    user = portfolio.get_portfolio(PLAYER)
    assert user["cash_balance"] == Decimal("99499.50")


def test_buy_by_amount_rounds_shares_down(setup_database):
    register()
    result = portfolio.buy_stock_by_amount(
        PLAYER, "AAPL", Decimal("100"), Decimal("3"), "2026-11-16"
    )

    assert result["quantity"] == Decimal("33.33333333")


def test_concurrent_buys_cannot_overdraw(setup_database):
    """Two buys that each fit alone, but not together, must not both succeed."""
    register()

    def attempt(_):
        try:
            buy("550", "100")   # $55,000 + fee, cash is $100,000
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))

    assert results.count(True) == 1
    assert portfolio.get_portfolio(PLAYER)["cash_balance"] >= 0
    assert portfolio.find_cash_mismatches() == []


# ---- selling -------------------------------------------------------------

def test_sell_stock(setup_database):
    register()
    buy("2.5", "100")
    result = sell("1", "110", date="2026-11-15")

    assert result["gross_amount_cents"] == 11_000
    assert result["fee_cents"] == 11
    assert result["net_proceeds_cents"] == 10_989

    user = portfolio.get_portfolio(PLAYER)
    assert user["cash_balance"] == Decimal("99859.64")
    assert user["holdings"]["AAPL"] == Decimal("1.5")


def test_sell_stock_insufficient_shares(setup_database):
    register()
    buy("1.5", "100")

    with pytest.raises(ValueError, match="Insufficient shares"):
        sell("2", "110")

    user = portfolio.get_portfolio(PLAYER)
    assert user["cash_balance"] == Decimal("99849.85")
    assert user["holdings"]["AAPL"] == Decimal("1.5")


def test_sell_all_shares(setup_database):
    register()
    buy("2", "100")
    sell("2", "110")

    assert portfolio.get_portfolio(PLAYER)["holdings"] == {}


def test_sell_none_sells_whole_position(setup_database):
    register()
    buy("2.5", "100")
    result = portfolio.sell_stock(PLAYER, "AAPL", None, Decimal("100"), "2026-11-16")

    assert result["quantity"] == Decimal("2.5")
    assert portfolio.get_portfolio(PLAYER)["holdings"] == {}


def test_sell_without_owning_anything(setup_database):
    register()

    with pytest.raises(ValueError, match="do not own any shares"):
        sell("1", "100")


def test_sell_stock_by_amount(setup_database):
    register()
    buy("5", "100", date="2026-11-14")
    result = portfolio.sell_stock_by_amount(
        PLAYER, "AAPL", Decimal("200"), Decimal("110"), "2026-11-15"
    )

    assert result["gross_amount_cents"] == 20_000
    assert result["fee_cents"] == 20
    assert result["net_proceeds_cents"] == 19_980

    user = portfolio.get_portfolio(PLAYER)
    assert user["holdings"]["AAPL"] < Decimal("5")
    assert user["cash_balance"] == Decimal("99699.30")


def test_sell_stock_by_amount_insufficient_shares(setup_database):
    register()
    buy("2", "100", date="2026-11-14")

    with pytest.raises(ValueError, match="Insufficient shares"):
        portfolio.sell_stock_by_amount(
            PLAYER, "AAPL", Decimal("500"), Decimal("110"), "2026-11-15"
        )

    assert portfolio.get_portfolio(PLAYER)["holdings"]["AAPL"] == Decimal("2")


def test_partial_sale_that_rounds_to_zero_is_rejected(setup_database):
    register()
    buy("2", "100")

    with pytest.raises(ValueError, match="too small"):
        sell("0.00001", "100")


def test_multiple_stock_holdings(setup_database):
    register()
    buy("2", "100", date="2026-11-14")
    buy("3", "200", date="2026-11-14", symbol="MSFT")
    sell("0.5", "110", date="2026-11-15")

    holdings = portfolio.get_portfolio(PLAYER)["holdings"]
    assert holdings["AAPL"] == Decimal("1.5")
    assert holdings["MSFT"] == Decimal("3")


# ---- ledger checks and history -------------------------------------------

def test_cash_matches_ledger_after_trading(setup_database):
    register()
    buy("2", "100")
    sell("1", "120", date="2026-11-14")

    assert portfolio.find_cash_mismatches() == []


def test_cash_mismatch_is_detected(setup_database):
    register()

    with database.get_connection(write=True) as connection:
        connection.execute("UPDATE users SET cash_balance_cents = 5")

    mismatches = portfolio.find_cash_mismatches()
    assert mismatches[0]["discord_id"] == PLAYER
    assert mismatches[0]["expected_cents"] == 10_000_000


def test_recent_trades_newest_first(setup_database):
    register()
    buy("1", "100", date="2026-11-12")
    buy("1", "100", date="2026-11-13", symbol="MSFT")

    trades = portfolio.get_recent_trades(PLAYER)
    assert [t["symbol"] for t in trades] == ["MSFT", "AAPL"]


def test_get_active_symbols(setup_database):
    register("111", "Alice")
    register("222", "Bob")

    buy("5", "100", symbol="AAPL", discord_id="111")
    buy("2", "100", symbol="MSFT", discord_id="111")
    sell("2", "100", symbol="MSFT", discord_id="111")
    buy("3", "100", symbol="AAPL", discord_id="222")
    buy("1", "100", symbol="NVDA", discord_id="222")

    assert portfolio.get_active_symbols() == ["AAPL", "NVDA"]


def test_get_active_users(setup_database):
    register("111", "Alice")
    register("222", "Bob")

    with database.get_connection(write=True) as connection:
        connection.execute("UPDATE users SET is_active = 0 WHERE discord_id = '222'")

    assert portfolio.get_active_users() == ["111"]


def test_historical_valuation(setup_database, monkeypatch):
    """Only trades on or before the target date count."""
    register()
    buy("2", "100", date="2026-11-14")
    fake_prices(monkeypatch, lambda s, d: ("2026-11-13", "110"))

    earlier = portfolio.get_historical_valued_portfolio(PLAYER, "2026-11-13")
    assert earlier["cash_balance"] == Decimal("100000")
    assert earlier["holdings"] == {}
    assert earlier["total_value"] == Decimal("100000")

    later = portfolio.get_historical_valued_portfolio(PLAYER, "2026-11-14")
    assert later["cash_balance"] == Decimal("99799.80")
    assert later["holdings"]["AAPL"]["quantity"] == Decimal("2")
    assert later["holdings"]["AAPL"]["price"] == Decimal("110")
    assert later["holdings_value"] == Decimal("220")
    assert later["total_value"] == Decimal("100019.80")


def test_historical_valuation_after_sale(setup_database, monkeypatch):
    register()
    buy("4", "100", date="2026-11-13")
    sell("1", "120", date="2026-11-14")
    closes = {"2026-11-13": "110", "2026-11-14": "125"}
    fake_prices(monkeypatch, lambda s, d: (d, closes[d]))

    before = portfolio.get_historical_valued_portfolio(PLAYER, "2026-11-13")
    assert before["holdings"]["AAPL"]["quantity"] == Decimal("4")
    assert before["cash_balance"] == Decimal("99599.60")
    assert before["total_value"] == Decimal("100039.60")

    after = portfolio.get_historical_valued_portfolio(PLAYER, "2026-11-14")
    assert after["holdings"]["AAPL"]["quantity"] == Decimal("3")
    assert after["cash_balance"] == Decimal("99719.48")
    assert after["holdings_value"] == Decimal("375")
    assert after["total_value"] == Decimal("100094.48")


def test_historical_valuation_multiple_stocks(setup_database, monkeypatch):
    register()
    buy("2", "100", symbol="AAPL")
    buy("3", "200", symbol="MSFT")
    closes = {"AAPL": "110", "MSFT": "190"}
    fake_prices(monkeypatch, lambda s, d: (d, closes[s]))

    result = portfolio.get_historical_valued_portfolio(PLAYER, "2026-11-13")

    assert result["holdings"]["AAPL"]["market_value"] == Decimal("220")
    assert result["holdings"]["MSFT"]["market_value"] == Decimal("570")
    assert result["holdings_value"] == Decimal("790")
    assert result["cash_balance"] == Decimal("99199.20")
    assert result["total_value"] == Decimal("99989.20")


def test_exact_price_required_for_snapshots(setup_database, monkeypatch):
    register()
    buy("2", "100", date="2026-11-13")
    fake_prices(monkeypatch, lambda s, d: ("2026-11-12", "110"))   # one day old

    with pytest.raises(ValueError, match="No AAPL close for 2026-11-13"):
        portfolio.save_portfolio_snapshot(
            PLAYER, "2026-11-13", require_exact_prices=True
        )


# ---- snapshots -----------------------------------------------------------

def test_save_portfolio_snapshot(setup_database, monkeypatch):
    register()
    buy("2", "100", date="2026-11-14")
    fake_prices(monkeypatch, lambda s, d: ("2026-11-13", "110"))

    result = portfolio.save_portfolio_snapshot(PLAYER, "2026-11-14")

    assert result["cash_balance"] == Decimal("99799.80")
    assert result["holdings_value"] == Decimal("220")
    assert result["total_value"] == Decimal("100019.80")


def test_snapshot_saves_position_rows(setup_database, monkeypatch):
    register()
    buy("2", "100", date="2026-11-14")
    fake_prices(monkeypatch, lambda s, d: ("2026-11-14", "110"))

    portfolio.save_portfolio_snapshot(PLAYER, "2026-11-14")

    with database.get_connection() as connection:
        rows = connection.execute("SELECT * FROM position_snapshots").fetchall()

    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["market_value_cents"] == 22_000


def test_saving_again_recalculates_without_duplicating(setup_database, monkeypatch):
    register()
    buy("2", "100", date="2026-11-14")

    fake_prices(monkeypatch, lambda s, d: ("2026-11-14", "110"))
    portfolio.save_portfolio_snapshot(PLAYER, "2026-11-14")

    fake_prices(monkeypatch, lambda s, d: ("2026-11-14", "120"))
    result = portfolio.save_portfolio_snapshot(PLAYER, "2026-11-14")

    assert result["holdings_value"] == Decimal("240")
    assert result["total_value"] == Decimal("100039.80")

    with database.get_connection() as connection:
        snapshots = connection.execute("SELECT * FROM portfolio_snapshots").fetchall()
        positions = connection.execute("SELECT * FROM position_snapshots").fetchall()

    assert len(snapshots) == 1
    assert len(positions) == 1
