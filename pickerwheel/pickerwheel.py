import io
import math
import random
import re
import colorsys
from PIL import Image, ImageDraw, ImageFont
import imageio
import discord
from redbot.core import commands, Config

class PickerWheel(commands.Cog):
    """Multiple named wheels with admin-only management and bulk adds."""

    DEFAULT_CONFIG = {"wheels": {}}

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.config.register_guild(**self.DEFAULT_CONFIG)
        # Use a bold, larger TTF font for maximum readability
        self.font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20
        )

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    async def pickerwheel(self, ctx):
        """Create, manage, and spin named wheels."""
        if not ctx.invoked_subcommand:
            await ctx.send_help()

    @pickerwheel.command()
    @commands.has_guild_permissions(administrator=True)
    async def create(self, ctx, name: str):
        """Create a new wheel with the given name."""
        name = name.lower()
        wheels = await self.config.guild(ctx.guild).wheels()
        if name in wheels:
            return await ctx.send(f"❌ Wheel **{name}** already exists.")
        wheels[name] = []
        await self.config.guild(ctx.guild).wheels.set(wheels)
        await ctx.send(f"✅ Created wheel **{name}**.")

    @pickerwheel.command()
    @commands.has_guild_permissions(administrator=True)
    async def delete(self, ctx, name: str):
        """Delete the wheel and all its options."""
        name = name.lower()
        wheels = await self.config.guild(ctx.guild).wheels()
        if name not in wheels:
            return await ctx.send(f"❌ No wheel named **{name}**.")
        wheels.pop(name)
        await self.config.guild(ctx.guild).wheels.set(wheels)
        await ctx.send(f"🗑 Deleted wheel **{name}**.")

    @pickerwheel.command(name="list")
    @commands.has_guild_permissions(administrator=True)
    async def _list(self, ctx, name: str = None):
        """
        List wheels or the options of a specific wheel.
        Without <name> shows all wheels; with <name> shows its items.
        """
        wheels = await self.config.guild(ctx.guild).wheels()
        if name is None:
            if not wheels:
                return await ctx.send("No wheels exist. Create one with `create`.")
            lines = [f"{w}: {len(opts)} items" for w, opts in wheels.items()]
            return await ctx.send("**Saved wheels:**\n" + "\n".join(lines))

        key = name.lower()
        if key not in wheels:
            return await ctx.send(f"❌ No wheel named **{key}**.")
        opts = wheels[key]
        if not opts:
            return await ctx.send(f"Wheel **{key}** is empty.")
        msg = "\n".join(f"{i+1}. {item}" for i, item in enumerate(opts))
        await ctx.send(f"**Options in {key}:**\n{msg}")

    @pickerwheel.command()
    @commands.has_guild_permissions(administrator=True)
    async def add(self, ctx, name: str, *, raw_items: str):
        """
        Add one or more options to a specific wheel.
        Separate items with commas or semicolons.
        """
        key = name.lower()
        wheels = await self.config.guild(ctx.guild).wheels()
        if key not in wheels:
            return await ctx.send(f"❌ No wheel named **{key}**.")
        parts = [p.strip() for p in re.split(r"[;,]", raw_items) if p.strip()]
        wheels[key].extend(parts)
        await self.config.guild(ctx.guild).wheels.set(wheels)
        added = ", ".join(f"**{p}**" for p in parts)
        await ctx.send(f"✅ Added {added} to **{key}**.")

    @pickerwheel.command()
    @commands.has_guild_permissions(administrator=True)
    async def remove(self, ctx, name: str, index: int):
        """Remove an option by 1-based index from a wheel."""
        key = name.lower()
        wheels = await self.config.guild(ctx.guild).wheels()
        if key not in wheels:
            return await ctx.send(f"❌ No wheel named **{key}**.")
        opts = wheels[key]
        if index < 1 or index > len(opts):
            return await ctx.send("❌ Invalid index.")
        removed = opts.pop(index - 1)
        wheels[key] = opts
        await self.config.guild(ctx.guild).wheels.set(wheels)
        await ctx.send(f"🗑 Removed **{removed}** from **{key}**.")

    @pickerwheel.command()
    @commands.has_guild_permissions(administrator=True)
    async def clear(self, ctx, name: str):
        """Clear all options from a wheel."""
        key = name.lower()
        wheels = await self.config.guild(ctx.guild).wheels()
        if key not in wheels:
            return await ctx.send(f"❌ No wheel named **{key}**.")
        wheels[key] = []
        await self.config.guild(ctx.guild).wheels.set(wheels)
        await ctx.send(f"🧹 Cleared wheel **{key}**.")

    @pickerwheel.command()
    async def spin(self, ctx, name: str, frames: int = 30, duration: float = 3.0):
        """
        Spin the specified wheel.
        frames: total frames in the GIF
        duration: total seconds of animation
        """
        key = name.lower()
        wheels = await self.config.guild(ctx.guild).wheels()
        if key not in wheels:
            return await ctx.send(f"❌ No wheel named **{key}**.")
        opts = wheels[key]
        if len(opts) < 2:
            return await ctx.send("Need at least two options to spin.")

        winner = random.choice(opts)
        gif = await self._make_wheel_gif(opts, frames, duration)
        file = discord.File(fp=gif, filename="wheel.gif")
        await ctx.send(f"🎉 **{key}** stops on **{winner}**!", file=file)

    def _get_colors(self, n):
        """Generate n evenly spaced, vibrant rainbow colors."""
        cols = []
        for i in range(n):
            h = i / n
            s, v = 0.8, 0.9
            r, g, b = colorsys.hsv_to_rgb(h, s, v)
            cols.append((int(r * 255), int(g * 255), int(b * 255)))
        return cols

    async def _make_wheel_gif(self, options, frames, duration):
        size = 500
        center = size // 2
        radius = center - 10
        sector = 360 / len(options)
        colors = self._get_colors(len(options))
        imgs = []

        for frame in range(frames):
            offset = (frame / frames) * 360
            im = Image.new("RGBA", (size, size), (255, 255, 255, 0))
            draw = ImageDraw.Draw(im)

            for idx, (opt, col) in enumerate(zip(options, colors)):
                # draw slice
                start = idx * sector + offset
                end = start + sector
                draw.pieslice(
                    [10, 10, size - 10, size - 10],
                    start, end,
                    fill=col,
                    outline=(0, 0, 0),
                )

                # label position
                mid_ang = math.radians((start + end) / 2)
                tx = center + (radius + 15) * math.cos(mid_ang)
                ty = center + (radius + 15) * math.sin(mid_ang)

                # truncate label
                label = opt if len(opt) <= 12 else opt[:12] + "…"

                # choose text color for contrast
                brightness = 0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2]
                text_fill = "black" if brightness > 128 else "white"
                outline_fill = "white" if text_fill == "black" else "black"

                # measure and render text with stroke
                x0, y0, x1, y1 = draw.textbbox((0, 0), label, font=self.font)
                w, h = x1 - x0, y1 - y0
                text_im = Image.new("RGBA", (w + 4, h + 4), (0, 0, 0, 0))
                td = ImageDraw.Draw(text_im)
                td.text(
                    (2, 2),
                    label,
                    font=self.font,
                    fill=text_fill,
                    stroke_width=1,
                    stroke_fill=outline_fill,
                )

                # rotate text upright and paste with a soft white halo
                rot = text_im.rotate(-math.degrees(mid_ang), expand=True)
                px, py = int(tx - rot.width / 2), int(ty - rot.height / 2)
                halo = Image.new("RGBA", rot.size, (255, 255, 255, 180))
                mask = rot.split()[3]
                im.paste(halo, (px, py), mask)
                im.paste(rot, (px, py), rot)

            imgs.append(im.convert("P"))

        bio = io.BytesIO()
        imageio.mimsave(bio, imgs, format="GIF", duration=duration / frames)
        bio.seek(0)
        return bio

async def setup(bot):
    await bot.add_cog(PickerWheel(bot))
