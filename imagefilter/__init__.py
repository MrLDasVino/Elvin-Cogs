from .imagefilter import ImageFilter, image_effect_context_menu
import discord


async def setup(bot):
    await bot.add_cog(ImageFilter(bot))
    tree = getattr(bot, "tree", None)
    if tree is None:
        return
    existing = tree.get_command("Image Effect", type=discord.AppCommandType.message)
    if existing is not None:
        tree.remove_command("Image Effect", type=discord.AppCommandType.message)
    tree.add_command(image_effect_context_menu)
