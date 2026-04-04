# reactionroles/dashboard.py
import os
import typing
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator
import discord

_ = Translator("ReactionRoles", __file__)


def dashboard_page(*args, **kwargs):
    def decorator(func: typing.Callable):
        func.__dashboard_decorator_params__ = (args, kwargs)
        return func
    return decorator


class DashboardIntegration:
    """Dashboard integration for ReactionRoles."""
    bot: Red
    cog: typing.Any
    name: str = "ReactionRoles"
    description: str = "Manage reaction roles via the web dashboard"

    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        # Keep this method for compatibility; the cog registers the same instance directly.
        try:
            dashboard_cog.rpc.third_parties_handler.add_third_party(self)
        except Exception:
            # swallow to avoid breaking dashboard load
            return

    @staticmethod
    def _read_file(name: str) -> str:
        file_path = os.path.join(os.path.dirname(__file__), name)
        with open(file_path, "rt", encoding="utf-8") as f:
            return f.read()

    @dashboard_page(name=None, description="Reaction Roles editor")
    async def dashboard_editor(self, **kwargs) -> typing.Dict[str, typing.Any]:
        source = self._read_file("editor.html")
        return {"status": 0, "web_content": {"source": source, "standalone": True}}

    @dashboard_page(name="guild", description="Create or manage reaction roles for a guild", methods=("GET", "POST"))
    async def dashboard_guild(self, user: discord.User, guild: discord.Guild, **kwargs) -> typing.Dict[str, typing.Any]:
        # Minimal implementation to satisfy dashboard discovery.
        # The cog's full implementation (sending/attaching messages and adding mappings) should be used in production.
        is_owner = user.id in self.bot.owner_ids
        member = guild.get_member(user.id)
        if not is_owner and not await self.bot.is_mod(member):
            return {"status": 0, "error_code": 403, "message": _("You don't have permissions to access this page.")}

        source = self._read_file("editor.html")
        return {"status": 0, "web_content": {"source": source, "standalone": True}}
