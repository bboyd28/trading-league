"""Smoke tests for the Discord layer, using fake interactions."""
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot import commands as bot_commands
from bot import embeds
from core import execution

DISCORD_ID = "123"


def make_interaction():
    interaction = MagicMock()
    interaction.user.id = int(DISCORD_ID)
    interaction.user.name = "Tester"
    interaction.response.defer = AsyncMock()
    interaction.response.is_done.return_value = True
    interaction.edit_original_response = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def call(command, interaction, *args):
    cog = bot_commands.TradingCommands(bot=MagicMock())
    return asyncio.run(command.callback(cog, interaction, *args))


FILL = {
    "symbol": "AAPL", "side": "BUY", "quantity": Decimal("2"),
    "price_per_share": Decimal("100"), "gross_amount_cents": 20_000,
    "fee_cents": 20, "cash_change_cents": 20_020, "price_date": "2026-11-16",
    "filled_live": False,
}


def test_buy_defers_then_shows_the_fill(monkeypatch):
    seen = {}

    def fake_order(discord_id, symbol, side, **amounts):
        seen.update(discord_id=discord_id, symbol=symbol, side=side, **amounts)
        return FILL

    monkeypatch.setattr(execution, "place_order", fake_order)
    interaction = make_interaction()

    call(bot_commands.TradingCommands.buy, interaction, "aapl", "2")

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    assert seen == {"discord_id": DISCORD_ID, "symbol": "aapl", "side": "BUY", "quantity": "2"}
    embed = interaction.edit_original_response.await_args.kwargs["embed"]
    assert embed.title == "Purchase complete"


def test_user_errors_are_shown_not_raised(monkeypatch):
    def refuse(*args, **kwargs):
        raise ValueError("Insufficient funds.")

    monkeypatch.setattr(execution, "place_order", refuse)
    interaction = make_interaction()

    call(bot_commands.TradingCommands.buy, interaction, "AAPL", "9999")

    interaction.edit_original_response.assert_awaited_once_with(content="Insufficient funds.")


def test_sell_amount_passes_the_amount(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        execution, "place_order",
        lambda discord_id, symbol, side, **amounts: seen.update(side=side, **amounts) or FILL,
    )

    call(bot_commands.TradingCommands.sell_amount, make_interaction(), "AAPL", "200")

    assert seen == {"side": "SELL", "amount": "200"}


def test_leaderboard_with_no_data_says_so(monkeypatch):
    monkeypatch.setattr(bot_commands, "get_standings", lambda period: None)
    interaction = make_interaction()

    call(bot_commands.TradingCommands.leaderboard, interaction, None)

    content = interaction.edit_original_response.await_args.kwargs["content"]
    assert "No standings yet" in content


def test_leaderboard_error_is_not_overwritten(monkeypatch):
    def broken(period):
        raise RuntimeError("League settings have not been initialized.")

    monkeypatch.setattr(bot_commands, "get_standings", broken)
    interaction = make_interaction()

    call(bot_commands.TradingCommands.leaderboard, interaction, None)

    interaction.edit_original_response.assert_awaited_once_with(
        content="League settings have not been initialized."
    )


def test_error_handler_reports_cooldowns():
    from discord import app_commands

    interaction = make_interaction()
    error = app_commands.CommandOnCooldown(app_commands.Cooldown(1, 3.0), 2.0)

    asyncio.run(bot_commands.on_app_command_error(interaction, error))

    message = interaction.followup.send.await_args.args[0]
    assert "Slow down" in message


# ---- embeds --------------------------------------------------------------

def test_fit_lines_truncates_with_a_count():
    lines = ["x" * 100 for _ in range(30)]

    text = embeds.fit_lines(lines, 1024)

    assert len(text) <= 1024
    assert text.endswith("more")


def test_fit_lines_keeps_everything_when_it_fits():
    assert embeds.fit_lines(["a", "b"], 100) == "a\nb"


def test_portfolio_embed_stays_inside_discord_limits():
    holdings = {
        f"SYM{i}": {"quantity": Decimal("10"), "price": Decimal("123.45"),
                    "price_date": "2026-11-16", "live": False,
                    "market_value": Decimal("1234.50")}
        for i in range(40)
    }
    result = {"username": "Tester", "cash_balance": Decimal("1000"),
              "holdings_value": Decimal("49380"), "total_value": Decimal("50380"),
              "holdings": holdings}

    embed = embeds.portfolio_embed(result)

    assert all(len(field.value) <= 1024 for field in embed.fields)


def test_stats_embed_handles_missing_values():
    summary = {
        "start_date": "2026-11-10", "end_date": "2026-11-13", "observations": 3,
        "total_return_pct": Decimal("1.5"), "volatility_pct": None, "sharpe": None,
        "max_drawdown_pct": Decimal("-2"), "beta": None,
        "benchmark_return_pct": None, "excess_return_pct": None,
    }

    embed = embeds.stats_embed("Tester", summary)

    assert "need more history" in embed.footer.text
    assert {f.name: f.value for f in embed.fields}["Sharpe"] == "n/a"


@pytest.mark.parametrize("quantity, shown", [
    (Decimal("10"), "10"), (Decimal("2.5"), "2.5"), (Decimal("33.33333333"), "33.3333"),
])
def test_share_formatting(quantity, shown):
    assert embeds.shares(quantity) == shown


def test_trade_embed_says_when_the_fill_was_live():
    live = embeds.trade_embed({**FILL, "filled_live": True})
    closed = embeds.trade_embed(FILL)

    assert live.footer.text == "Filled at the live price"
    assert closed.footer.text == "Filled at the 2026-11-16 close"


def test_portfolio_embed_footer_shows_live_prices():
    holding = {"quantity": Decimal("1"), "price": Decimal("100"), "price_date": "2026-11-16",
               "live": True, "market_value": Decimal("100")}
    result = {"username": "Tester", "cash_balance": Decimal("0"), "holdings_value": Decimal("100"),
              "total_value": Decimal("100"), "holdings": {"AAPL": holding}}

    assert "Live prices" in embeds.portfolio_embed(result).footer.text


def test_admin_mode_switches_the_pricing_model(monkeypatch):
    from discord import app_commands

    chosen = []
    monkeypatch.setattr(execution, "set_execution_model", chosen.append)
    interaction = make_interaction()
    choice = app_commands.Choice(name="Live quotes during the session", value="live_quote")

    call(bot_commands.TradingCommands.admin_mode, interaction, choice)

    assert chosen == ["live_quote"]
    interaction.edit_original_response.assert_awaited_once_with(
        content="Trades now use: Live quotes during the session."
    )


def test_admin_mode_reports_a_bad_value(monkeypatch):
    from discord import app_commands

    def refuse(model):
        raise ValueError("Model must be one of: any_time, daily_close, live_quote.")

    monkeypatch.setattr(execution, "set_execution_model", refuse)
    interaction = make_interaction()

    call(bot_commands.TradingCommands.admin_mode, interaction,
         app_commands.Choice(name="x", value="x"))

    assert "Model must be one of" in interaction.edit_original_response.await_args.kwargs["content"]
