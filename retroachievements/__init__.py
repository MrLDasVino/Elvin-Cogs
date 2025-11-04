from .retroachievements import RetroAchievements

async def setup(bot):
    await bot.add_cog(RetroAchievements(bot))
