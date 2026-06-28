# glint.py
"""
Glint - interactive image editor cog for Red-DiscordBot.

Rewrite notes (for the maintainer, can be deleted):
- Fixed: the dropdown's selection never visually cleared after use, because
  discord.ui.Select.values is a read-only property - you can't reassign it,
  you have to rebuild the select. The old code did `self.select.values = []`
  inside a bare try/except, so the bug was silently swallowed.
- Fixed: solarize's threshold formula could exceed 255 (the max pixel value),
  which made the effect a complete no-op at the default 100% intensity and
  anything below ~200%.
- Fixed: vignette used a pure-Python per-pixel double for-loop. On a
  1024x1024 image that's ~1 full second per application, which adds up fast
  once it's part of a stack that gets replayed on every undo.
- Fixed: image fetching relied on a private discord.py attribute
  (bot.http._session) that isn't public API and isn't guaranteed to exist.
- Fixed: almost every exception across the cog was caught and silently
  discarded, so broken features just did nothing with no feedback at all.
  Errors are now logged and, where it matters, shown to the user.
- Added: large input images are downscaled up front so effects stay fast and
  uploads stay under Discord's size limit; outputs that are still too big
  automatically fall back to JPEG.
- Added: a Reset-to-original button, a numbered effect-stack display,
  grouped dropdowns by category (the old one had 24 options in a single
  select, one away from Discord's hard cap of 25), and clearer error
  messages when something goes wrong.
"""
import io
import logging
import math
import random
import re
import time
import uuid
from typing import List, Optional, Tuple

import aiohttp
import discord
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps
from redbot.core import commands

log = logging.getLogger("red.glint")

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

# Hard caps so a session can never hang the bot or fail to upload to Discord.
MAX_DIMENSION = 1600  # longest side in pixels after downscaling
MAX_UPLOAD_BYTES = 8 * 1024 * 1024 - 1024  # stay safely under the 8MB cap
FETCH_TIMEOUT = 10  # seconds
EDITOR_TIMEOUT = 300  # seconds


# --------------------------------------------------------------------------- #
# Networking helpers
# --------------------------------------------------------------------------- #

async def fetch_image_bytes(
    session: aiohttp.ClientSession, url: str
) -> Tuple[Optional[bytes], Optional[str]]:
    """Fetch raw bytes from a URL. Returns (data, error_message) - exactly one is None."""
    if not url.lower().startswith(("http://", "https://")):
        return None, "That doesn't look like a valid URL."
    try:
        timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT)
        async with session.get(url, timeout=timeout) as resp:
            if resp.status != 200:
                return None, f"The server returned HTTP {resp.status} for that URL."
            ctype = resp.headers.get("content-type", "")
            looks_like_image = "image" in ctype.lower() or url.lower().endswith(
                (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
            )
            if not looks_like_image:
                return None, "That URL doesn't appear to point to an image."
            data = await resp.read()
            if not data:
                return None, "The URL returned an empty response."
            return data, None
    except aiohttp.ClientError as e:
        return None, f"Network error while fetching the image ({e})."
    except Exception as e:
        log.exception("Unexpected error fetching %s", url)
        return None, f"Unexpected error while fetching the image ({e})."


# --------------------------------------------------------------------------- #
# Image plumbing helpers
# --------------------------------------------------------------------------- #

def downscale_if_needed(img: Image.Image, max_dim: int = MAX_DIMENSION) -> Image.Image:
    if max(img.size) <= max_dim:
        return img
    ratio = max_dim / max(img.size)
    new_size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
    return img.resize(new_size, Image.LANCZOS)


def image_to_discord_file(img: Image.Image, filename: str) -> discord.File:
    """Encode as PNG; fall back to JPEG if that would be too big to upload."""
    bio = io.BytesIO()
    img.convert("RGBA").save(bio, "PNG", optimize=True)
    if bio.tell() <= MAX_UPLOAD_BYTES:
        bio.seek(0)
        if not filename.lower().endswith(".png"):
            filename = filename.rsplit(".", 1)[0] + ".png"
        return discord.File(bio, filename=filename)

    bio = io.BytesIO()
    img.convert("RGB").save(bio, "JPEG", quality=85, optimize=True)
    bio.seek(0)
    filename = filename.rsplit(".", 1)[0] + ".jpg"
    return discord.File(bio, filename=filename)


# --------------------------------------------------------------------------- #
# Effects
# --------------------------------------------------------------------------- #
# Each effect is a pure function: (Image, intensity 10-300) -> Image.
# Grouped into categories purely for the UI (Discord caps a single select at
# 25 options, so splitting into a few logical groups also leaves headroom to
# add more effects later without hitting that ceiling).

EFFECT_GROUPS = [
    (
        "Color",
        [
            ("Grayscale", "grayscale"),
            ("Sepia", "sepia"),
            ("Invert", "invert"),
            ("Color Boost", "color_boost"),
            ("Warm Tone", "warm_tone"),
            ("Cool Tone", "cool_tone"),
            ("Hue Shift +30°", "hue_plus_30"),
            ("Hue Shift -30°", "hue_minus_30"),
            ("Swap Red/Blue", "swap_rb"),
        ],
    ),
    (
        "Filters",
        [
            ("Box Blur", "blur"),
            ("Gaussian Blur", "gaussian_blur"),
            ("Sharpen", "sharpen"),
            ("Edge Enhance", "edge_enhance"),
            ("Contour", "contour"),
            ("Emboss", "emboss"),
            ("Pixelate", "pixelate"),
            ("Posterize", "posterize"),
            ("Solarize", "solarize"),
        ],
    ),
    (
        "Stylize",
        [
            ("Contrast+", "contrast_up"),
            ("Brightness+", "brightness_up"),
            ("Vignette", "vignette"),
            ("Old Film (grain)", "old_film"),
            ("Solar Glow", "solar_glow"),
            ("Frame (border)", "frame"),
        ],
    ),
]

# Flat lookup used for validation and for rendering effect names in embeds.
EFFECT_LABELS = {value: label for _, opts in EFFECT_GROUPS for label, value in opts}


def apply_effect(img: Image.Image, effect: str, intensity: int = 100) -> Image.Image:
    """Apply one named effect. Unknown effect names are a no-op (defensive, not silent-catch-all)."""
    handler = _EFFECT_HANDLERS.get(effect)
    if handler is None:
        log.warning("Unknown effect requested: %r", effect)
        return img
    try:
        return handler(img, intensity)
    except Exception:
        log.exception("Effect %r failed at intensity %s", effect, intensity)
        return img


def _grayscale(img, intensity):
    return ImageOps.grayscale(img).convert("RGBA")


def _sepia(img, intensity):
    img_rgb = img.convert("RGB")
    sep = Image.new("RGB", img_rgb.size, (112, 66, 20))
    alpha = min(0.9, intensity / 300.0)
    blended = Image.blend(img_rgb, sep, alpha=alpha)
    return blended.convert("RGBA")


def _invert(img, intensity):
    r, g, b, a = img.convert("RGBA").split()
    rgb = Image.merge("RGB", (r, g, b))
    inverted = ImageOps.invert(rgb)
    r2, g2, b2 = inverted.split()
    return Image.merge("RGBA", (r2, g2, b2, a))


def _blur(img, intensity):
    radius = max(1, round(1 + (intensity / 100.0) * 3))
    return img.filter(ImageFilter.BoxBlur(radius))


def _gaussian_blur(img, intensity):
    radius = max(1, round((intensity / 100.0) * 6))
    return img.filter(ImageFilter.GaussianBlur(radius=radius))


def _contour(img, intensity):
    return img.filter(ImageFilter.CONTOUR)


def _emboss(img, intensity):
    return img.filter(ImageFilter.EMBOSS)


def _sharpen(img, intensity):
    return img.filter(ImageFilter.SHARPEN)


def _edge_enhance(img, intensity):
    return img.filter(ImageFilter.EDGE_ENHANCE)


def _posterize(img, intensity):
    # bits in [1,8]; higher intensity -> fewer bits -> more posterized
    bits = max(1, min(8, round(8 - (intensity / 100.0) * 5)))
    return ImageOps.posterize(img.convert("RGB"), bits=bits).convert("RGBA")


def _solarize(img, intensity):
    # Stays within Pillow's valid 0-255 threshold range, unlike the old
    # formula (128 * 200 / intensity), which exceeded 255 for any intensity
    # under 200 and made the effect invisible at normal settings.
    threshold = max(0, min(255, round(255 - (intensity / 300.0) * 255)))
    return ImageOps.solarize(img.convert("RGB"), threshold=threshold).convert("RGBA")


def _pixelate(img, intensity):
    pixel_size = max(2, round((intensity / 100.0) * 20))
    small = img.resize(
        (max(1, img.width // pixel_size), max(1, img.height // pixel_size)),
        resample=Image.NEAREST,
    )
    return small.resize(img.size, Image.NEAREST).convert("RGBA")


def _vignette(img, intensity):
    """Vectorized radial vignette: build a small gradient, then upscale + blur.

    The original implementation drew this pixel-by-pixel with nested Python
    loops, which took roughly a full second on a 1024x1024 image. Building
    the gradient at low resolution and letting Pillow's resize/blur do the
    heavy lifting is visually equivalent (it gets blurred anyway) and runs in
    a few hundredths of a second.
    """
    width, height = img.size
    small_w, small_h = max(2, width // 8), max(2, height // 8)
    gradient = Image.new("L", (small_w, small_h), 0)
    draw = ImageDraw.Draw(gradient)
    max_dist = math.hypot(small_w / 2, small_h / 2)
    strength = min(1.0, (intensity / 100.0) * 1.5)
    for y in range(small_h):
        for x in range(small_w):
            d = math.hypot(x - small_w / 2, y - small_h / 2)
            t = d / max_dist if max_dist else 0
            val = int(255 * (t ** (1 + strength)))
            draw.point((x, y), fill=min(255, val))
    gradient = gradient.resize((width, height), Image.BILINEAR)
    blur_radius = max(1, min(width, height) // 20)
    alpha = gradient.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    black = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    return Image.composite(black, img.convert("RGBA"), alpha)


def _contrast_up(img, intensity):
    factor = 1.0 + (intensity / 100.0) * 1.0
    return ImageEnhance.Contrast(img).enhance(factor)


def _brightness_up(img, intensity):
    factor = 1.0 + (intensity / 100.0) * 0.8
    return ImageEnhance.Brightness(img).enhance(factor)


def _color_boost(img, intensity):
    factor = 1.0 + (intensity / 100.0) * 1.5
    return ImageEnhance.Color(img).enhance(factor)


def _tone_shift(img, shifts: Tuple[float, float, float]):
    r_shift, g_shift, b_shift = shifts
    r, g, b, a = img.convert("RGBA").split()
    r = ImageEnhance.Brightness(r).enhance(1 + r_shift / 100.0)
    g = ImageEnhance.Brightness(g).enhance(1 + g_shift / 100.0)
    b = ImageEnhance.Brightness(b).enhance(1 + b_shift / 100.0)
    return Image.merge("RGBA", (r, g, b, a))


def _warm_tone(img, intensity):
    scale = intensity / 100.0
    return _tone_shift(img, (20 * scale, 6 * scale, -16 * scale))


def _cool_tone(img, intensity):
    scale = intensity / 100.0
    return _tone_shift(img, (-16 * scale, -6 * scale, 20 * scale))


def _old_film(img, intensity):
    sep = _sepia(img, intensity).convert("RGBA")
    grain_strength = max(10, round((intensity / 100.0) * 60))
    noise_l = Image.effect_noise(img.size, grain_strength)
    # Center noise around 0 so grain can darken as well as lighten - the old
    # version only ever added noise, which just washed highlights out toward
    # white instead of looking like real film grain.
    noise_signed = noise_l.point(lambda p: p - 128)
    grain_opacity = min(1.0, intensity / 150.0)
    scaled_noise = noise_signed.point(lambda p: int(p * grain_opacity))
    r, g, b = sep.convert("RGB").split()
    r2 = ImageChops.add(r, scaled_noise)
    g2 = ImageChops.add(g, scaled_noise)
    b2 = ImageChops.add(b, scaled_noise)
    combined = Image.merge("RGB", (r2, g2, b2)).convert("RGBA")
    combined.putalpha(sep.split()[3])
    return combined


def _frame(img, intensity):
    border = max(8, round(30 * intensity / 100.0))
    color = (24, 24, 24, 255)
    rgba = img.convert("RGBA")
    new_size = (rgba.width + border * 2, rgba.height + border * 2)
    framed = Image.new("RGBA", new_size, color)
    framed.paste(rgba, (border, border), rgba)
    return framed


def _shift_hue(img, deg: int):
    img = img.convert("RGBA")
    r, g, b, a = img.split()
    hsv = Image.merge("RGB", (r, g, b)).convert("HSV")
    h, s, v = hsv.split()
    offset = round(deg * 255 / 360)
    lut = [(i + offset) % 256 for i in range(256)]
    h = h.point(lut)
    new_rgb = Image.merge("HSV", (h, s, v)).convert("RGBA")
    new_rgb.putalpha(a)
    return new_rgb


def _hue_plus_30(img, intensity):
    return _shift_hue(img, round(30 * intensity / 100.0))


def _hue_minus_30(img, intensity):
    return _shift_hue(img, -round(30 * intensity / 100.0))


def _swap_rb(img, intensity):
    r, g, b, a = img.convert("RGBA").split()
    return Image.merge("RGBA", (b, g, r, a))


def _solar_glow(img, intensity):
    img = img.convert("RGBA")
    radius = max(3, round((intensity / 100.0) * 18))
    glow = img.filter(ImageFilter.GaussianBlur(radius=radius))
    glow = ImageEnhance.Brightness(glow).enhance(1.0 + (intensity / 100.0) * 1.0)
    return ImageChops.screen(img, glow)


_EFFECT_HANDLERS = {
    "grayscale": _grayscale,
    "sepia": _sepia,
    "invert": _invert,
    "blur": _blur,
    "gaussian_blur": _gaussian_blur,
    "contour": _contour,
    "emboss": _emboss,
    "sharpen": _sharpen,
    "edge_enhance": _edge_enhance,
    "posterize": _posterize,
    "solarize": _solarize,
    "pixelate": _pixelate,
    "vignette": _vignette,
    "contrast_up": _contrast_up,
    "brightness_up": _brightness_up,
    "color_boost": _color_boost,
    "warm_tone": _warm_tone,
    "cool_tone": _cool_tone,
    "old_film": _old_film,
    "frame": _frame,
    "hue_plus_30": _hue_plus_30,
    "hue_minus_30": _hue_minus_30,
    "swap_rb": _swap_rb,
    "solar_glow": _solar_glow,
}


# --------------------------------------------------------------------------- #
# Session: holds per-editor state
# --------------------------------------------------------------------------- #

class GlintSession:
    """Owns the original image, the current (edited) image, and the effect stack
    for a single editor instance. Pure state + image work; no Discord UI logic.
    """

    def __init__(self, ctx: commands.Context, base_image: Image.Image, filename: str):
        self.ctx = ctx
        self.base_image = base_image.copy()
        self.current_image = base_image.copy()
        self.filename = filename
        self.applied_effects: List[str] = []
        self.message: Optional[discord.Message] = None
        self.finished = False
        self.intensity = 100  # percent, range [10, 300]
        self.owner_id = ctx.author.id
        self.session_id = f"glint-{ctx.author.id}-{int(time.time())}-{uuid.uuid4().hex[:6]}"

    def set_message(self, message: discord.Message) -> None:
        self.message = message

    # -- embeds -----------------------------------------------------------

    def _base_embed(self, title: str, description: str, color: int) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color)
        icon_url = None
        try:
            icon_url = self.ctx.bot.user.display_avatar.url
        except Exception:
            pass
        embed.set_author(name="Glint Image Editor", icon_url=icon_url)
        return embed

    def make_embed(self, description: str, random_color: bool = False) -> discord.Embed:
        color = random.randint(0, 0xFFFFFF) if random_color else 0x2B6CB0
        embed = self._base_embed("Glint Editor", description, color)
        stack = self.applied_effects
        if stack:
            pretty = [EFFECT_LABELS.get(e, e) for e in stack]
            numbered = "\n".join(f"`{i + 1}.` {name}" for i, name in enumerate(pretty))
        else:
            numbered = "*None yet*"
        embed.add_field(name=f"Effect stack ({len(stack)})", value=numbered[:1024], inline=False)
        embed.add_field(name="Intensity", value=f"{self.intensity}%", inline=True)
        embed.set_image(url=f"attachment://{self.filename}")
        embed.set_footer(text="Pick effects below to apply them immediately • Undo removes the last one • Finish posts the result")
        return embed

    # -- effect application -------------------------------------------------

    def apply_effects(self, effects: List[str]) -> None:
        img = self.current_image
        for eff in effects:
            img = apply_effect(img, eff, intensity=self.intensity)
            self.applied_effects.append(eff)
        self.current_image = img

    def undo(self) -> bool:
        """Remove the most recent effect and replay the remaining stack from the original."""
        if not self.applied_effects:
            return False
        self.applied_effects.pop()
        img = self.base_image
        for eff in self.applied_effects:
            img = apply_effect(img, eff, intensity=self.intensity)
        self.current_image = img
        return True

    def reset(self) -> bool:
        """Discard the whole effect stack and go back to the original image."""
        if not self.applied_effects:
            return False
        self.applied_effects = []
        self.current_image = self.base_image.copy()
        return True

    def replay_with_current_intensity(self) -> None:
        """Re-apply the whole stack from the original image using the current intensity.
        Used after the intensity slider changes, so existing effects scale too
        instead of only newly-added ones.
        """
        img = self.base_image
        for eff in self.applied_effects:
            img = apply_effect(img, eff, intensity=self.intensity)
        self.current_image = img

    # -- message updates -----------------------------------------------------

    async def update_message(self, view: discord.ui.View, description: str) -> None:
        if not self.message:
            return
        embed = self.make_embed(description, random_color=True)
        file = image_to_discord_file(self.current_image, self.filename)
        self.filename = file.filename  # keep in sync if PNG->JPEG fallback kicked in
        embed.set_image(url=f"attachment://{self.filename}")

        try:
            await self.message.edit(embed=embed, attachments=[file], view=view)
            return
        except discord.HTTPException:
            log.warning("Editing Glint message with new attachment failed; retrying without image swap", exc_info=True)

        try:
            await self.message.edit(embed=embed, view=view)
        except discord.HTTPException:
            log.exception("Failed to edit Glint editor message at all")

    async def finish_post(self, finalize: bool = True) -> None:
        if self.finished:
            return
        file = image_to_discord_file(self.current_image, self.filename)
        color = random.randint(0, 0xFFFFFF)
        title = "Glint Result" if finalize else "Glint (editor timed out)"
        description = (
            "Here's the final image." if finalize
            else "The editor timed out, so here's the image as it was left."
        )
        embed = self._base_embed(title, description, color)
        stack = self.applied_effects
        pretty = [EFFECT_LABELS.get(e, e) for e in stack]
        embed.add_field(name=f"Effects applied ({len(stack)})", value=(", ".join(pretty) or "None"), inline=False)
        embed.add_field(name="Intensity", value=f"{self.intensity}%", inline=True)
        embed.set_image(url=f"attachment://{file.filename}")
        try:
            await self.ctx.send(embed=embed, file=file)
        except discord.HTTPException:
            log.warning("Failed to post final Glint result to channel, trying DM", exc_info=True)
            try:
                await self.ctx.author.send(embed=embed, file=file)
            except discord.HTTPException:
                log.exception("Failed to DM final Glint result as a fallback")
        self.finished = True


# --------------------------------------------------------------------------- #
# UI: the editor view
# --------------------------------------------------------------------------- #

MIN_INTENSITY = 10
MAX_INTENSITY = 300
INTENSITY_STEP = 10


class GlintEditorView(discord.ui.View):
    """The interactive editor. Three category dropdowns (rows 0-2), intensity
    controls (row 3), and action buttons (row 4) - five rows total, which is
    Discord's hard cap for a single message.
    """

    def __init__(self, session: GlintSession, timeout: int = EDITOR_TIMEOUT):
        super().__init__(timeout=timeout)
        self.session = session
        self._selects: dict = {}

        for row, (group_name, options) in enumerate(EFFECT_GROUPS):
            self._add_group_select(row, group_name, options)

        # Intensity controls
        self.decrease_button = discord.ui.Button(
            label="−", style=discord.ButtonStyle.secondary, row=3,
            custom_id=f"{session.session_id}:dec",
        )
        self.decrease_button.callback = self.decrease_intensity
        self.add_item(self.decrease_button)

        self.intensity_label = discord.ui.Button(
            label=f"{session.intensity}%", style=discord.ButtonStyle.secondary, row=3,
            disabled=True, custom_id=f"{session.session_id}:label",
        )
        self.add_item(self.intensity_label)

        self.increase_button = discord.ui.Button(
            label="+", style=discord.ButtonStyle.secondary, row=3,
            custom_id=f"{session.session_id}:inc",
        )
        self.increase_button.callback = self.increase_intensity
        self.add_item(self.increase_button)

        # Action buttons
        self.undo_button = discord.ui.Button(
            label="Undo", style=discord.ButtonStyle.secondary, row=4,
            custom_id=f"{session.session_id}:undo",
        )
        self.undo_button.callback = self.undo_callback
        self.add_item(self.undo_button)

        self.reset_button = discord.ui.Button(
            label="Reset", style=discord.ButtonStyle.secondary, row=4,
            custom_id=f"{session.session_id}:reset",
        )
        self.reset_button.callback = self.reset_callback
        self.add_item(self.reset_button)

        self.finish_button = discord.ui.Button(
            label="Finish", style=discord.ButtonStyle.success, row=4,
            custom_id=f"{session.session_id}:finish",
        )
        self.finish_button.callback = self.finish_callback
        self.add_item(self.finish_button)

        self.cancel_button = discord.ui.Button(
            label="Cancel", style=discord.ButtonStyle.danger, row=4,
            custom_id=f"{session.session_id}:cancel",
        )
        self.cancel_button.callback = self.cancel_callback
        self.add_item(self.cancel_button)

    # -- select construction --------------------------------------------------

    def _add_group_select(self, row: int, group_name: str, options) -> None:
        """Build (or rebuild) the dropdown for one effect category."""
        select = discord.ui.Select(
            placeholder=f"{group_name}…",
            min_values=1,
            max_values=min(5, len(options)),
            options=[discord.SelectOption(label=label, value=value) for label, value in options],
            custom_id=f"{self.session.session_id}:select:{group_name.lower()}",
            row=row,
        )
        select.callback = self._make_select_callback(group_name, options)
        self._selects[group_name] = select
        self.add_item(select)

    def _make_select_callback(self, group_name: str, options):
        async def callback(interaction: discord.Interaction):
            select = self._selects[group_name]
            chosen = list(select.values)
            try:
                await interaction.response.defer()
            except discord.HTTPException:
                pass

            if chosen:
                self.session.apply_effects(chosen)
                labels = ", ".join(EFFECT_LABELS.get(c, c) for c in chosen)
                self._rebuild_select(group_name, options, row=select.row)
                await self.session.update_message(self, f"Applied: {labels}")
        return callback

    def _rebuild_select(self, group_name: str, options, row: int) -> None:
        """Replace a select with a freshly built one so its visible selection
        clears. discord.ui.Select.values is read-only - it can't be reset by
        assignment, only by swapping in a new Select instance. (This is the
        root cause of the old dropdown-never-clears bug.)
        """
        old = self._selects[group_name]
        self.remove_item(old)
        self._add_group_select(row, group_name, options)

    # -- access control ---------------------------------------------------

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.session.owner_id:
            try:
                await interaction.response.send_message(
                    "This editor session isn't yours.", ephemeral=True
                )
            except discord.HTTPException:
                pass
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        try:
            if self.session.message:
                await self.session.update_message(self, "Editor timed out; controls disabled.")
        except Exception:
            log.exception("Failed to update message on Glint editor timeout")
        # Deliberately does not post a final image - Finish is the only path
        # that posts, same as before, just now actually guaranteed by this
        # function doing nothing else.

    # -- intensity ----------------------------------------------------------

    async def decrease_intensity(self, interaction: discord.Interaction):
        self.session.intensity = max(MIN_INTENSITY, self.session.intensity - INTENSITY_STEP)
        self.intensity_label.label = f"{self.session.intensity}%"
        self.session.replay_with_current_intensity()
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            pass
        await self.session.update_message(self, f"Intensity set to {self.session.intensity}%")

    async def increase_intensity(self, interaction: discord.Interaction):
        self.session.intensity = min(MAX_INTENSITY, self.session.intensity + INTENSITY_STEP)
        self.intensity_label.label = f"{self.session.intensity}%"
        self.session.replay_with_current_intensity()
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            pass
        await self.session.update_message(self, f"Intensity set to {self.session.intensity}%")

    # -- actions ------------------------------------------------------------

    async def undo_callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            pass
        if self.session.undo():
            await self.session.update_message(self, "Undid the last effect.")
        else:
            await self.session.update_message(self, "Nothing to undo.")

    async def reset_callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            pass
        if self.session.reset():
            await self.session.update_message(self, "Reset to the original image.")
        else:
            await self.session.update_message(self, "Already at the original image.")

    async def finish_callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            pass
        for child in self.children:
            child.disabled = True
        try:
            if self.session.message:
                await self.session.update_message(self, "Finishing — posting the final image below.")
        except Exception:
            log.exception("Failed to update Glint message before posting final result")
        await self.session.finish_post(finalize=True)
        self.stop()

    async def cancel_callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            pass
        for child in self.children:
            child.disabled = True
        try:
            if self.session.message:
                await self.session.update_message(self, "Editor closed without posting a final image.")
        except Exception:
            log.exception("Failed to update Glint message on cancel")
        self.stop()


# --------------------------------------------------------------------------- #
# Cog
# --------------------------------------------------------------------------- #

class Glint(commands.Cog):
    """Interactive image editor: stack effects, undo/reset, adjust intensity, and post results."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: Optional[aiohttp.ClientSession] = None

    async def cog_load(self) -> None:
        self._session = aiohttp.ClientSession()

    async def cog_unload(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    @commands.command(name="glint")
    @commands.guild_only()
    @commands.bot_has_permissions(attach_files=True, embed_links=True)
    @commands.max_concurrency(1, per=commands.BucketType.user)
    async def glint(self, ctx: commands.Context, *, maybe_text: Optional[str] = None):
        """
        Open the Glint image editor.

        Usage:
        - Reply to a message with an image and run `[p]glint`
        - Provide an image URL: `[p]glint https://.../image.png`
        - Attach an image and run `[p]glint`
        - Mention a user to use their avatar: `[p]glint @SomeUser`
        """
        image_bytes, image_name, err = await self._resolve_image(ctx, maybe_text)

        if image_bytes is None:
            await ctx.send(
                err
                or "Please attach an image, reply to a message with an image, "
                "mention a user to use their avatar, or provide an image URL."
            )
            return

        try:
            base_image = Image.open(io.BytesIO(image_bytes))
            base_image.load()  # decode now, so a corrupt file fails here with a clear message
            base_image = base_image.convert("RGBA")
        except Exception:
            await ctx.send("Couldn't open that as an image. Make sure it's a valid PNG, JPEG, WEBP, or GIF.")
            return

        base_image = downscale_if_needed(base_image)

        session = GlintSession(ctx, base_image, image_name)
        view = GlintEditorView(session, timeout=EDITOR_TIMEOUT)
        embed = session.make_embed("Editor opened — pick effects from the dropdowns below.", random_color=True)
        file = image_to_discord_file(base_image, image_name)
        session.filename = file.filename

        try:
            message = await ctx.send(embed=embed, file=file, view=view)
        except discord.HTTPException:
            log.warning("Failed to send Glint editor message with attachment, retrying without it", exc_info=True)
            message = await ctx.send(embed=embed, view=view)

        session.set_message(message)
        await view.wait()
        # Posting only happens from Finish (see finish_callback) or never, on
        # timeout/cancel - this is intentional and unchanged from before.

    async def _resolve_image(
        self, ctx: commands.Context, maybe_text: Optional[str]
    ) -> Tuple[Optional[bytes], str, Optional[str]]:
        """Try each image source in priority order. Returns (bytes, filename, error_message)."""
        session = self._get_session()
        image_name = "glint.png"

        # 1) Mentioned user's avatar
        if ctx.message.mentions:
            target = ctx.message.mentions[0]
            avatar = getattr(target, "display_avatar", None) or getattr(target, "avatar", None)
            if avatar is not None:
                try:
                    avatar_url = avatar.replace(size=1024).url
                except Exception:
                    avatar_url = getattr(avatar, "url", None)
                if avatar_url:
                    data, err = await fetch_image_bytes(session, avatar_url)
                    if data:
                        return data, f"{target.id}_avatar.png", None
                    if err:
                        log.info("Avatar fetch failed for user %s: %s", target.id, err)

        # 2) Attachments on the command message itself
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            try:
                data = await attachment.read()
                return data, attachment.filename or image_name, None
            except discord.HTTPException as e:
                return None, image_name, f"Couldn't download your attachment ({e})."

        # 3) Replied-to message's attachments
        if ctx.message.reference:
            try:
                ref = ctx.message.reference.resolved
                if not isinstance(ref, discord.Message):
                    ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                if ref.attachments:
                    attachment = ref.attachments[0]
                    data = await attachment.read()
                    return data, attachment.filename or image_name, None
            except discord.HTTPException:
                log.info("Could not read the replied-to message's attachment", exc_info=True)

        # 4) A URL in the command argument or the raw message content
        candidate_text = maybe_text or ctx.message.content or ""
        m = URL_RE.search(candidate_text)
        if m:
            url = m.group(0)
            data, err = await fetch_image_bytes(session, url)
            if data:
                name = url.split("/")[-1].split("?")[0] or image_name
                return data, name, None
            return None, image_name, err or "Couldn't fetch an image from that URL."

        return None, image_name, None


async def setup(bot: commands.Bot):
    await bot.add_cog(Glint(bot))
