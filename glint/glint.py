# glint.py
import io
import math
import asyncio
import random
import re
import time
import uuid
from typing import List, Optional

import aiohttp
from PIL import Image, ImageFilter, ImageOps, ImageEnhance, ImageChops, ImageDraw

import discord
from redbot.core import commands

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


class Glint(commands.Cog):
    """Interactive image editor: apply stacked effects, undo, adjustable intensity, and post results."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._lock = asyncio.Lock()

    @commands.command(name="glint")
    @commands.guild_only()
    async def glint(self, ctx: commands.Context, *, maybe_text: Optional[str] = None):
        """
        Open the Glint image editor.

        Usage:
        - Reply to a message with an image and run [p]glint
        - Provide an image URL: [p]glint https://.../image.png
        - Attach an image and run [p]glint
        - Mention a user to use their avatar: [p]glint @SomeUser
        """
        image_bytes = None
        image_name = "glint.png"

        # 0) Mentioned user's avatar (first mention)
        if ctx.message.mentions:
            target = ctx.message.mentions[0]
            try:
                avatar = getattr(target, "display_avatar", None) or getattr(target, "avatar", None)
                if avatar:
                    try:
                        avatar_url = avatar.replace(size=1024).url
                    except Exception:
                        avatar_url = getattr(avatar, "url", None) or str(avatar)
                    if avatar_url:
                        image_bytes = await _fetch_bytes(avatar_url, ctx)
                        if image_bytes:
                            image_name = f"{target.id}_avatar.png"
            except Exception:
                image_bytes = None

        # 1) Attachments on the command message
        if image_bytes is None and ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            try:
                image_bytes = await attachment.read()
                image_name = attachment.filename or image_name
            except Exception:
                image_bytes = None

        # 2) Replied-to message attachments
        if image_bytes is None and ctx.message.reference:
            try:
                ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                if ref.attachments:
                    attachment = ref.attachments[0]
                    image_bytes = await attachment.read()
                    image_name = attachment.filename or image_name
            except Exception:
                pass

        # 3) URL in argument or message content
        if image_bytes is None:
            candidate_text = maybe_text or ""
            if not candidate_text:
                candidate_text = ctx.message.content or ""
            m = URL_RE.search(candidate_text)
            if m:
                url = m.group(0)
                image_bytes = await _fetch_bytes(url, ctx)
                if image_bytes:
                    image_name = url.split("/")[-1].split("?")[0] or image_name

        # 4) Nothing found -> error
        if image_bytes is None:
            await ctx.send(
                "Please attach an image, reply to a message with an image, mention a user to use their avatar, or provide an image URL."
            )
            return

        # Load image
        try:
            base_image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        except Exception:
            await ctx.send("Couldn't open the image. Make sure it's a valid image file.")
            return

        # Create session state (session_id ensures stable custom_ids)
        session = GlintSession(ctx, base_image, image_name)
        view = GlintEditorView(session, timeout=300)
        embed = session.make_embed("Editor opened - choose effects from the dropdown (selection applies immediately).", random_color=True)

        # Attach the initial image to the editor message so it can be edited in-place
        bio = io.BytesIO()
        base_image.convert("RGBA").save(bio, "PNG")
        bio.seek(0)
        file = discord.File(bio, filename=image_name)

        # Send the editor message (public). The view restricts interactions to the command user.
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


async def _fetch_bytes(url: str, ctx: commands.Context, timeout: int = 10) -> Optional[bytes]:
    """
    Robust helper to fetch bytes from a URL. Tries bot's internal session if available,
    otherwise uses aiohttp.ClientSession.
    """
    if not url.lower().startswith(("http://", "https://")):
        return None
    session_obj = None
    try:
        session_obj = getattr(ctx.bot.http, "_session", None)
    except Exception:
        session_obj = None

    try:
        if session_obj:
            async with session_obj.get(url, timeout=timeout) as resp:
                if resp.status == 200:
                    ctype = resp.headers.get("content-type", "")
                    if "image" in ctype or url.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                        return await resp.read()
                    return None
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=timeout) as resp:
                if resp.status == 200:
                    ctype = resp.headers.get("content-type", "")
                    if "image" in ctype or url.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                        return await resp.read()
    except Exception:
        return None
    return None


# Session and UI

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
        self.owner_id = ctx.author.id
        # stable session id used to build custom_id for components
        self.session_id = f"glint-{ctx.author.id}-{int(time.time())}-{uuid.uuid4().hex[:6]}"

    def set_message(self, message: discord.Message):
        self.message = message

    def _nice_embed_base(self, title: str, description: str, color: int) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color)
        try:
            icon_url = self.ctx.bot.user.display_avatar.replace(size=64).url
        except Exception:
            icon_url = getattr(self.ctx.bot.user, "avatar", None) or ""
        if icon_url:
            embed.set_author(name="Glint Image Editor", icon_url=icon_url)
        else:
            embed.set_author(name="Glint Image Editor")
        embed.set_footer(text="Select effects to apply immediately. Undo removes last. Finish posts final image.")
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
        bio = io.BytesIO()
        self.current_image.convert("RGBA").save(bio, "PNG")
        bio.seek(0)
        file = discord.File(bio, filename=self.filename)
        embed.set_image(url=f"attachment://{self.filename}")

        # Try to edit the original message and attach the updated image in-place.
        try:
            await self.message.edit(embed=embed, attachments=[file], view=view)
            return
        except Exception:
            pass

        # If attachments on edit are not supported, edit embed only (best-effort).
        try:
            await self.message.edit(embed=embed, view=view)
            return
        except Exception:
            pass

        # Last resort: send a new message with embed+file and update session.message to point to it,
        # then delete the old editor message to avoid duplicates (best-effort).
        try:
            new_msg = await self.message.channel.send(embed=embed, file=file, view=view)
            try:
                await self.message.delete()
            except Exception:
                pass
            self.message = new_msg
        except Exception:
            # If even that fails, silently ignore to avoid crashing the bot
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
        try:
            await self.ctx.send(embed=embed, file=file)
        except Exception:
            # If posting to the original channel fails, attempt to DM the user the final result instead
            try:
                await self.ctx.author.send(embed=embed, file=file)
            except Exception:
                pass
        self.finished = True


# UI View

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

        # Build stable custom_ids for components using session.session_id
        sid = self.session.session_id

        # Select (selecting applies immediately) - keep same object instance always
        options = _make_select_options()
        self.select = discord.ui.Select(
            placeholder="Choose effects (multi-select) - selection applies immediately",
            min_values=1,
            max_values=5,
            options=options,
            custom_id=f"{sid}:select",
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

        # Intensity controls (small buttons) with stable custom_ids
        self.decrease_button = discord.ui.Button(label="-", style=discord.ButtonStyle.secondary, row=1, custom_id=f"{sid}:dec")
        self.decrease_button.callback = self.decrease_intensity
        self.add_item(self.decrease_button)

        self.intensity_label = discord.ui.Button(label=f"{self.session.intensity}%", style=discord.ButtonStyle.gray, disabled=True, row=1, custom_id=f"{sid}:label")
        self.add_item(self.intensity_label)

        self.increase_button = discord.ui.Button(label="+", style=discord.ButtonStyle.secondary, row=1, custom_id=f"{sid}:inc")
        self.increase_button.callback = self.increase_intensity
        self.add_item(self.increase_button)

        # Action buttons
        self.undo_button = discord.ui.Button(label="Undo", style=discord.ButtonStyle.secondary, row=2, custom_id=f"{sid}:undo")
        self.undo_button.callback = self.undo_callback
        self.add_item(self.undo_button)

        self.finish_button = discord.ui.Button(label="Finish", style=discord.ButtonStyle.primary, row=2, custom_id=f"{sid}:finish")
        self.finish_button.callback = self.finish_callback
        self.add_item(self.finish_button)

        self.cancel_button = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger, row=2, custom_id=f"{sid}:cancel")
        self.cancel_button.callback = self.cancel_callback
        self.add_item(self.cancel_button)

    # Helper: ensure only the command user can interact with this view
    def _is_owner(self, user: discord.User) -> bool:
        return user.id == self.session.owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Prevent others from interacting; send ephemeral notice if not owner
        if not self._is_owner(interaction.user):
            try:
                await interaction.response.send_message("This editor session isn't yours.", ephemeral=True)
            except Exception:
                pass
            return False
        return True

    async def on_timeout(self) -> None:
        # Disable all components when the view times out and update the message
        for child in list(self.children):
            try:
                child.disabled = True
            except Exception:
                pass

        # Edit the message to reflect disabled controls and post final image if not already posted
        try:
            if self.session.message:
                await self.session.update_message(self, "Editor timed out; current image (controls disabled).")
        except Exception:
            pass
        # Post final result if not already posted
        if not self.session.finished:
            await self.session.finish_post(finalize=False)

    async def select_callback(self, interaction: discord.Interaction):
        # interaction_check already validated owner
        # Save the selected values (read-only property)
        self.selected_effects = list(self.select.values)
        # Acknowledge the interaction to avoid "This interaction failed"
        try:
            await interaction.response.defer()
        except Exception:
            pass

        # Immediately apply the selected effects
        if not self.selected_effects:
            return

        await self.session.apply_effects(self.selected_effects)
        # Update the editor message in-place (no extra public replies)
        await self.session.update_message(self, f"Applied: {', '.join(self.selected_effects)}")

        # Clear stored selection and reset the select options in-place (preferred)
        self.selected_effects = []
        try:
            # Reset the select's values to clear selection while keeping same object and custom_id
            self.select.values = []
            self.select.options = _make_select_options()
            self.select.placeholder = "Choose effects (multi-select) - selection applies immediately"
        except Exception:
            # If something goes wrong, don't recreate the select object; just ignore to avoid losing registration
            pass

    async def decrease_intensity(self, interaction: discord.Interaction):
        # interaction_check already validated owner
        self.session.intensity = max(10, self.session.intensity - 10)
        self.intensity_label.label = f"{self.session.intensity}%"
        await self.session.update_message(self, f"Intensity set to {self.session.intensity}%")
        try:
            await interaction.response.defer()
        except Exception:
            pass

    async def increase_intensity(self, interaction: discord.Interaction):
        # interaction_check already validated owner
        self.session.intensity = min(300, self.session.intensity + 10)
        self.intensity_label.label = f"{self.session.intensity}%"
        await self.session.update_message(self, f"Intensity set to {self.session.intensity}%")
        try:
            await interaction.response.defer()
        except Exception:
            pass

    async def undo_callback(self, interaction: discord.Interaction):
        # interaction_check already validated owner
        try:
            await interaction.response.defer()
        except Exception:
            pass
        undone = await self.session.undo()

        if not undone:
            return
        await self.session.update_message(self, "Undid last effect")
        # Do not send any followup or ephemeral message.

    async def finish_callback(self, interaction: discord.Interaction):
        # interaction_check already validated owner
        try:
            await interaction.response.defer()
        except Exception:
            pass
        # Disable all components immediately so users can't interact while posting
        for child in list(self.children):
            try:
                child.disabled = True
            except Exception:
                pass
        # Update the editor message to show controls disabled
        try:
            if self.session.message:
                await self.session.update_message(self, "Finishing and posting final image (controls disabled).")
        except Exception:
            pass
        await self.session.finish_post(finalize=True)
        self.stop()

    async def cancel_callback(self, interaction: discord.Interaction):
        # interaction_check already validated owner
        try:
            await interaction.response.defer()
        except Exception:
            pass

        # Disable all components immediately
        for child in list(self.children):
            try:
                child.disabled = True
            except Exception:
                pass

        try:
            if self.session.message:
                await self.session.update_message(self, "Editor closed without posting final image (controls disabled).")
        except Exception:
            pass
        self.stop()


# Image effect implementations (with intensity)

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
    gradient = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(gradient)
    max_dist = math.hypot(width / 2, height / 2)
    intensity_factor = min(1.0, (intensity / 100.0) * 1.5)
    for y in range(height):
        for x in range(width):
            dx = x - width / 2
            dy = y - height / 2
            d = math.hypot(dx, dy)
            t = (d / max_dist)
            intensity_val = int(255 * (t ** (1 + intensity_factor)))
            if intensity_val > 255:
                intensity_val = 255
            draw.point((x, y), fill=intensity_val)
    alpha = gradient.filter(ImageFilter.GaussianBlur(radius=max(1, min(width, height) // 20)))
    black = Image.new("RGBA", (width, height), (0, 0, 0, 255))
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


# Red cog setup (async)
async def setup(bot: commands.Bot):
    await bot.add_cog(Glint(bot))
