from .imagefilter import ImageFilter, image_effect_context_menu
import discord


async def setup(bot):
    await bot.add_cog(ImageFilter(bot))
    tree = getattr(bot, "tree", None)
    if tree is None:
        return
    tree.remove_command("Image Effect", type=discord.AppCommandType.message)
    image_effect_context_menu.extras["red_force_enable"] = True
    tree.add_command(image_effect_context_menu, override=True)
    red_check_enabled = getattr(tree, "red_check_enabled", None)
    if red_check_enabled is not None:
        await red_check_enabled()
