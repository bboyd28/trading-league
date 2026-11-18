"""Builds the Discord embeds. No database or network calls in here."""
from decimal import Decimal

import discord

FIELD_LIMIT = 1024
DESCRIPTION_LIMIT = 4096


def money(amount):
    return f"${amount:,.2f}"


def shares(quantity):
    return f"{quantity:,.4f}".rstrip("0").rstrip(".")


def percent(value, signed=False):
    if value is None:
        return "n/a"
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


def number(value):
    return "n/a" if value is None else f"{value:.2f}"


def fit_lines(lines, limit, separator="\n"):
    """Join lines, stopping before the Discord size limit."""
    kept = []
    used = 0

    for position, line in enumerate(lines):
        remaining = len(lines) - position
        note = f"{separator}...and {remaining} more"

        if used + len(line) + len(separator) + len(note) > limit:
            return separator.join(kept) + note if kept else note.strip()

        kept.append(line)
        used += len(line) + len(separator)

    return separator.join(kept)


def portfolio_embed(result):
    embed = discord.Embed(
        title=f"{result['username']}'s Portfolio",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Cash", value=money(result["cash_balance"]))
    embed.add_field(name="Holdings", value=money(result["holdings_value"]))
    embed.add_field(name="Total", value=money(result["total_value"]), inline=False)

    lines = [
        f"**{symbol}**: {shares(h['quantity'])} shares at {money(h['price'])} "
        f"= {money(h['market_value'])}"
        for symbol, h in result["holdings"].items()
    ]
    embed.add_field(
        name="Positions",
        value=fit_lines(lines, FIELD_LIMIT) or "No stock holdings yet.",
        inline=False,
    )

    positions = result["holdings"].values()
    if any(h["live"] for h in positions):
        embed.set_footer(text="Live prices (IEX quotes)")
    elif positions:
        embed.set_footer(text=f"Prices as of {max(h['price_date'] for h in positions)} close")

    return embed


def trade_embed(result):
    bought = result["side"] == "BUY"
    embed = discord.Embed(
        title="Purchase complete" if bought else "Sale complete",
        color=discord.Color.green(),
    )
    embed.add_field(name="Stock", value=result["symbol"])
    embed.add_field(name="Shares", value=shares(result["quantity"]))
    embed.add_field(name="Price", value=money(result["price_per_share"]))
    embed.add_field(name="Amount", value=money(result["gross_amount_cents"] / 100))
    embed.add_field(name="Fee", value=money(result["fee_cents"] / 100))
    embed.add_field(
        name="Total cost" if bought else "Net proceeds",
        value=money(result["cash_change_cents"] / 100),
    )
    if result["filled_live"]:
        embed.set_footer(text="Filled at the live price")
    else:
        embed.set_footer(text=f"Filled at the {result['price_date']} close")
    return embed


def welcome_embed(username, cash_balance):
    return discord.Embed(
        title="Welcome to the Trading League!",
        description=f"You're in as **{username}** with {money(cash_balance)} to trade.",
        color=discord.Color.green(),
    )


TITLES = {"all": "All-time standings", "week": "Past week", "month": "Past month"}


def leaderboard_embed(standings):
    lines = [
        f"**#{row['rank']} {row['username']}**\n"
        f"{money(row['total_value'])} ({percent(row['return_percentage'], signed=True)})"
        for row in standings["rows"]
    ]
    return discord.Embed(
        title=f"Trading League: {TITLES[standings['period']]}",
        description=fit_lines(lines, DESCRIPTION_LIMIT, "\n\n") or "No players yet.",
        color=discord.Color.gold(),
    ).set_footer(text=f"As of {standings['as_of']} close")


def stats_embed(username, summary):
    embed = discord.Embed(title=f"{username}'s Stats", color=discord.Color.blurple())
    embed.add_field(name="Return", value=percent(summary["total_return_pct"], signed=True))
    embed.add_field(name="SPY", value=percent(summary["benchmark_return_pct"], signed=True))
    embed.add_field(name="Vs SPY", value=percent(summary["excess_return_pct"], signed=True))
    embed.add_field(name="Volatility", value=percent(summary["volatility_pct"]))
    embed.add_field(name="Sharpe", value=number(summary["sharpe"]))
    embed.add_field(name="Max drawdown", value=percent(summary["max_drawdown_pct"]))
    embed.add_field(name="Beta", value=number(summary["beta"]))

    footer = f"{summary['start_date']} to {summary['end_date']} ({summary['observations']} trading days)"
    if summary["observations"] < 5:
        footer += ". Ratios need more history to mean much."
    embed.set_footer(text=footer)
    return embed


def trades_embed(username, trades):
    lines = [
        f"{t['price_date']} **{t['side']}** {shares(Decimal(t['quantity']))} "
        f"{t['symbol']} at {money(Decimal(t['price_per_share']))}"
        for t in trades
    ]
    return discord.Embed(
        title=f"{username}'s Recent Trades",
        description=fit_lines(lines, DESCRIPTION_LIMIT) or "No trades yet.",
        color=discord.Color.blurple(),
    )
