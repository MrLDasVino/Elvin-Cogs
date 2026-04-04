from .reactionroles import ReactionRoles 

async def setup(bot):
    cog = ReactionRoles(bot)
    await bot.add_cog(cog)
