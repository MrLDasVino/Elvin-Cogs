from redbot.core.bot import Red

from .chronicle import Chronicle


async def setup(bot: Red) -> None:
    await bot.add_cog(Chronicle(bot))
