from typing import TYPE_CHECKING

from redbot.core.bot import Red

if TYPE_CHECKING:
    from .reactionroles import ReactionRoles  # noqa: F401

__red_end_user_data_statement__ = (
    "This cog stores guild-specific reaction role configuration (message IDs, channel IDs, "
    "emoji -> role mappings, and the author who created the mapping) using Red's Config system. "
    "No personal data beyond Discord IDs is stored. You can request deletion of stored data "
    "by removing the cog or using the bot's config management commands if available."
)


async def setup(bot: Red):

    from .reactionroles import ReactionRoles  # type: ignore

    cog = ReactionRoles(bot)
    await bot.add_cog(cog)
