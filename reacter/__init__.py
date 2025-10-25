from .reacter import Reacter

async def setup(bot):
    await bot.add_cog(Reacter(bot))