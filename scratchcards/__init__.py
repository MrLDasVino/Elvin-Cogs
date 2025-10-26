from .scratchcards import ScratchCardExtended  # noqa: F401

async def setup(bot):
    cog = ScratchCardExtended(bot)
    await bot.add_cog(cog)