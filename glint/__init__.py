from .glint import Glint

async def setup(bot):

    await bot.add_cog(Glint(bot))
