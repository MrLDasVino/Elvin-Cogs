from .battleroyale import BattleRoyale

async def setup(bot):

    cog = BattleRoyale(bot)
    try:
        await bot.add_cog(cog)
    except Exception:
        # If adding the cog failed, ensure any resources the cog created are closed
        try:
            # close aiohttp session if present
            sess = getattr(cog, "session", None)
            if sess is not None:
                # session.close() is a coroutine
                try:
                    await sess.close()
                except Exception:
                    pass
        except Exception:
            pass
        # re-raise so Red shows the original error
        raise
