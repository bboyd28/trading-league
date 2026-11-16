
import discord
from discord import app_commands
from discord.ext import commands
from decimal import Decimal
from datetime import date

from core.portfolio import (
    get_valued_portfolio,
    register_user,
    get_portfolio,
    buy_stock,
    buy_stock_by_amount,
    sell_stock,
    sell_stock_by_amount
)
from core.leaderboard import get_leaderboard
from core.prices import get_or_update_price


class TradingCommands(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="portfolio",
        description="View your current trading portfolio."
    )
    async def portfolio(self, interaction: discord.Interaction):

        discord_id = str(interaction.user.id)

        try:
            result = get_valued_portfolio(discord_id)

        except ValueError as error:
            await interaction.response.send_message(
                f"Could not retrieve your portfolio: {error}",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"{result['username']}'s Portfolio",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="Cash Balance",
            value=f"${result['cash_balance']:,.2f}",
            inline=True
        )

        embed.add_field(
            name="Holdings Value",
            value=f"${result['holdings_value']:,.2f}",
            inline=True
        )

        embed.add_field(
            name="Total Portfolio Value",
            value=f"${result['total_value']:,.2f}",
            inline=False
        )

        holdings_text = ""

        for symbol, holding in result["holdings"].items():
            holdings_text += (
                f"**{symbol}** — "
                f"{holding['quantity']:,.4f} shares\n"
                f"Price: ${holding['price']:,.2f} | "
                f"Value: ${holding['market_value']:,.2f}\n\n"
            )

        if not holdings_text:
            holdings_text = "You currently have no stock holdings."

        embed.add_field(
            name="Holdings",
            value=holdings_text,
            inline=False
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="leaderboard",
        description="View the trading league standings."
    )
    async def leaderboard(self, interaction: discord.Interaction):

        snapshot_date = date.today().isoformat()

        results = get_leaderboard(snapshot_date)

        if not results:
            await interaction.response.send_message(
                "No leaderboard data is available for today yet.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Trading League Leaderboard",
            description=f"Standings for {snapshot_date}",
            color=discord.Color.gold()
        )

        leaderboard_text = ""

        for player in results:
            leaderboard_text += (
                f"**#{player['rank']} — {player['username']}**\n"
                f"${player['total_value']:,.2f} "
                f"({player['return_percentage']:+.2f}%)\n\n"
            )

        embed.description = leaderboard_text

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="register",
        description="Join the trading league."
    )
    async def register(self, interaction: discord.Interaction):

        discord_id = str(interaction.user.id)
        username = interaction.user.name

        try:
            register_user(discord_id, username)
            portfolio = get_portfolio(discord_id)

        except (ValueError, RuntimeError) as error:
            await interaction.response.send_message(
                f"Registration unsuccessful: {error}",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Welcome to the Trading League!",
            description=(
                f"You're registered as **{username}**.\n\n"
                f"Your current cash balance is "
                f"**${portfolio['cash_balance']:,.2f}**."
            ),
            color=discord.Color.green()
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    @app_commands.command(
        name="buy",
        description="Purchase shares of a stock."
    )
    async def buy(
        self,
        interaction: discord.Interaction,
        symbol: str,
        quantity: float
    ):

        discord_id = str(interaction.user.id)
        symbol = symbol.upper().strip()

        try:
            price_data = get_or_update_price(
                symbol,
                date.today().isoformat()
            )

            result = buy_stock(
                discord_id,
                symbol,
                Decimal(str(quantity)),
                price_data["price"],
                price_data["price_date"]
            )

        except (ValueError, RuntimeError) as error:
            await interaction.response.send_message(
                f"Purchase unsuccessful: {error}",
                ephemeral=True
            )
            return

        total_cost = result["total_cost_cents"] / 100
        fee = result["fee_cents"] / 100

        embed = discord.Embed(
            title="Purchase Successful",
            color=discord.Color.green()
        )

        embed.add_field(
            name="Stock",
            value=result["symbol"],
            inline=True
        )

        embed.add_field(
            name="Shares Purchased",
            value=f"{result['quantity']:,.4f}",
            inline=True
        )

        embed.add_field(
            name="Price Per Share",
            value=f"${result['price_per_share']:,.2f}",
            inline=True
        )

        embed.add_field(
            name="Transaction Fee",
            value=f"${fee:,.2f}",
            inline=True
        )

        embed.add_field(
            name="Total Cost",
            value=f"${total_cost:,.2f}",
            inline=True
        )

        embed.set_footer(
            text=f"Execution price from {price_data['price_date']}"
        )

        await interaction.response.send_message(embed=embed)


    @app_commands.command(
        name="buy-amount",
        description="Purchase stock using a dollar amount."
    )
    async def buy_amount(
        self,
        interaction: discord.Interaction,
        symbol: str,
        amount: float
    ):

        discord_id = str(interaction.user.id)
        symbol = symbol.upper().strip()

        try:
            price_data = get_or_update_price(
                symbol,
                date.today().isoformat()
            )

            result = buy_stock_by_amount(
                discord_id,
                symbol,
                Decimal(str(amount)),
                price_data["price"],
                price_data["price_date"]
            )

        except (ValueError, RuntimeError) as error:
            await interaction.response.send_message(
                f"Purchase unsuccessful: {error}",
                ephemeral=True
            )
            return

        total_cost = result["total_cost_cents"] / 100
        fee = result["fee_cents"] / 100
        gross_amount = result["gross_amount_cents"] / 100

        embed = discord.Embed(
            title="Purchase Successful",
            color=discord.Color.green()
        )

        embed.add_field(
            name="Stock",
            value=result["symbol"],
            inline=True
        )

        embed.add_field(
            name="Shares Purchased",
            value=f"{result['quantity']:,.4f}",
            inline=True
        )

        embed.add_field(
            name="Price Per Share",
            value=f"${result['price_per_share']:,.2f}",
            inline=True
        )

        embed.add_field(
            name="Stock Purchase",
            value=f"${gross_amount:,.2f}",
            inline=True
        )

        embed.add_field(
            name="Transaction Fee",
            value=f"${fee:,.2f}",
            inline=True
        )

        embed.add_field(
            name="Total Cost",
            value=f"${total_cost:,.2f}",
            inline=True
        )

        embed.set_footer(
            text=f"Execution price from {price_data['price_date']}"
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
    name="sell",
    description="Sell a specific number of shares or your entire position."
    )
    @app_commands.describe(
    quantity="Number of shares to sell, or 'all' to sell your entire position."

    )
    async def sell(
        self,
        interaction: discord.Interaction,
        symbol: str,
        quantity: str
    ):
        discord_id = str(interaction.user.id)
        symbol = symbol.upper().strip()
        quantity = quantity.strip().lower()

        try:
            if quantity != "all":
                quantity = Decimal(quantity)

            price_data = get_or_update_price(
                symbol,
                date.today().isoformat()
            )

            result = sell_stock(
                discord_id,
                symbol,
                quantity,
                price_data["price"],
                price_data["price_date"]
            )

        except (ValueError, RuntimeError) as error:
            await interaction.response.send_message(
                f"Sale unsuccessful: {error}",
                ephemeral=True
            )
            return

        gross_proceeds = result["gross_amount_cents"] / 100
        fee = result["fee_cents"] / 100
        net_proceeds = result["net_proceeds_cents"] / 100

        embed = discord.Embed(
            title="Sale Successful",
            color=discord.Color.green()
        )

        embed.add_field(name="Stock", value=result["symbol"], inline=True)
        embed.add_field(
            name="Shares Sold",
            value=f"{result['quantity']:,.8f}",
            inline=True
        )
        embed.add_field(
            name="Price Per Share",
            value=f"${result['price_per_share']:,.2f}",
            inline=True
        )
        embed.add_field(
            name="Gross Proceeds",
            value=f"${gross_proceeds:,.2f}",
            inline=True
        )
        embed.add_field(
            name="Transaction Fee",
            value=f"${fee:,.2f}",
            inline=True
        )
        embed.add_field(
            name="Net Proceeds",
            value=f"${net_proceeds:,.2f}",
            inline=True
        )

        embed.set_footer(
            text=f"Execution price from {price_data['price_date']}"
        )

        await interaction.response.send_message(embed=embed)


    @app_commands.command(
        name="sell-amount",
        description="Sell stock using a dollar amount."
    )
    async def sell_amount(
        self,
        interaction: discord.Interaction,
        symbol: str,
        amount: float
    ):
        discord_id = str(interaction.user.id)
        symbol = symbol.upper().strip()

        try:
            price_data = get_or_update_price(
                symbol,
                date.today().isoformat()
            )

            result = sell_stock_by_amount(
                discord_id,
                symbol,
                Decimal(str(amount)),
                price_data["price"],
                price_data["price_date"]
            )

        except (ValueError, RuntimeError) as error:
            await interaction.response.send_message(
                f"Sale unsuccessful: {error}",
                ephemeral=True
            )
            return

        gross_proceeds = result["gross_amount_cents"] / 100
        fee = result["fee_cents"] / 100
        net_proceeds = result["net_proceeds_cents"] / 100

        embed = discord.Embed(
            title="Sale Successful",
            color=discord.Color.green()
        )

        embed.add_field(
            name="Stock",
            value=result["symbol"],
            inline=True
        )

        embed.add_field(
            name="Shares Sold",
            value=f"{result['quantity']:,.8f}",
            inline=True
        )

        embed.add_field(
            name="Price Per Share",
            value=f"${result['price_per_share']:,.2f}",
            inline=True
        )

        embed.add_field(
            name="Gross Proceeds",
            value=f"${gross_proceeds:,.2f}",
            inline=True
        )

        embed.add_field(
            name="Transaction Fee",
            value=f"${fee:,.2f}",
            inline=True
        )

        embed.add_field(
            name="Net Proceeds",
            value=f"${net_proceeds:,.2f}",
            inline=True
        )

        embed.set_footer(
            text=f"Execution price from {price_data['price_date']}"
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(TradingCommands(bot))
