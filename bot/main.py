"""Run from the project root with: python -m bot.main"""
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from core.database import initialize_database

logger = logging.getLogger(__name__)


class TradingBot(commands.Bot):

    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
        )

    async def setup_hook(self):
        await self.load_extension("bot.commands")
        await self.load_extension("bot.tasks")

        # A guild sync shows up instantly. A global sync can take up to an hour.
        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()

        logger.info("Synced commands: %s", [c.name for c in synced])

    async def on_ready(self):
        logger.info("Logged in as %s", self.user)


def main():
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN is missing. Copy .env.example to .env and fill it in.")

    initialize_database()
    TradingBot().run(token, log_handler=None)


if __name__ == "__main__":
    main()
