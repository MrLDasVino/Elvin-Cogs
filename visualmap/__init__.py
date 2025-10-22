from .visualmap import VisualMap
from redbot.core.bot import Red

async def setup(bot: Red):
    cog = VisualMap(bot)
    await bot.add_cog(cog)