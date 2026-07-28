from redbot.core.bot import Red

from .memeforge import MemeForge


async def setup(bot: Red) -> None:
    await bot.add_cog(MemeForge(bot))
