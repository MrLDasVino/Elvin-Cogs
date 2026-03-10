import io
import math
import asyncio
import random
import re
from typing import List, Optional

from PIL import Image, ImageFilter, ImageOps, ImageEnhance, ImageChops, ImageDraw

import discord
from redbot.core import commands


URL_RE = re.compile(r"https?://\S+")


# ---------- Cog ----------

class Glint(commands.Cog):
    """Interactive image editor: apply stacked effects, undo, adjustable intensity, and post results."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._lock = asyncio.Lock()

    @commands.command(name="glint")
    @commands.guild_only()
    async def glint(self, ctx: commands.Context, *, maybe_url: Optional[str] = None):
        """
        Open the Glint image editor.
        Usage:
        - Reply to a message with an image and run `[p]glint`
        - Provide an image URL: `[p]glint https://.../image.png`
        - Attach an image and run `[p]glint`
        - Mention a user to use their avatar: `[p]glint @SomeUser`
        """
        image_bytes = None
        image_name = "glint.png"

        # 0) If user mentioned someone, try to use their avatar (explicit mention anywhere in message)
        if ctx.message.mentions:
            target = ctx.message.mentions[0]
            try:
                avatar_url = target.display_avatar.replace(size=1024).url
                async with self.bot.http._session.get(avatar_url) as resp:
                    if resp.status == 200:
                        image_bytes = await resp.read()
                        image_name = f"{target.id}_avatar.png"
            except Exception:
                image_bytes = None

        # 1) If message has attachments (highest priority after mention)
        if image_bytes is None and ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            try:
                image_bytes = await attachment.read()
                image_name = attachment.filename or image_name
            except Exception:
                image_bytes = None

        # 2) If replied to a message with attachments
        if image_bytes is None and ctx.message.reference:
            try:
                ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                if ref.attachments:
                    attachment = ref.attachments[0]
                    image_bytes = await attachment.read()
                    image_name = attachment.filename or image_name
            except Exception:
                pass

        # 3) If a URL was provided as argument or present in message content, try to fetch it
        if image_bytes is None:
            # Try the explicit argument first
            candidate_text = maybe_url or ""
            # If no explicit arg, search the whole message content for a URL
            if not candidate_text:
                candidate_text = ctx.message.content or ""
            # Find first http(s) URL
            m = URL_RE.search(candidate_text)
            if m:
                url = m.group(0)
                try:
                    async with self.bot.http._session.get(url) as resp:
                        if resp.status == 200:
                            image_bytes = await resp.read()
                            image_name = url.split("/")[-1].split("?")[0] or image_name
                except Exception:
                    image_bytes = None

        # 4) If still none, error
        if image_bytes is None:
            await ctx.send("Please attach an image, reply to a message with an image, mention a user to use their avatar, or provide an image URL.")
            return

        # Load image
        try:
            base_image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        except Exception:
            await ctx.send("Couldn't open the image. Make sure it's a valid image file.")
            return

        # Create session state
        session = GlintSession(ctx, base_image, image_name)
        view = GlintEditorView(session, timeout=300)
        embed = session.make_embed("Editor opened — choose effects from the dropdown and press Apply", random_color=True)

        # Attach the initial image to the editor message so it can be edited in-place
        bio = io.BytesIO()
        base_image.convert("RGBA").save(bio, "PNG")
        bio.seek(0)
        file = discord.File(bio, filename=image_name)

        # Send the editor message with the image attached. Keep a reference to the message for in-place edits.
        try:
            message = await ctx.send(embed=embed, file=file, view=view)
        except Exception:
            # Fallback: send without file (some versions) then send file separately and keep the editor message
            message = await ctx.send(embed=embed, view=view)
            try:
                await ctx.send(file=file)
            except Exception:
                pass

        session.set_message(message)
        await view.wait()
        # When view times out, finalize if not already posted
        if not session.finished:
            await session.finish_post(finalize=False)


# ---------- Session and UI ----------

class GlintSession:
    def __init__(self, ctx: commands.Context, base_image: Image.Image, filename: str):
        self.ctx = ctx
        self.base_image = base_image.copy()
        self.current_image = base_image.copy()
        self.filename = filename
        self.applied_effects: List[str] = []
        self.message: Optional[discord.Message] = None
        self.finished = False
        self.intensity = 100  # percent

    def set_message(self, message: discord.Message):
        self.message = message

    def _nice_embed_base(self, title: str, description: str, color: int) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_author(name="Glint Image Editor", icon_url=self.ctx.bot.user.display_avatar.replace(size=64).url)
        embed.set_footer(text="Select effects, press Apply to stack, Undo to remove last, Finish to post.")
        return embed

    def make_embed(self, description: str, random_color: bool = False) -> discord.Embed:
        color = random.randint(0, 0xFFFFFF) if random_color else 0x00FFAA
        embed = self._nice_embed_base("Glint Editor", description, color)
        embed.add_field(name="Applied effects", value=(", ".join(self.applied_effects) or "None"), inline=False)
        embed.add_field(name="Intensity", value=f"{self.intensity}%", inline=True)
        embed.set_thumbnail(url=f"attachment://{self.filename}")
        return embed

    async def update_message(self, view: discord.ui.View, description: str):
        if not self.message:
            return
        embed = self.make_embed(description, random_color=True)
        # attach current image as file and set embed image
        bio = io.BytesIO()
        self.current_image.convert("RGBA").save(bio, "PNG")
        bio.seek(0)
        file = discord.File(bio, filename=self.filename)
        embed.set_image(url=f"attachment://{self.filename}")

        # Try to edit the original message and attach the updated image in-place.
        # Different discord.py/Red versions handle attachments differently; try robustly.
        try:
            await self.message.edit(embed=embed, attachments=[file], view=view)
            return
        except Exception:
            pass

        # Some versions don't accept attachments on edit; try editing embed only then send the file so the embed image resolves.
        try:
            await self.message.edit(embed=embed, view=view)
            # send the file separately (ephemeral to channel)
            await self.ctx.send(file=file)
            return
        except Exception:
            pass

        # Last resort: send a new message with embed+file and update session.message to point to it (so future edits target it).
        try:
            new_msg = await self.ctx.send(embed=embed, file=file, view=view)
            self.message = new_msg
        except Exception:
            # If even that fails, silently ignore (we don't want to crash the bot)
            pass

    async def apply_effects(self, effects: List[str]):
        img = self.current_image.copy()
        for eff in effects:
            img = apply_effect(img, eff, intensity=self.intensity)
            self.applied_effects.append(eff)
        self.current_image = img

    async def undo(self):
        if not self.applied_effects:
            return False
        self.applied_effects.pop()
        img = self.base_image.copy()
        for eff in self.applied_effects:
            img = apply_effect(img, eff, intensity=self.intensity)
        self.current_image = img
        return True

    async def finish_post(self, finalize=True):
        if self.finished:
            return
        bio = io.BytesIO()
        self.current_image.convert("RGBA").save(bio, "PNG")
        bio.seek(0)
        file = discord.File(bio, filename=self.filename)
        color = random.randint(0, 0xFFFFFF)
        embed = self._nice_embed_base("Glint Result", ("Final image" if finalize else "Editor timed out; current image"), color)
        embed.add_field(name="Effects", value=(", ".join(self.applied_effects) or "None"), inline=False)
        embed.add_field(name="Intensity", value=f"{self.intensity}%", inline=True)
        embed.set_image(url=f"attachment://{self.filename}")
        await self.ctx.send(embed=embed, file=file)
        self.finished = True


# ---------- UI View ----------

EFFECT_CHOICES = [
    ("Grayscale", "grayscale"),
    ("Sepia", "sepia"),
    ("Invert", "invert"),
    ("Blur", "blur"),
    ("Gaussian Blur", "gaussian_blur"),
    ("Contour", "contour"),
    ("Emboss", "emboss"),
    ("Sharpen", "sharpen"),
    ("Edge Enhance", "edge_enhance"),
    ("Posterize", "posterize"),
    ("Solarize", "solarize"),
    ("Pixelate", "pixelate"),
    ("Vignette", "vignette"),
    ("Contrast+", "contrast_up"),
    ("Brightness+", "brightness_up"),
    ("Color Boost", "color_boost"),
    ("Warm Tone", "warm_tone"),
    ("Cool Tone", "cool_tone"),
    ("Old Film (grain)", "old_film"),
    ("Frame (border)", "frame"),
    ("Hue Shift +30", "hue_plus_30"),
    ("Hue Shift -30", "hue_minus_30"),
    ("Swap Red/Blue", "swap_rb"),
    ("Solar Glow", "solar_glow"),
]


def _make_select_options():
    return [discord.SelectOption(label=label, value=value) for label, value in EFFECT_CHOICES]


class GlintEditorView(discord.ui.View):
    def __init__(self, session: GlintSession, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.session = session
        self.selected_effects: List[str] = []

        # Select
        options = _make_select_options()
        self.select = discord.ui.Select(placeholder="Choose effects (multi-select)", min_values=1, max_values=5, options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

        # Intensity controls (small buttons)
        self.decrease_button = discord.ui.Button(label="-", style=discord.ButtonStyle.secondary, row=1)
        self.decrease_button.callback = self.decrease_intensity
        self.add_item(self.decrease_button)

        self.intensity_label = discord.ui.Button(label=f"{self.session.intensity}%", style=discord.ButtonStyle.gray, disabled=True, row=1)
        self.add_item(self.intensity_label)

        self.increase_button = discord.ui.Button(label="+", style=discord.ButtonStyle.secondary, row=1)
        self.increase_button.callback = self.increase_intensity
        self.add_item(self.increase_button)

        # Action buttons
        self.apply_button = discord.ui.Button(label="Apply", style=discord.ButtonStyle.success, row=2)
        self.apply_button.callback = self.apply_callback
        self.add_item(self.apply_button)

        self.undo_button = discord.ui.Button(label="Undo", style=discord.ButtonStyle.secondary, row=2)
        self.undo_button.callback = self.undo_callback
        self.add_item(self.undo_button)

        self.finish_button = discord.ui.Button(label="Finish", style=discord.ButtonStyle.primary, row=2)
        self.finish_button.callback = self.finish_callback
        self.add_item(self.finish_button)

        self.cancel_button = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger, row=2)
        self.cancel_button.callback = self.cancel_callback
        self.add_item(self.cancel_button)

    async def select_callback(self, interaction: discord.Interaction):
        # Save the selected values (read-only property)
        self.selected_effects = list(self.select.values)
        await interaction.response.defer()

    async def decrease_intensity(self, interaction: discord.Interaction):
        # Decrease by 10%, min 10%
        self.session.intensity = max(10, self.session.intensity - 10)
        self.intensity_label.label = f"{self.session.intensity}%"
        await self.session.update_message(self, f"Intensity set to {self.session.intensity}%")
        await interaction.response.defer()

    async def increase_intensity(self, interaction: discord.Interaction):
        # Increase by 10%, max 300%
        self.session.intensity = min(300, self.session.intensity + 10)
        self.intensity_label.label = f"{self.session.intensity}%"
        await self.session.update_message(self, f"Intensity set to {self.session.intensity}%")
        await interaction.response.defer()

    async def apply_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        async with self.session.ctx.typing():
            if not self.selected_effects:
                await interaction.followup.send("No effects selected. Use the dropdown to pick effects.", ephemeral=True)
                return
            await self.session.apply_effects(self.selected_effects)
            await self.session.update_message(self, f"Applied: {', '.join(self.selected_effects)}")
            # Clear stored selection and recreate select to clear UI
            self.selected_effects = []
            try:
                self.remove_item(self.select)
            except Exception:
                pass
            self.select = discord.ui.Select(placeholder="Choose effects (multi-select)", min_values=1, max_values=5, options=_make_select_options())
            self.select.callback = self.select_callback
            # Add the new select back into the view (discord.py will append; that's acceptable)
            self.add_item(self.select)
            await interaction.followup.send("Effects applied.", ephemeral=True)

    async def undo_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        undone = await self.session.undo()
        if not undone:
            await interaction.followup.send("Nothing to undo.", ephemeral=True)
            return
        await self.session.update_message(self, "Undid last effect")
        await interaction.followup.send("Undid last effect.", ephemeral=True)

    async def finish_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        await self.session.finish_post(finalize=True)
        await interaction.followup.send("Final image posted.", ephemeral=True)
        self.stop()

    async def cancel_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        await interaction.followup.send("Editor closed without posting final image.", ephemeral=True)
        self.stop()


# ---------- Image effect implementations (with intensity) ----------

def apply_effect(img: Image.Image, effect: str, intensity: int = 100) -> Image.Image:
    try:
        if effect == "grayscale":
            return ImageOps.grayscale(img).convert("RGBA")
        if effect == "sepia":
            return sepia(img, intensity)
        if effect == "invert":
            r, g, b, a = img.split()
            rgb = Image.merge("RGB", (r, g, b))
            inverted = ImageOps.invert(rgb)
            r2, g2, b2 = inverted.split()
            return Image.merge("RGBA", (r2, g2, b2, a))
        if effect == "blur":
            radius = max(1, int(1 + (intensity / 100.0) * 3))
            return img.filter(ImageFilter.BoxBlur(radius))
        if effect == "gaussian_blur":
            radius = max(1, int((intensity / 100.0) * 6))
            return img.filter(ImageFilter.GaussianBlur(radius=radius))
        if effect == "contour":
            return img.filter(ImageFilter.CONTOUR)
        if effect == "emboss":
            return img.filter(ImageFilter.EMBOSS)
        if effect == "sharpen":
            return img.filter(ImageFilter.SHARPEN)
        if effect == "edge_enhance":
            return img.filter(ImageFilter.EDGE_ENHANCE)
        if effect == "posterize":
            bits = max(1, int(8 - (intensity / 100.0) * 5))
            return ImageOps.posterize(img.convert("RGB"), bits=bits).convert("RGBA")
        if effect == "solarize":
            threshold = int(128 * (200 / max(1, intensity)))
            return ImageOps.solarize(img.convert("RGB"), threshold=threshold).convert("RGBA")
        if effect == "pixelate":
            pixel_size = max(2, int((intensity / 100.0) * 20))
            return pixelate(img, pixel_size=pixel_size)
        if effect == "vignette":
            return vignette(img, intensity=intensity)
        if effect == "contrast_up":
            factor = 1.0 + (intensity / 100.0) * 1.5
            return ImageEnhance.Contrast(img).enhance(factor)
        if effect == "brightness_up":
            factor = 1.0 + (intensity / 100.0) * 1.2
            return ImageEnhance.Brightness(img).enhance(factor)
        if effect == "color_boost":
            factor = 1.0 + (intensity / 100.0) * 1.8
            return ImageEnhance.Color(img).enhance(factor)
        if effect == "warm_tone":
            return color_tone(img, (int(30 * intensity / 100.0), int(10 * intensity / 100.0), int(-10 * intensity / 100.0)))
        if effect == "cool_tone":
            return color_tone(img, (int(-10 * intensity / 100.0), int(-10 * intensity / 100.0), int(30 * intensity / 100.0)))
        if effect == "old_film":
            return old_film(img, intensity=intensity)
        if effect == "frame":
            border = max(10, int(30 * intensity / 100.0))
            return add_frame(img, border=border)
        if effect == "hue_plus_30":
            deg = int(30 * (intensity / 100.0))
            return shift_hue(img, deg)
        if effect == "hue_minus_30":
            deg = -int(30 * (intensity / 100.0))
            return shift_hue(img, deg)
        if effect == "swap_rb":
            return swap_red_blue(img)
        if effect == "solar_glow":
            return solar_glow(img, intensity=intensity)
    except Exception:
        return img
    return img


def sepia(img: Image.Image, intensity: int = 100) -> Image.Image:
    img_rgb = img.convert("RGB")
    sep = Image.new("RGB", img_rgb.size, (112, 66, 20))
    blended = Image.blend(img_rgb, sep, alpha=min(0.9, intensity / 300.0))
    return blended.convert("RGBA")


def pixelate(img: Image.Image, pixel_size: int = 10) -> Image.Image:
    small = img.resize((max(1, img.width // pixel_size), max(1, img.height // pixel_size)), resample=Image.NEAREST)
    result = small.resize(img.size, Image.NEAREST)
    return result.convert("RGBA")


def vignette(img: Image.Image, intensity: int = 100) -> Image.Image:
    width, height = img.size
    gradient = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(gradient)
    max_dist = math.hypot(width / 2, height / 2)
    for y in range(height):
        for x in range(width):
            dx = x - width / 2
            dy = y - height / 2
            d = math.hypot(dx, dy)
            t = (d / max_dist)
            intensity_factor = min(1.0, (intensity / 100.0) * 1.5)
            intensity_val = int(255 * (t ** (1 + intensity_factor)))
            if intensity_val > 255:
                intensity_val = 255
            draw.point((x, y), fill=intensity_val)
    alpha = gradient.filter(ImageFilter.GaussianBlur(radius=max(1, min(width, height) // 20)))
    black = Image.new('RGBA', (width, height), (0, 0, 0, 255))
    img_with_vignette = Image.composite(black, img.convert("RGBA"), alpha)
    return img_with_vignette


def color_tone(img: Image.Image, shifts=(0, 0, 0)) -> Image.Image:
    r_shift, g_shift, b_shift = shifts
    r, g, b, a = img.split()
    r = ImageEnhance.Brightness(r).enhance(1 + r_shift / 100.0)
    g = ImageEnhance.Brightness(g).enhance(1 + g_shift / 100.0)
    b = ImageEnhance.Brightness(b).enhance(1 + b_shift / 100.0)
    return Image.merge("RGBA", (r, g, b, a))


def old_film(img: Image.Image, intensity: int = 100) -> Image.Image:
    sep = sepia(img, intensity=intensity)
    grain_strength = int(max(10, (intensity / 100.0) * 80))
    noise = Image.effect_noise(img.size, grain_strength).convert("L").point(lambda p: p // 3)
    noise = Image.merge("RGBA", (noise, noise, noise, Image.new("L", img.size, int(40 * intensity / 100.0))))
    combined = ImageChops.add(sep.convert("RGBA"), noise)
    return combined


def add_frame(img: Image.Image, border=30, color=(30, 30, 30)) -> Image.Image:
    new_w = img.width + border * 2
    new_h = img.height + border * 2
    framed = Image.new("RGBA", (new_w, new_h), color + (255,))
    framed.paste(img, (border, border), img)
    return framed


def shift_hue(img: Image.Image, deg: int) -> Image.Image:
    img = img.convert("RGBA")
    arr = img.convert("RGBA")
    r, g, b, a = arr.split()
    rgb = Image.merge("RGB", (r, g, b)).convert("HSV")
    h, s, v = rgb.split()
    lut = [(i + int(deg * 255 / 360)) % 256 for i in range(256)]
    h = h.point(lut)
    new_rgb = Image.merge("HSV", (h, s, v)).convert("RGBA")
    new_rgb.putalpha(a)
    return new_rgb


def swap_red_blue(img: Image.Image) -> Image.Image:
    r, g, b, a = img.split()
    return Image.merge("RGBA", (b, g, r, a))


def solar_glow(img: Image.Image, intensity: int = 100) -> Image.Image:
    img = img.convert("RGBA")
    radius = max(5, int((intensity / 100.0) * 30))
    glow = img.copy().filter(ImageFilter.GaussianBlur(radius=radius))
    enhancer = ImageEnhance.Brightness(glow)
    glow = enhancer.enhance(1.0 + (intensity / 100.0) * 1.5)
    try:
        return ImageChops.screen(img, glow)
    except Exception:
        return img
