from redbot.core.bot import Red

from .chatterbox import ChatterBox


async def setup(bot: Red) -> None:
    await bot.add_cog(ChatterBox(bot))
