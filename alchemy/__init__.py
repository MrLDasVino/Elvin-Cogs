from .alchemy import Alchemy


async def setup(bot):

    await bot.add_cog(Alchemy(bot))
