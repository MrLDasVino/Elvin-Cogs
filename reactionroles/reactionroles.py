# reactionroles/reactionroles.py
import logging
import typing
import discord
from redbot.core import checks, commands, Config
from redbot.core.bot import Red
from redbot.core.i18n import Translator
from redbot.core.utils.chat_formatting import pagify

from .dashboard import DashboardIntegration  # type: ignore

_ = Translator("ReactionRoles", __file__)
log = logging.getLogger("red.reactionroles")


def emoji_to_key(emoji: typing.Union[discord.PartialEmoji, discord.Emoji, str]) -> str:
    if isinstance(emoji, (discord.PartialEmoji, discord.Emoji)):
        if getattr(emoji, "id", None):
            return f"<:{emoji.name}:{emoji.id}>"
        return str(emoji)
    return str(emoji)


class ReactionRoles(commands.Cog):
    """Reaction role manager (admin only)."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.logger = log
        self.config = Config.get_conf(self, identifier=0xA1B2C3D4E7, force_registration=True)
        self.config.register_guild(messages={})
        self._dashboard_integration: typing.Optional[DashboardIntegration] = None

    async def cog_load(self) -> None:
        try:
            dashboard_cog = self.bot.get_cog("Dashboard")
            if dashboard_cog:
                inst = self.dashboard
                inst.bot = self.bot
                inst.cog = self
                dashboard_cog.rpc.third_parties_handler.add_third_party(inst)
                self.logger.info("ReactionRoles: dashboard integration registered during cog_load.")
        except Exception:
            self.logger.exception("ReactionRoles: dashboard registration failed in cog_load.")

    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        try:
            inst = self.dashboard
            inst.bot = self.bot
            inst.cog = self
            dashboard_cog.rpc.third_parties_handler.add_third_party(inst)
            self.logger.info("ReactionRoles: dashboard integration registered via on_dashboard_cog_add.")
        except Exception:
            self.logger.exception("ReactionRoles: failed to register dashboard integration via event")

    # --- status command for debugging dashboard registration ---
    @commands.command(name="reactionroles-dashboardstatus")
    @checks.admin_or_permissions(manage_guild=True)
    async def dashboard_status(self, ctx: commands.Context):
        """Show dashboard registration status (debug)."""
        lines = []
        dashboard_cog = self.bot.get_cog("Dashboard")
        lines.append(f"Dashboard cog loaded: {bool(dashboard_cog)}")
        if not dashboard_cog:
            await ctx.send("\n".join(lines))
            return
        handler = getattr(dashboard_cog.rpc, "third_parties_handler", None)
        lines.append(f"third_parties_handler present: {bool(handler)}")
        if not handler:
            await ctx.send("\n".join(lines))
            return
        # try to inspect registered third parties (handler internals vary by version)
        try:
            registered = getattr(handler, "third_parties", None) or getattr(handler, "_third_parties", None)
            if registered is None:
                # try list method
                registered = getattr(handler, "list_third_parties", lambda: [])()
            # check for our instance
            inst = self.dashboard
            present = False
            for item in (registered or []):
                if item is inst:
                    present = True
                    break
            lines.append(f"our integration instance registered: {present}")
            # list decorated pages on our instance
            pages = []
            for attr in dir(inst):
                obj = getattr(inst, attr)
                if hasattr(obj, "__dashboard_decorator_params__"):
                    pages.append(f"{attr}: {getattr(obj,'__dashboard_decorator_params__')}")
            lines.append(f"decorated pages found: {len(pages)}")
            lines.extend(pages[:20])
        except Exception as e:
            lines.append(f"error inspecting handler: {e}")
        await ctx.send("\n".join(lines))

    # --- rest of commands/events omitted for brevity; keep your existing commands here ---
    # For brevity in this snippet, assume all previously provided commands (send/add/remove/list/clear/delete)
    # remain unchanged and present below in your actual file.
    # (When you replace the file, include the full command implementations as before.)
    pass

    @property
    def dashboard(self) -> DashboardIntegration:
        if self._dashboard_integration is None:
            inst = DashboardIntegration()
            inst.bot = self.bot
            inst.cog = self
            self._dashboard_integration = inst
        return self._dashboard_integration
