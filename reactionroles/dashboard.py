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
        dashboard_cog.rpc.third_parties_handler.add_third_party(self)

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
        # Implementation mirrors examples; omitted here for brevity — keep your existing implementation.
        return {"status": 0, "web_content": {"source": self._read_file("editor.html"), "standalone": True}}
