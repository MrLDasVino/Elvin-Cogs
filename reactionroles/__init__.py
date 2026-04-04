# reactionroles/__init__.py
from .reactionroles import ReactionRoles  # noqa: F401

async def setup(bot):
    cog = ReactionRoles(bot)
    await bot.add_cog(cog)

    # Try immediate registration if Dashboard is already loaded
    try:
        dashboard_cog = bot.get_cog("Dashboard")
        if dashboard_cog:
            inst = cog.dashboard
            inst.bot = bot
            inst.cog = cog
            try:
                dashboard_cog.rpc.third_parties_handler.add_third_party(inst)
            except Exception:
                # best-effort logging if available
                try:
                    if hasattr(bot, "logger"):
                        bot.logger.debug("ReactionRoles: immediate dashboard registration failed in setup.")
                except Exception:
                    pass
    except Exception:
        # swallow errors during setup; registration will be attempted in cog_load/on_dashboard_cog_add
        try:
            if hasattr(bot, "logger"):
                bot.logger.debug("ReactionRoles: error while attempting dashboard registration in setup.")
        except Exception:
            pass
