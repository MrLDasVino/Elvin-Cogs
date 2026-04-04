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

        # Try to obtain registered items from common handler internals
        registered = None
        try:
            registered = getattr(handler, "third_parties", None)
            if registered is None:
                registered = getattr(handler, "_third_parties", None)
            if registered is None and hasattr(handler, "list_third_parties"):
                try:
                    registered = handler.list_third_parties()
                except Exception:
                    registered = None
        except Exception as e:
            lines.append(f"error accessing handler internals: {e}")

        # Normalize registered into a list of objects to inspect
        objs = []
        if registered:
            # handler may store dicts, tuples, or objects
            if isinstance(registered, dict):
                # dict mapping name -> obj
                for k, v in registered.items():
                    if isinstance(v, dict) and "object" in v:
                        objs.append(v["object"])
                    else:
                        objs.append(v)
            elif isinstance(registered, (list, tuple, set)):
                for item in registered:
                    if isinstance(item, dict) and "object" in item:
                        objs.append(item["object"])
                    else:
                        objs.append(item)
            else:
                objs.append(registered)
        else:
            # fallback: try common attribute names on handler
            for attr in ("_third_parties", "third_parties", "registered"):
                val = getattr(handler, attr, None)
                if val:
                    if isinstance(val, (list, tuple, set)):
                        objs.extend(val)
                    else:
                        objs.append(val)

        # Helper to detect a dashboard integration by decorated pages
        def is_integration_candidate(o):
            try:
                for attr in dir(o):
                    obj = getattr(o, attr, None)
                    if hasattr(obj, "__dashboard_decorator_params__"):
                        return True
            except Exception:
                return False
            return False

        # Check if our exact instance is present (identity)
        inst = self.dashboard
        present_identity = False
        for o in objs:
            if o is inst:
                present_identity = True
                break

        # Check if any registered object looks like our integration (has decorated pages)
        present_candidate = False
        candidate_names = []
        for o in objs:
            if is_integration_candidate(o):
                present_candidate = True
                candidate_names.append(getattr(o, "name", getattr(o, "__class__", type(o)).__name__))

        lines.append(f"our integration instance registered (identity): {present_identity}")
        lines.append(f"any integration-like object registered (decorated pages): {present_candidate}")
        lines.append(f"integration-like registered names (sample up to 10): {candidate_names[:10]}")

        # Also list decorated pages on our instance for comparison
        pages = []
        try:
            for attr in dir(inst):
                obj = getattr(inst, attr)
                if hasattr(obj, "__dashboard_decorator_params__"):
                    pages.append(f"{attr}: {getattr(obj,'__dashboard_decorator_params__')}")
        except Exception as e:
            pages.append(f"error enumerating pages: {e}")

        lines.append(f"decorated pages found on our instance: {len(pages)}")
        lines.extend(pages[:20])

        await ctx.send("\n".join(lines))

    # --- rest of commands/events should be present below (send/add/remove/list/clear/delete) ---
    # For brevity in this snippet the full command implementations are omitted.
    # When you replace the file, ensure all command implementations you previously had are included here.

    @property
    def dashboard(self) -> DashboardIntegration:
        if self._dashboard_integration is None:
            inst = DashboardIntegration()
            inst.bot = self.bot
            inst.cog = self
            self._dashboard_integration = inst
        return self._dashboard_integration
