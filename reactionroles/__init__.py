# reactionroles/__init__.py
from .reactionroles import ReactionRoles  # noqa: F401

async def setup(bot):
    cog = ReactionRoles(bot)
    await bot.add_cog(cog)

    # If the Dashboard cog is already loaded when this cog is loaded,
    # register our dashboard integration instance immediately.
    try:
        dashboard_cog = bot.get_cog("Dashboard")
        if dashboard_cog:
            # dashboard expects the same object instance that exposes the decorated pages
            inst = cog.dashboard
            inst.bot = bot
            inst.cog = cog
            dashboard_cog.rpc.third_parties_handler.add_third_party(inst)
    except Exception:
        # don't raise during setup; registration will also be attempted in cog_load/on_dashboard_cog_add
        try:
            # best-effort logging if available
            if hasattr(bot, "logger"):
                bot.logger.debug("ReactionRoles: failed to auto-register dashboard integration in setup (will retry later).")
        except Exception:
            pass
