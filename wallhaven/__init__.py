from .wallhaven import WallhavenCog

async def setup(bot):
    cog = WallhavenCog(bot)
    await bot.add_cog(cog)