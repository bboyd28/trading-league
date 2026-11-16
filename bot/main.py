import discord
from discord.ext import commands
from dotenv import load_dotenv
import os

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")


class TradingBot(commands.Bot):

    def __init__(self):
        intents = discord.Intents.default()

        super().__init__(
            command_prefix="!",
            intents=intents
        )
    async def setup_hook(self):
        await self.load_extension("bot.commands")
        print("Command extension loaded.")

    async def on_ready(self):
        print(f"Logged in as {self.user}")

        synced = await self.tree.sync()

        print("Slash commands synchronized.")

        for command in synced:
            print(f"Registered command: /{command.name}")


bot = TradingBot()

bot.run(TOKEN)