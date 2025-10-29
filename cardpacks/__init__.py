from .cardpacks import CardPacks  # noqa

async def setup(bot):
    await bot.add_cog(CardPacks(bot))

