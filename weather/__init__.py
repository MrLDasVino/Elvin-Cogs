from .weather import Weather

async def setup(bot):
    """Async setup for Redbot."""
    await bot.add_cog(Weather(bot))
