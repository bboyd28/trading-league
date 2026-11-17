"""Scheduled jobs: daily prices and snapshots, plus a Friday weekly board."""
import asyncio
import datetime
import logging
import os

from discord.ext import commands, tasks

from bot import embeds
from core.leaderboard import get_standings
from core.market_calendar import EASTERN, is_trading_day, today_eastern
from core.market_updates import catch_up_snapshots, run_daily_market_update

logger = logging.getLogger(__name__)

# Half an hour after the close has settled.
UPDATE_TIME = datetime.time(hour=16, minute=30, tzinfo=EASTERN)
FRIDAY = 4


class MarketTasks(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.daily_update.start()

    async def cog_unload(self):
        self.daily_update.cancel()

    async def _post(self, **message):
        channel_id = os.getenv("LEAGUE_CHANNEL_ID")
        channel = self.bot.get_channel(int(channel_id)) if channel_id else None

        if channel is not None:
            await channel.send(**message)

    @tasks.loop(time=UPDATE_TIME)
    async def daily_update(self):
        if not is_trading_day(today_eastern()):
            return

        result = await asyncio.to_thread(run_daily_market_update)
        failed = result["price_updates"]["failed"]
        failures = result["snapshot_failures"]
        logger.info("Daily update: %s snapshots, failed prices %s, failed snapshots %s",
                    len(result["snapshots_saved"]), failed, failures)

        if failed or failures:
            await self._post(
                content=f"Daily update had problems.\nPrices: {failed or 'ok'}\n"
                        f"Snapshots: {failures or 'ok'}"
            )

        if today_eastern().weekday() == FRIDAY:
            standings = await asyncio.to_thread(get_standings, "week")
            if standings and standings["rows"]:
                await self._post(embed=embeds.leaderboard_embed(standings))

    @daily_update.before_loop
    async def before_daily_update(self):
        await self.bot.wait_until_ready()
        # If the bot was offline, fill in the days it missed.
        filled = await asyncio.to_thread(catch_up_snapshots)
        if filled:
            logger.info("Caught up snapshots for %s", list(filled["days"]))

    @daily_update.error
    async def daily_update_error(self, error):
        logger.exception("Daily update crashed", exc_info=error)


async def setup(bot):
    await bot.add_cog(MarketTasks(bot))
