"""Slash commands. Each one hands the real work to core/ in a worker thread."""
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot import embeds
from core import analytics, execution, portfolio
from core.leaderboard import get_standings
from core.market_updates import run_daily_market_update

logger = logging.getLogger(__name__)

# Trade confirmations are private by default. Set True to show them in the channel.
TRADES_PUBLIC = False

trade_cooldown = app_commands.checks.cooldown(1, 3.0, key=lambda i: i.user.id)

# Returned by run_blocking after it has already told the user what went wrong.
FAILED = object()


async def run_blocking(interaction, func, *args, public=True, **kwargs):
    """Defer, run func off the event loop, and report user errors in place.

    Returns FAILED if the user hit a ValueError or RuntimeError.
    """
    await interaction.response.defer(ephemeral=not public)

    try:
        return await asyncio.to_thread(func, *args, **kwargs)
    except (ValueError, RuntimeError) as error:
        await interaction.edit_original_response(content=str(error))
        return FAILED


class TradingCommands(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="register", description="Join the trading league.")
    async def register(self, interaction: discord.Interaction):
        user = await run_blocking(
            interaction, execution.register,
            str(interaction.user.id), interaction.user.name, public=False,
        )
        if user is FAILED:
            return

        await interaction.edit_original_response(
            embed=embeds.welcome_embed(user["username"], user["cash_balance_cents"] / 100)
        )

    @app_commands.command(name="portfolio", description="View your portfolio.")
    async def portfolio(self, interaction: discord.Interaction):
        def load():
            live = execution.live_prices_enabled()
            return portfolio.get_valued_portfolio(str(interaction.user.id), live=live)

        result = await run_blocking(interaction, load)
        if result is not FAILED:
            await interaction.edit_original_response(embed=embeds.portfolio_embed(result))

    async def _trade(self, interaction, symbol, side, **amounts):
        result = await run_blocking(
            interaction, execution.place_order,
            str(interaction.user.id), symbol, side,
            public=TRADES_PUBLIC, **amounts,
        )
        if result is not FAILED:
            await interaction.edit_original_response(embed=embeds.trade_embed(result))

    @app_commands.command(name="buy", description="Buy shares of a stock.")
    @app_commands.describe(symbol="Ticker, like AAPL", quantity="Number of shares, like 2.5")
    @trade_cooldown
    async def buy(self, interaction: discord.Interaction, symbol: str, quantity: str):
        await self._trade(interaction, symbol, "BUY", quantity=quantity)

    @app_commands.command(name="buy-amount", description="Buy a dollar amount of a stock.")
    @app_commands.describe(symbol="Ticker, like AAPL", amount="Dollars to spend before the fee")
    @trade_cooldown
    async def buy_amount(self, interaction: discord.Interaction, symbol: str, amount: str):
        await self._trade(interaction, symbol, "BUY", amount=amount)

    @app_commands.command(name="sell", description="Sell shares, or your whole position.")
    @app_commands.describe(symbol="Ticker, like AAPL", quantity="Number of shares, or 'all'")
    @trade_cooldown
    async def sell(self, interaction: discord.Interaction, symbol: str, quantity: str):
        await self._trade(interaction, symbol, "SELL", quantity=quantity)

    @app_commands.command(name="sell-amount", description="Sell a dollar amount of a stock.")
    @app_commands.describe(symbol="Ticker, like AAPL", amount="Dollars to raise before the fee")
    @trade_cooldown
    async def sell_amount(self, interaction: discord.Interaction, symbol: str, amount: str):
        await self._trade(interaction, symbol, "SELL", amount=amount)

    @app_commands.command(name="leaderboard", description="See the league standings.")
    @app_commands.describe(period="Which standings to show")
    @app_commands.choices(period=[
        app_commands.Choice(name="All time", value="all"),
        app_commands.Choice(name="Past week", value="week"),
        app_commands.Choice(name="Past month", value="month"),
    ])
    async def leaderboard(self, interaction: discord.Interaction,
                          period: app_commands.Choice[str] = None):
        standings = await run_blocking(
            interaction, get_standings, period.value if period else "all"
        )
        if standings is FAILED:
            return

        if standings is None:
            await interaction.edit_original_response(
                content="No standings yet. Snapshots are saved after each market close."
            )
        else:
            await interaction.edit_original_response(embed=embeds.leaderboard_embed(standings))

    @app_commands.command(name="stats", description="Your return, risk, and beta vs SPY.")
    async def stats(self, interaction: discord.Interaction):
        discord_id = str(interaction.user.id)

        def load():
            portfolio.get_portfolio(discord_id)   # raises if not registered
            return analytics.get_performance_summary(discord_id)

        summary = await run_blocking(interaction, load)
        if summary is FAILED:
            return

        if summary is None:
            await interaction.edit_original_response(
                content="Not enough history yet. Stats start after your second daily snapshot."
            )
        else:
            await interaction.edit_original_response(
                embed=embeds.stats_embed(interaction.user.name, summary)
            )

    @app_commands.command(name="trades", description="Your 10 most recent trades.")
    async def trades(self, interaction: discord.Interaction):
        trades = await run_blocking(
            interaction, portfolio.get_recent_trades, str(interaction.user.id), public=False
        )
        if trades is not FAILED:
            await interaction.edit_original_response(
                embed=embeds.trades_embed(interaction.user.name, trades)
            )

    @app_commands.command(name="admin-update", description="Run the daily price and snapshot job now.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_update(self, interaction: discord.Interaction):
        result = await run_blocking(interaction, run_daily_market_update, public=False)
        if result is FAILED:
            return

        text = (
            f"{result['snapshot_date']} was not a trading day. Nothing saved."
            if result["skipped"] else
            f"Snapshots saved for {len(result['snapshots_saved'])} players on "
            f"{result['snapshot_date']}.\n"
            f"Price failures: {result['price_updates']['failed'] or 'none'}\n"
            f"Snapshot failures: {result['snapshot_failures'] or 'none'}"
        )
        await interaction.edit_original_response(content=text)

    @app_commands.command(name="admin-mode", description="Choose how trades are priced.")
    @app_commands.describe(model="Pricing model")
    @app_commands.choices(model=[
        app_commands.Choice(name="Live quotes during the session", value="live_quote"),
        app_commands.Choice(name="Last close, market closed only", value="daily_close"),
        app_commands.Choice(name="Last close, any time (testing)", value="any_time"),
    ])
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_mode(self, interaction: discord.Interaction,
                         model: app_commands.Choice[str]):
        done = await run_blocking(
            interaction, execution.set_execution_model, model.value, public=False
        )
        if done is not FAILED:
            await interaction.edit_original_response(content=f"Trades now use: {model.name}.")

    @app_commands.command(name="admin-check", description="Check that cash matches the trade ledger.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_check(self, interaction: discord.Interaction):
        mismatches = await run_blocking(
            interaction, portfolio.find_cash_mismatches, public=False
        )
        if mismatches is FAILED:
            return

        text = "Every balance matches the ledger." if not mismatches else "\n".join(
            f"{m['username']}: stored ${m['stored_cents'] / 100:,.2f}, "
            f"ledger says ${m['expected_cents'] / 100:,.2f}"
            for m in mismatches
        )
        await interaction.edit_original_response(content=text)


async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CommandOnCooldown):
        message = f"Slow down. Try again in {error.retry_after:.0f} seconds."
    elif isinstance(error, app_commands.MissingPermissions):
        message = "Only server admins can use that command."
    else:
        logger.exception("Unhandled command error", exc_info=error)
        message = "Something went wrong on my end. Try again in a moment."

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def setup(bot):
    bot.tree.on_error = on_app_command_error
    await bot.add_cog(TradingCommands(bot))
