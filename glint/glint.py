import io
import math
import asyncio
from typing import List, Optional

from PIL import Image, ImageFilter, ImageOps, ImageEnhance, ImageChops, ImageDraw

import discord
from redbot.core import commands


class Glint(commands.Cog):
    """Image effects editor: apply, stack, undo, and post image effects via dropdown and buttons."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._lock = asyncio.Lock()

    @commands.command(name="glint")
    @commands.guild_only()
    async def glint(self, ctx: commands.Context, *, url: Optional[str] = None):
        """
        Open the Glint image editor.
        Usage:
        - Reply to a message with an image and run `[p]glint`
        - Provide an image URL: `[p]glint https://.../image.png`
        - Attach an image and run `[p]glint`
        """
        image_bytes = None
        image_name = "glint.png"

        # 1) If message has attachments
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            image_bytes = await attachment.read()
            image_name = attachment.filename

        # 2) If replied to a message with attachments
        elif ctx.message.reference:
            try:
                ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                if ref.attachments:
                    attachment = ref.attachments[0]
                    image_bytes = await attachment.read()
                    image_name = attachment.filename
            except Exception:
                pass

        # 3) If URL provided
        if image_bytes is None and url:
            try:
                async with self.bot.http._session.get(url) as resp:
                    if resp.status == 200:
                        image_bytes = await resp.read()
                        image_name = url.split("/")[-1].split("?")[0] or "glint.png"
            except Exception:
                image_bytes = None

        # 4) If still none, error
        if image_bytes is None:
            await ctx.send("Please attach an image, reply to a message with an image, or provide an image URL.")
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
        embed = session.make_embed("Editor opened — choose effects from the dropdown and press Apply")
        message = await ctx.send(embed=embed, view=view)
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

    def set_message(self, message: discord.Message):
        self.message = message

    def make_embed(self, description: str) -> discord.Embed:
        embed = discord.Embed(title="Glint Image Editor", description=description, color=0x00FFAA)
        embed.add_field(name="Applied effects", value=(", ".join(self.applied_effects) or "None"), inline=False)
        embed.set_footer(text="Use the dropdown to pick effects. Apply stacks them. Undo removes last.")
        return embed

    async def update_message(self, view: discord.ui.View, description: str):
        if not self.message:
            return
        embed = self.make_embed(description)
        bio = io.BytesIO()
        self.current_image.convert("RGBA").save(bio, "PNG")
        bio.seek(0)
        file = discord.File(bio, filename=self.filename)
        embed.set_image(url=f"attachment://{self.filename}")
        try:
            await self.message.edit(embed=embed, attachments=[file], view=view)
        except Exception:
            try:
                await self.ctx.send(embed=embed, file=file, view=view)
            except Exception:
                pass

    async def apply_effects(self, effects: List[str]):
        img = self.current_image.copy()
        for eff in effects:
            img = apply_effect(img, eff)
            self.applied_effects.append(eff)
        self.current_image = img

    async def undo(self):
        if not self.applied_effects:
            return False
        self.applied_effects.pop()
        img = self.base_image.copy()
        for eff in self.applied_effects:
            img = apply_effect(img, eff)
        self.current_image = img
        return True

    async def finish_post(self, finalize=True):
        if self.finished:
            return
        bio = io.BytesIO()
        self.current_image.convert("RGBA").save(bio, "PNG")
        bio.seek(0)
        file = discord.File(bio, filename=self.filename)
        embed = discord.Embed(title="Glint Result", description=("Final image" if finalize else "Editor timed out; current image"), color=0x00FFAA)
        embed.add_field(name="Effects", value=(", ".join(self.applied_effects) or "None"), inline=False)
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

class GlintEditorView(discord.ui.View):
    def __init__(self, session: GlintSession, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.session = session
        self.selected_effects: List[str] = []

        options = [discord.SelectOption(label=label, value=value) for label, value in EFFECT_CHOICES]
        self.select = discord.ui.Select(placeholder="Choose effects (you can multi-select)", min_values=1, max_values=5, options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

        self.apply_button = discord.ui.Button(label="Apply", style=discord.ButtonStyle.success)
        self.apply_button.callback = self.apply_callback
        self.add_item(self.apply_button)

        self.undo_button = discord.ui.Button(label="Undo", style=discord.ButtonStyle.secondary)
        self.undo_button.callback = self.undo_callback
        self.add_item(self.undo_button)

        self.finish_button = discord.ui.Button(label="Finish", style=discord.ButtonStyle.primary)
        self.finish_button.callback = self.finish_callback
        self.add_item(self.finish_button)

        self.cancel_button = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        self.cancel_button.callback = self.cancel_callback
        self.add_item(self.cancel_button)

    async def select_callback(self, interaction: discord.Interaction):
        self.selected_effects = self.select.values
        await interaction.response.defer()

    async def apply_callback(self, interaction: discord.Interaction):
        async with self.session.ctx.typing():
            if not self.selected_effects:
                await interaction.response.send_message("No effects selected. Use the dropdown to pick effects.", ephemeral=True)
                return
            await self.session.apply_effects(self.selected_effects)
            await self.session.update_message(self, f"Applied: {', '.join(self.selected_effects)}")
            self.selected_effects = []
            self.select.values = []
            await interaction.response.defer()

    async def undo_callback(self, interaction: discord.Interaction):
        undone = await self.session.undo()
        if not undone:
            await interaction.response.send_message("Nothing to undo.", ephemeral=True)
            return
        await self.session.update_message(self, "Undid last effect")
        await interaction.response.defer()

    async def finish_callback(self, interaction: discord.Interaction):
        await self.session.finish_post(finalize=True)
        await interaction.response.send_message("Final image posted.", ephemeral=True)
        self.stop()

    async def cancel_callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("Editor closed without posting final image.", ephemeral=True)
        self.stop()


# ---------- Image effect implementations ----------

def apply_effect(img: Image.Image, effect: str) -> Image.Image:
    try:
        if effect == "grayscale":
            return ImageOps.grayscale(img).convert("RGBA")
        if effect == "sepia":
            return sepia(img)
        if effect == "invert":
            r, g, b, a = img.split()
            rgb = Image.merge("RGB", (r, g, b))
            inverted = ImageOps.invert(rgb)
            r2, g2, b2 = inverted.split()
            return Image.merge("RGBA", (r2, g2, b2, a))
        if effect == "blur":
            return img.filter(ImageFilter.BoxBlur(2))
        if effect == "gaussian_blur":
            return img.filter(ImageFilter.GaussianBlur(radius=4))
        if effect == "contour":
            return img.filter(ImageFilter.CONTOUR)
        if effect == "emboss":
            return img.filter(ImageFilter.EMBOSS)
        if effect == "sharpen":
            return img.filter(ImageFilter.SHARPEN)
        if effect == "edge_enhance":
            return img.filter(ImageFilter.EDGE_ENHANCE)
        if effect == "posterize":
            return ImageOps.posterize(img.convert("RGB"), bits=3).convert("RGBA")
        if effect == "solarize":
            return ImageOps.solarize(img.convert("RGB"), threshold=128).convert("RGBA")
        if effect == "pixelate":
            return pixelate(img, pixel_size=12)
        if effect == "vignette":
            return vignette(img)
        if effect == "contrast_up":
            return ImageEnhance.Contrast(img).enhance(1.5)
        if effect == "brightness_up":
            return ImageEnhance.Brightness(img).enhance(1.3)
        if effect == "color_boost":
            return ImageEnhance.Color(img).enhance(1.6)
        if effect == "warm_tone":
            return color_tone(img, (30, 10, -10))
        if effect == "cool_tone":
            return color_tone(img, (-10, -10, 30))
        if effect == "old_film":
            return old_film(img)
        if effect == "frame":
            return add_frame(img)
        if effect == "hue_plus_30":
            return shift_hue(img, 30)
        if effect == "hue_minus_30":
            return shift_hue(img, -30)
        if effect == "swap_rb":
            return swap_red_blue(img)
        if effect == "solar_glow":
            return solar_glow(img)
    except Exception:
        return img
    return img


def sepia(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    width, height = img.size
    pixels = img.load()
    for py in range(height):
        for px in range(width):
            r, g, b = pixels[px, py]
            tr = int(0.393 * r + 0.769 * g + 0.189 * b)
            tg = int(0.349 * r + 0.686 * g + 0.168 * b)
            tb = int(0.272 * r + 0.534 * g + 0.131 * b)
            pixels[px, py] = (min(255, tr), min(255, tg), min(255, tb))
    return img.convert("RGBA")


def pixelate(img: Image.Image, pixel_size: int = 10) -> Image.Image:
    small = img.resize((max(1, img.width // pixel_size), max(1, img.height // pixel_size)), resample=Image.NEAREST)
    result = small.resize(img.size, Image.NEAREST)
    return result.convert("RGBA")


def vignette(img: Image.Image) -> Image.Image:
    width, height = img.size
    gradient = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(gradient)
    max_dist = math.hypot(width / 2, height / 2)
    for y in range(height):
        for x in range(width):
            dx = x - width / 2
            dy = y - height / 2
            d = math.hypot(dx, dy)
            intensity = int(255 * (d / max_dist))
            if intensity > 255:
                intensity = 255
            draw.point((x, y), fill=intensity)
    alpha = gradient.filter(ImageFilter.GaussianBlur(radius=min(width, height) // 10))
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


def old_film(img: Image.Image) -> Image.Image:
    sep = sepia(img)
    noise = Image.effect_noise(img.size, 64).convert("L").point(lambda p: p // 3)
    noise = Image.merge("RGBA", (noise, noise, noise, Image.new("L", img.size, 80)))
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


def solar_glow(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    glow = img.copy().filter(ImageFilter.GaussianBlur(radius=20))
    enhancer = ImageEnhance.Brightness(glow)
    glow = enhancer.enhance(1.8)
    return ImageChops.screen(img, glow)
