from .battleroyale import BattleRoyale

async def setup(bot):

    await bot.add_cog(BattleRoyale(bot))
