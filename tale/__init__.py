from .tale import TaleCog

async def setup(bot):
    await bot.add_cog(TaleCog(bot))