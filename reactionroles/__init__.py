# reactionroles/__init__.py
from .reactionroles import ReactionRoles  # noqa: F401

async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
