import io
import logging
import random
import re
from urllib.parse import urlparse
from typing import Optional, Union

from redbot.core import commands, Config, app_commands
import aiohttp
import discord

logger = logging.getLogger("red.cogs.imagefilter")

IMAGE_EFFECTS = ('blur', 'balls', 'abstract', '3d', 'ace', 'ads', 'bayer', 'bevel', 'billboard', 'blocks', 'boil', 'bomb', 'bonks', 'bubble', 'burn', 'canny', 'cartoon', 'cinema', 'clock', 'cloth', 'console', 'contour', 'cow', 'cracks', 'cube', 'dilate', 'dither', 'dizzy', 'dots', 'earthquake', 'emojify', 'endless', 'equations', 'explicit', 'fall', 'fan', 'fire', 'flag', 'flush', 'gallery', 'gameboy_camera', 'glitch', 'globe', 'half_invert', 'heart_diffraction', 'heart_locket', 'hearts', 'infinity', 'ipcam', 'kanye', 'knit', 'lamp', 'laundry', 'layers', 'letters', 'lines', 'liquefy', 'logoff', 'lsd', 'magnify', 'matrix', 'melt', 'minecraft', 'neon', 'optics', 'painting', 'paparazzi', 'patpat', 'pattern', 'phase', 'phone', 'pizza', 'plank', 'plates', 'poly', 'print', 'pyramid', 'quarter', 'radiate', 'rain', 'reflection', 'ripped', 'ripple', 'roll', 'scrapbook', 'sensitive', 'shear', 'shine', 'shock', 'shoot', 'shred', 'slice', 'soap', 'spikes', 'spin', 'stereo', 'stretch', 'tiles', 'tunnel', 'tv', 'wall', 'warp', 'wave', 'wiggle', 'zonk')
IMAGE_EFFECT_SET = frozenset(IMAGE_EFFECTS)


def _normalise_effect_name(value):
    return re.sub(r"[\s-]+", "_", (value or "").strip().casefold())


def _effect_label(value):
    if value == "3d":
        return "3D"
    return value.replace("_", " ").title()


async def _effect_autocomplete(interaction: discord.Interaction, current: str):
    query = (current or "").strip().casefold().replace("_", " ").replace("-", " ")
    names = list(IMAGE_EFFECTS)
    if query:
        def rank(name):
            label = _effect_label(name).casefold()
            normalised = name.replace("_", " ").casefold()
            if label.startswith(query) or normalised.startswith(query):
                return (0, name)
            if query in label or query in normalised:
                return (1, name)
            return (2, name)
        names = [name for name in names if query in _effect_label(name).casefold() or query in name.replace("_", " ").casefold()]
        names.sort(key=rank)
    else:
        names.sort(key=lambda name: _effect_label(name).casefold())
    return [app_commands.Choice(name=_effect_label(name), value=name) for name in names[:25]]


def _make_modal_field(label, **kwargs):
    if hasattr(discord.ui, "Label"):
        field = discord.ui.TextInput(**kwargs)
        return field, discord.ui.Label(text=label, component=field)
    field = discord.ui.TextInput(label=label, **kwargs)
    return field, field


class ImageFilterModal(discord.ui.Modal):
    def __init__(self, cog, owner_id: int, effect: str, default_target: str = ""):
        super().__init__(title="Image Filter")
        self.cog = cog
        self.owner_id = owner_id
        self.effect_input, effect_item = _make_modal_field(
            "Filter / effect",
            custom_id="imgmanip_effect",
            default=effect,
            placeholder="The effect you selected; you may edit it",
            min_length=1,
            max_length=80,
            required=True,
        )
        self.target_input, target_item = _make_modal_field(
            "Target user / ID / URL or text",
            custom_id="imgmanip_target",
            default=default_target or None,
            placeholder="Mention, user ID, image URL; text for ace/scrapbook",
            max_length=1000,
            required=False,
        )
        self.second_target_input, second_target_item = _make_modal_field(
            "Second target (heart_locket)",
            custom_id="imgmanip_target_2",
            placeholder="Optional; used by heart_locket",
            max_length=200,
            required=False,
        )
        self.add_item(effect_item)
        self.add_item(target_item)
        self.add_item(second_target_item)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This form belongs to another user.", ephemeral=True)
            return
        await self.cog._run_slash_effect(
            interaction,
            self.effect_input.value,
            self.target_input.value,
            self.second_target_input.value,
        )

BaseCog = getattr(commands, "Cog", object)

class ImageFilter(BaseCog):
    """Apply image effects using the Jeyy Image API: blur, balls, and abstract."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.config.register_user(api_key=None)


    @app_commands.command(name="imgmanip", description="Search for an image effect, then choose a target in a private form.")
    @app_commands.describe(
        effect="Search for a filter or effect",
        target_user="Optional user to target; you can also enter an ID in the modal",
    )
    @app_commands.autocomplete(effect=_effect_autocomplete)
    async def slash_imgmanip(
        self,
        interaction: discord.Interaction,
        effect: str,
        target_user: Optional[discord.User] = None,
    ):
        effect_name = _normalise_effect_name(effect)
        if effect_name not in IMAGE_EFFECT_SET:
            await interaction.response.send_message(
                "Choose an effect from the autocomplete suggestions when typing the effect name.",
                ephemeral=True,
            )
            return
        api_key = await self.config.user(interaction.user).api_key()
        if not api_key:
            await interaction.response.send_message(
                "Set your Jeyy API key first with the prefix command `[p]imgmanip setkey YOUR_KEY`, then run this slash command again.",
                ephemeral=True,
            )
            return
        default_target = ""
        if target_user is not None and effect_name not in ("ace", "scrapbook"):
            default_target = str(target_user.id)
        await interaction.response.send_modal(
            ImageFilterModal(self, interaction.user.id, effect_name, default_target=default_target)
        )

    @commands.group(name="imgmanip", invoke_without_command=True)
    async def imgmanip(self, ctx):
        """Group for Jeyy Image manipulation commands."""
        await ctx.send_help(ctx.command)

    @imgmanip.command(name="setkey")
    async def setkey(self, ctx, api_key: str):
        """Store your Jeyy API key."""
        await self.config.user(ctx.author).api_key.set(api_key)
        await ctx.send("✅ Your Jeyy API key has been saved.")

    async def _fetch(
        self,
        endpoint: str,
        api_key: str,
        method: str = "GET",
        params: dict = None,
        payload: dict = None,
    ) -> bytes:
        """Internal: call Jeyy API and return raw image bytes."""
        url = f"https://api.jeyy.xyz/{endpoint}"
        headers = {"Authorization": f"Bearer {api_key}"}
        async with aiohttp.ClientSession() as session:
            if method == "GET":
                async with session.get(url, params=params, headers=headers) as resp:
                    if resp.status != 200:
                        err = await resp.text()
                        logger.warning(f"Jeyy GET /{endpoint} failed: {resp.status} {err}")
                        raise RuntimeError(f"HTTP {resp.status}")
                    return await resp.read()
            else:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        err = await resp.text()
                        logger.warning(f"Jeyy POST /{endpoint} failed: {resp.status} {err}")
                        raise RuntimeError(f"HTTP {resp.status}")
                    return await resp.read()


    async def _resolve_slash_image(self, interaction: discord.Interaction, target: Optional[str], default_to_author: bool = True) -> Optional[str]:
        value = (target or "").strip()
        if not value:
            if not default_to_author:
                return None
            try:
                return interaction.user.display_avatar.url
            except Exception:
                return None

        parsed = urlparse(value)
        if parsed.scheme.casefold() in ("http", "https") and parsed.netloc:
            return value

        mention = re.fullmatch(r"<@!?(\d+)>", value)
        user_id = int(mention.group(1)) if mention else (int(value) if value.isdigit() else None)
        if user_id is None:
            return None

        user = None
        guild = interaction.guild
        if guild is not None:
            user = guild.get_member(user_id)
        if user is None:
            user = self.bot.get_user(user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(user_id)
            except (discord.HTTPException, discord.NotFound, discord.Forbidden):
                user = None
            except Exception:
                user = None
        if user is None:
            return None
        try:
            return user.display_avatar.url
        except Exception:
            return None

    @staticmethod
    def _is_upload_too_large(error: discord.HTTPException) -> bool:
        return (
            getattr(error, "status", None) == 413
            or getattr(error, "code", None) == 40005
            or "payload too large" in str(error).casefold()
        )

    @staticmethod
    def _upload_limit(interaction: discord.Interaction) -> int:
        limit = getattr(interaction, "filesize_limit", None)
        if isinstance(limit, int) and limit > 0:
            return limit
        guild = getattr(interaction, "guild", None)
        guild_limit = getattr(guild, "filesize_limit", None) if guild else None
        standard_limit = 20 * 1024 * 1024
        if isinstance(guild_limit, int) and guild_limit > 0:
            return max(standard_limit, guild_limit)
        return standard_limit

    @staticmethod
    def _compress_gif(data: bytes, quality: int) -> Optional[bytes]:
        try:
            from PIL import Image, ImageSequence
        except ImportError:
            return None

        settings = (
            (0.88, 256, 1),
            (0.76, 192, 1),
            (0.64, 128, 1),
            (0.54, 96, 2),
            (0.45, 80, 2),
            (0.37, 64, 3),
            (0.30, 48, 4),
            (0.23, 32, 5),
        )
        if quality < 0 or quality >= len(settings):
            return None

        try:
            source = Image.open(io.BytesIO(data))
            scale, colors, frame_step = settings[quality]
            width, height = source.size
            size = (max(1, int(width * scale)), max(1, int(height * scale)))
            durations = []
            frames = []
            frame_total = getattr(source, "n_frames", 1)
            source_durations = []
            for frame in ImageSequence.Iterator(source):
                source_durations.append(max(20, int(frame.info.get("duration", source.info.get("duration", 100)))))
            if not source_durations:
                source_durations = [100]
            selected_indices = list(range(0, frame_total, frame_step))
            for index in selected_indices:
                source.seek(index)
                frame = source.convert("RGB")
                resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", getattr(Image, "LANCZOS", 1))
                quantize_modes = getattr(Image, "Quantize", Image)
                quantize_method = getattr(quantize_modes, "MEDIANCUT", 0)
                if frame.size != size:
                    frame = frame.resize(size, resampling)
                frame = frame.quantize(colors=colors, method=quantize_method)
                frames.append(frame)
                durations.append(sum(source_durations[index:min(index + frame_step, frame_total)]))
            if not frames:
                return None
            output = io.BytesIO()
            frames[0].save(
                output,
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                loop=source.info.get("loop", 0),
                optimize=True,
                disposal=2,
            )
            return output.getvalue()
        except Exception:
            logger.exception("Could not compress generated GIF")
            return None

    async def _send_slash_result(self, interaction: discord.Interaction, effect_name: str, data: bytes) -> bool:
        channel = interaction.channel
        if channel is None or not hasattr(channel, "send"):
            await interaction.followup.send(
                "The effect finished, but I couldn't post the result in this channel.",
                ephemeral=True,
            )
            return False

        limit = self._upload_limit(interaction)
        last_error = None
        compressed_versions = 0
        for attempt in range(9):
            candidate = data if attempt == 0 else self._compress_gif(data, attempt - 1)
            if candidate is None:
                continue
            if attempt > 0:
                compressed_versions += 1
            try:
                await channel.send(
                    file=discord.File(io.BytesIO(candidate), filename=f"{effect_name}.gif"),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True
            except discord.HTTPException as error:
                last_error = error
                if not self._is_upload_too_large(error):
                    logger.exception("Discord rejected the generated image for effect %s", effect_name)
                    if getattr(error, "status", None) == 403 or getattr(error, "code", None) == 50013:
                        message = (
                            "I generated the image, but I don't have permission to upload files in this channel. "
                            "Give the bot **Send Messages** and **Attach Files** permission (or **Send Messages in Threads** if this is a thread)."
                        )
                    else:
                        message = (
                            f"I generated the image, but Discord rejected the upload (HTTP {getattr(error, 'status', 'unknown')}, "
                            f"error code {getattr(error, 'code', 'unknown')}). Check the channel permissions and server upload limit."
                        )
                    await interaction.followup.send(message, ephemeral=True)
                    return False
                if attempt == 0:
                    logger.warning(
                        "Image upload too large for effect %s: %s bytes; retrying with GIF compression (reported limit %s bytes)",
                        effect_name,
                        len(data),
                        limit,
                    )

        if last_error is not None:
            logger.error(
                "Discord refused the generated image after compression for effect %s",
                effect_name,
                exc_info=(type(last_error), last_error, last_error.__traceback__),
            )
        original_mib = len(data) / (1024 * 1024)
        limit_mib = limit / (1024 * 1024)
        if compressed_versions:
            message = (
                f"I generated the image, but Discord still rejected it after trying smaller GIF versions. "
                f"Original size: {original_mib:.1f} MiB; limit reported for this interaction: {limit_mib:.1f} MiB. "
                "Check that the bot has **Attach Files** permission in this channel. If it does, this effect may need a smaller source image."
            )
        else:
            message = (
                f"I generated the image, but it is too large for Discord to upload ({original_mib:.1f} MiB; "
                f"reported limit {limit_mib:.1f} MiB), and automatic GIF compression was unavailable. "
                "Install Pillow in the Redbot environment and try again, or use a smaller source image."
            )
        await interaction.followup.send(message, ephemeral=True)
        return False

    async def _run_slash_effect(self, interaction: discord.Interaction, effect: str, target: str = "", second_target: str = ""):
        effect_name = _normalise_effect_name(effect)
        if effect_name not in IMAGE_EFFECT_SET:
            matches = [name for name in IMAGE_EFFECTS if effect_name in name or name in effect_name] if effect_name else []
            suggestions = ", ".join(_effect_label(name) for name in matches[:8])
            message = "That effect was not found. Choose an effect from slash autocomplete."
            if suggestions:
                message += f" Possible matches: {suggestions}."
            await interaction.response.send_message(message, ephemeral=True)
            return

        api_key = await self.config.user(interaction.user).api_key()
        if not api_key:
            await interaction.response.send_message(
                "Your Jeyy API key is not set. Use `[p]imgmanip setkey YOUR_KEY` and try again.",
                ephemeral=True,
            )
            return

        target = (target or "").strip()
        second_target = (second_target or "").strip()
        if effect_name in ("ace", "scrapbook") and not target:
            await interaction.response.send_message("This effect needs text in the first input field.", ephemeral=True)
            return
        if effect_name == "heart_locket" and (not target or not second_target):
            await interaction.response.send_message(
                "Heart Locket needs two targets. Enter a user mention, user ID, or image URL in each target field.",
                ephemeral=True,
            )
            return

        app_permissions = getattr(interaction, "app_permissions", None)
        if app_permissions is not None:
            channel = interaction.channel
            is_thread = isinstance(channel, discord.Thread)
            can_send = getattr(app_permissions, "send_messages_in_threads", False) if is_thread else getattr(app_permissions, "send_messages", False)
            can_attach = getattr(app_permissions, "attach_files", False)
            if not can_send or not can_attach:
                missing = []
                if not can_send:
                    missing.append("Send Messages in Threads" if is_thread else "Send Messages")
                if not can_attach:
                    missing.append("Attach Files")
                await interaction.response.send_message(
                    "I can't post the finished image here because I am missing: **" + ", ".join(missing) + "**. "
                    "Update the bot's permissions for this channel and run the command again.",
                    ephemeral=True,
                )
                return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            if effect_name == "ace":
                attorneys = ["Jordan Blake", "Alexis Reed", "Taylor Quinn", "Morgan Flynn"]
                prosecutors = ["Casey Vaughn", "Riley Carter", "Jamie Lee", "Dakota Shore"]
                user = interaction.user
                display_name = getattr(user, "display_name", None) or getattr(user, "global_name", None) or user.name
                params = {
                    "name": display_name,
                    "attorney": random.choice(attorneys),
                    "prosecutor": random.choice(prosecutors),
                    "side": random.choice(["attorney", "prosecutor"]),
                    "text": target,
                }
            elif effect_name == "scrapbook":
                params = {"text": target}
            elif effect_name == "heart_locket":
                image_one = await self._resolve_slash_image(interaction, target, default_to_author=False)
                image_two = await self._resolve_slash_image(interaction, second_target, default_to_author=False)
                if not image_one or not image_two:
                    await interaction.followup.send(
                        "I couldn't resolve one of those targets. Use a valid mention, numeric user ID, or HTTP(S) image URL.",
                        ephemeral=True,
                    )
                    return
                params = {"image_url": image_one, "image_url_2": image_two}
            else:
                image_url = await self._resolve_slash_image(interaction, target, default_to_author=True)
                if not image_url:
                    await interaction.followup.send(
                        "I couldn't resolve that target. Use a user mention, numeric user ID, or HTTP(S) image URL.",
                        ephemeral=True,
                    )
                    return
                params = {"image_url": image_url}
                if effect_name == "bevel":
                    params["level"] = random.randint(10, 30)
                elif effect_name == "boil":
                    params["level"] = random.randint(1, 5)
                elif effect_name == "earthquake":
                    params["level"] = random.randint(1, 10)
                elif effect_name == "emojify":
                    params["size"] = random.randint(16, 64)
                elif effect_name == "glitch":
                    params["level"] = random.randint(1, 10)
                elif effect_name == "hearts":
                    params["rainbow"] = random.choice(["true", "false"])
                elif effect_name == "minecraft":
                    params["size"] = random.randint(10, 100)
                elif effect_name == "shear":
                    params["axis"] = random.choice(["x", "X", "y", "Y"])
                    params["x"] = round(random.uniform(-1.0, 1.0), 2)
                    params["y"] = round(random.uniform(-1.0, 1.0), 2)
                elif effect_name == "tiles":
                    params["n_edges"] = random.choice(["3", "4", "5", "6", "7", "8"])
                elif effect_name == "tunnel":
                    params["direction"] = random.choice(["h", "v", "c", "r"])
                elif effect_name == "wave":
                    params["frequency"] = round(random.uniform(0.01, 0.2), 3)
                    params["amplitude"] = random.choice(["1", "2", "3", "4", "5"])

            data = await self._fetch(
                endpoint=f"v2/image/{effect_name}",
                api_key=api_key,
                method="GET",
                params=params,
            )
        except Exception:
            logger.exception("Slash image effect failed: %s", effect_name)
            await interaction.followup.send(
                "I couldn't generate that effect. Check your Jeyy API key and try again.",
                ephemeral=True,
            )
            return

        uploaded = await self._send_slash_result(interaction, effect_name, data)
        if not uploaded:
            return
        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            logger.debug("Could not remove the private processing response for effect %s", effect_name, exc_info=True)

    async def _resolve_image_url(
        self,
        ctx: commands.Context,
        target: Optional[Union[discord.Member, str]]
    ) -> Optional[str]:
        """
        Resolve an image URL from:
        - Member or User object -> avatar
        - pasted numeric user id or mention -> avatar
        - http(s) URL string -> the URL itself
        - message attachments -> first attachment
        - fallback -> ctx.author avatar
        Returns None only if no avatar or attachment can be resolved.
        """
        # Direct Member/User
        if isinstance(target, (discord.Member, discord.User)):
            user = target
            try:
                return user.display_avatar.url
            except Exception:
                return None

        # If target is a string, try URL, mention, or user id
        if isinstance(target, str):
            s = target.strip()

            # direct http(s) url
            if s.lower().startswith("http"):
                return s

            # mention like <@123...> or <@!123...>
            if s.startswith("<@") and s.endswith(">"):
                s = s.strip("<@!>")

            # numeric id: try to resolve user
            if s.isdigit():
                user_id = int(s)
                member = None
                # try guild member first
                if ctx.guild:
                    member = ctx.guild.get_member(user_id)
                # try cache
                if not member:
                    member = self.bot.get_user(user_id)
                # fetch from API as last resort
                if not member:
                    try:
                        member = await self.bot.fetch_user(user_id)
                    except Exception:
                        member = None
                if member:
                    try:
                        return member.display_avatar.url
                    except Exception:
                        return None

        # attachments present
        if ctx.message and ctx.message.attachments:
            return ctx.message.attachments[0].url

        # fallback to invoking user avatar
        try:
            return ctx.author.display_avatar.url
        except Exception:
            return None


    @imgmanip.command(name="blur")
    async def blur(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Blur an image."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Blurring image…")
        try:
            data = await self._fetch(
                endpoint="v2/image/blur",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "blur.gif"))

    @imgmanip.command(name="balls")
    async def balls(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Balls filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Balls filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/balls",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "balls.gif"))

    @imgmanip.command(name="abstract")
    async def abstract(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Abstract v2 filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Abstract v2 filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/abstract",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "abstract.gif"))
        
    @imgmanip.command(name="3d")
    async def three_d(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply 3D filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying 3D filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/3d",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "3d.gif"))
        

    @imgmanip.command(name="ace")
    async def ace(self, ctx, *, text: str):
        """
        Generate an 'Ace' courtroom GIF.
        
        text        The line of dialogue to show in the speech bubble.
        """
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        name = ctx.author.display_name
        attorneys = ["Jordan Blake", "Alexis Reed", "Taylor Quinn", "Morgan Flynn"]
        prosecutors = ["Casey Vaughn", "Riley Carter", "Jamie Lee", "Dakota Shore"]
        # pick random roles
        attorney = random.choice(attorneys)
        prosecutor = random.choice(prosecutors)
        # side tells the API who’s speaking: 'attorney' or 'prosecutor'
        side = random.choice(["attorney", "prosecutor"])

        await ctx.send("🔄 Building Ace GIF…")
        try:
            data = await self._fetch(
                endpoint="v2/image/ace",
                api_key=api_key,
                method="GET",
                params={
                    "name": name,
                    "attorney": attorney,
                    "prosecutor": prosecutor,
                    "side": side,
                    "text": text,
                },
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "ace.gif"))
        
    @imgmanip.command(name="ads")
    async def ads(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Ads filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Ads filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/ads",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "ads.gif"))
        
    @imgmanip.command(name="bayer")
    async def bayer(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Bayer filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Bayer filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/bayer",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "bayer.gif"))

    @imgmanip.command(name="bevel")
    async def bevel(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Bevel filter with a random level."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        # Choose a random level between 10 and 30 inclusive
        level = random.randint(10, 30)

        await ctx.send(f"🔄 Applying Bevel filter… (level={level})")
        try:
            data = await self._fetch(
                endpoint="v2/image/bevel",
                api_key=api_key,
                method="GET",
                params={
                    "image_url": img_url,
                    "level": level,
                },
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "bevel.gif"))


    @imgmanip.command(name="billboard")
    async def billboard(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Billboard filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Billboard filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/billboard",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "billboard.gif"))

    @imgmanip.command(name="blocks")
    async def blocks(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Blocks filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Blocks filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/blocks",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "blocks.gif"))

    @imgmanip.command(name="boil")
    async def boil(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Boil filter with a random level."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        # Choose a random level between 1 and 5 inclusive
        level = random.randint(1, 5)

        await ctx.send(f"🔄 Applying Boil filter… (level={level})")
        try:
            data = await self._fetch(
                endpoint="v2/image/boil",
                api_key=api_key,
                method="GET",
                params={
                    "image_url": img_url,
                    "level": level,
                },
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "boil.gif"))


    @imgmanip.command(name="bomb")
    async def bomb(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Bomb filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Bomb filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/bomb",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "bomb.gif"))

    @imgmanip.command(name="bonks")
    async def bonks(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Bonks filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Bonks filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/bonks",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "bonks.gif"))

    @imgmanip.command(name="bubble")
    async def bubble(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Bubble filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Bubble filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/bubble",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "bubble.gif"))

    @imgmanip.command(name="burn")
    async def burn(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Burn filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Burn filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/burn",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "burn.gif"))

    @imgmanip.command(name="canny")
    async def canny(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Canny edge-detection filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Canny filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/canny",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "canny.gif"))

    @imgmanip.command(name="cartoon")
    async def cartoon(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Cartoon filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Cartoon filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/cartoon",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "cartoon.gif"))
        
    @imgmanip.command(name="cinema")
    async def cinema(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Cinema filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Cinema filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/cinema",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "cinema.gif"))

    @imgmanip.command(name="clock")
    async def clock(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Clock filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Clock filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/clock",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "clock.gif"))

    @imgmanip.command(name="cloth")
    async def cloth(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Cloth filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Cloth filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/cloth",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "cloth.gif"))

    @imgmanip.command(name="console")
    async def console(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Console filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Console filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/console",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "console.gif"))

    @imgmanip.command(name="contour")
    async def contour(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Contour filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Contour filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/contour",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "contour.gif"))

    @imgmanip.command(name="cow")
    async def cow(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Cow filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Cow filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/cow",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "cow.gif"))

    @imgmanip.command(name="cracks")
    async def cracks(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Cracks filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Cracks filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/cracks",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "cracks.gif"))

    @imgmanip.command(name="cube")
    async def cube(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Cube filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Cube filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/cube",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "cube.gif"))

    @imgmanip.command(name="dilate")
    async def dilate(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Dilate filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Dilate filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/dilate",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "dilate.gif"))

    @imgmanip.command(name="dither")
    async def dither(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Dither filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Dither filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/dither",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "dither.gif"))

    @imgmanip.command(name="dizzy")
    async def dizzy(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Dizzy filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Dizzy filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/dizzy",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "dizzy.gif"))

    @imgmanip.command(name="dots")
    async def dots(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Dots filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Dots filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/dots",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "dots.gif"))

    @imgmanip.command(name="earthquake")
    async def earthquake(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Earthquake filter with a random level."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        # Choose a random level between 1 and 10 inclusive
        level = random.randint(1, 10)

        await ctx.send(f"🔄 Applying Earthquake filter… (level={level})")
        try:
            data = await self._fetch(
                endpoint="v2/image/earthquake",
                api_key=api_key,
                method="GET",
                params={
                    "image_url": img_url,
                    "level": level,
                },
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "earthquake.gif"))


    @imgmanip.command(name="emojify")
    async def emojify(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Emojify filter with a random size."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        # Choose a random size between 16 and 64 inclusive
        size = random.randint(16, 64)

        await ctx.send(f"🔄 Applying Emojify filter… (size={size})")
        try:
            data = await self._fetch(
                endpoint="v2/image/emojify",
                api_key=api_key,
                method="GET",
                params={
                    "image_url": img_url,
                    "size": size,
                },
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "emojify.gif"))


    @imgmanip.command(name="endless")
    async def endless(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Endless filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Endless filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/endless",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "endless.gif"))

    @imgmanip.command(name="equations")
    async def equations(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Equations filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Equations filter…")

        try:
            data = await self._fetch(
                endpoint="v2/image/equations",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        # Check Discord’s upload cap for this channel/guild
        max_size = getattr(ctx.guild, "filesize_limit", 8 * 1024 * 1024)  # default 8MB

        # If the payload is too big, try to downscale the GIF
        if len(data) > max_size:
            try:
                from PIL import Image, ImageSequence

                orig = Image.open(io.BytesIO(data))
                frames = [frame.copy().convert("RGBA") for frame in ImageSequence.Iterator(orig)]
                w, h = frames[0].size

                # Compute a simple scale factor based on size ratio
                scale = (max_size / len(data)) ** 0.5
                new_size = (max(1, int(w * scale)), max(1, int(h * scale)))

                out = io.BytesIO()
                frames[0].save(
                    out,
                    format="GIF",
                    save_all=True,
                    append_images=frames[1:],
                    loop=0,
                    optimize=True,
                    duration=orig.info.get("duration", 100),
                )
                data = out.getvalue()
            except Exception:
                pass  # if resizing fails, we'll catch on send

        # Final send (may still error if resizing didn’t shrink enough)
        fp = io.BytesIO(data)
        fp.seek(0)
        try:
            await ctx.send(file=discord.File(fp, "equations.gif"))
        except discord.HTTPException as exc:
            if exc.code == 40005:  # Payload Too Large
                return await ctx.send(
                    "❌ The resulting GIF is too large to upload. "
                    "Try with a smaller image or lower resolution."
                )
            raise


    @imgmanip.command(name="explicit")
    async def explicit(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Explicit filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Explicit filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/explicit",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "explicit.gif"))

    @imgmanip.command(name="fall")
    async def fall(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Fall filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Fall filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/fall",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "fall.gif"))

    @imgmanip.command(name="fan")
    async def fan(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Fan filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Fan filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/fan",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "fan.gif"))

    @imgmanip.command(name="fire")
    async def fire(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Fire filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Fire filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/fire",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "fire.gif"))

    @imgmanip.command(name="flag")
    async def flag(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Flag filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Flag filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/flag",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "flag.gif"))

    @imgmanip.command(name="flush")
    async def flush(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Flush filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Flush filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/flush",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "flush.gif"))

    @imgmanip.command(name="gallery")
    async def gallery(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Gallery filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Gallery filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/gallery",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "gallery.gif"))

    @imgmanip.command(name="gameboy_camera")
    async def gameboy_camera(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Gameboy Camera filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Gameboy Camera filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/gameboy_camera",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "gameboy_camera.gif"))

    @imgmanip.command(name="glitch")
    async def glitch(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Glitch filter with a random level."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        # Choose a random level between 1 and 10 inclusive
        level = random.randint(1, 10)

        await ctx.send(f"🔄 Applying Glitch filter… (level={level})")
        try:
            data = await self._fetch(
                endpoint="v2/image/glitch",
                api_key=api_key,
                method="GET",
                params={
                    "image_url": img_url,
                    "level": level,
                },
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "glitch.gif"))


    @imgmanip.command(name="globe")
    async def globe(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Globe filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Globe filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/globe",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "globe.gif"))
        
    @imgmanip.command(name="half_invert")
    async def half_invert(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Half Invert filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Half Invert filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/half_invert",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "half_invert.gif"))

    @imgmanip.command(name="heart_diffraction")
    async def heart_diffraction(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Heart Diffraction filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        await ctx.send("🔄 Applying Heart Diffraction filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/heart_diffraction",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "heart_diffraction.gif"))

    @imgmanip.command(name="heart_locket")
    async def heart_locket(
        self,
        ctx,
        first: Optional[Union[discord.Member, str]] = None,
        second: Optional[Union[discord.Member, str]] = None,
    ):
        """Apply Heart Locket filter with two images."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        # 1) Gather attachments if no explicit args
        attachment_urls = [att.url for att in ctx.message.attachments]
        if not first and not second and len(attachment_urls) >= 2:
            img1, img2 = attachment_urls[:2]
        else:
            img1 = await self._resolve_image_url(ctx, first)
            img2 = await self._resolve_image_url(ctx, second)

        # 2) Ensure both images are provided
        if not img1 or not img2:
            return await ctx.send("❌ Please provide two images (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Heart Locket filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/heart_locket",
                api_key=api_key,
                method="GET",
                params={
                    "image_url": img1,
                    "image_url_2": img2,
                },
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "heart_locket.gif"))

    @imgmanip.command(name="hearts")
    async def hearts(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Hearts filter with random Rainbow value."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        # Pick a random rainbow value
        rainbow = random.choice(['true', 'false'])

        await ctx.send(f"🔄 Applying Hearts filter… (rainbow={rainbow})")
        try:
            data = await self._fetch(
                endpoint="v2/image/hearts",
                api_key=api_key,
                method="GET",
                params={
                    "image_url": img_url,
                    "rainbow": rainbow,
                },
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "hearts.gif"))


    @imgmanip.command(name="infinity")
    async def infinity(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Infinity filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Infinity filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/infinity",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "infinity.gif"))

    @imgmanip.command(name="ipcam")
    async def ipcam(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Ipcam filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Ipcam filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/ipcam",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "ipcam.gif"))

    @imgmanip.command(name="kanye")
    async def kanye(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Kanye filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Kanye filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/kanye",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "kanye.gif"))

    @imgmanip.command(name="knit")
    async def knit(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Knit filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Knit filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/knit",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "knit.gif"))

    @imgmanip.command(name="lamp")
    async def lamp(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Lamp filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Lamp filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/lamp",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "lamp.gif"))

    @imgmanip.command(name="laundry")
    async def laundry(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Laundry filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Laundry filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/laundry",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "laundry.gif"))

    @imgmanip.command(name="layers")
    async def layers(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Layers filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Layers filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/layers",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "layers.gif"))

    @imgmanip.command(name="letters")
    async def letters(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Letters filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Letters filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/letters",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "letters.gif"))

    @imgmanip.command(name="lines")
    async def lines(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Lines filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Lines filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/lines",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "lines.gif"))

    @imgmanip.command(name="liquefy")
    async def liquefy(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Liquefy filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Liquefy filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/liquefy",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "liquefy.gif"))

    @imgmanip.command(name="logoff")
    async def logoff(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Logoff filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Logoff filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/logoff",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "logoff.gif"))

    @imgmanip.command(name="lsd")
    async def lsd(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply LSD filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying LSD filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/lsd",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "lsd.gif"))

    @imgmanip.command(name="magnify")
    async def magnify(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Magnify filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Magnify filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/magnify",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "magnify.gif"))

    @imgmanip.command(name="matrix")
    async def matrix(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Matrix filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Matrix filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/matrix",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "matrix.gif"))

    @imgmanip.command(name="melt")
    async def melt(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Melt filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Melt filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/melt",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "melt.gif"))

    @imgmanip.command(name="minecraft")
    async def minecraft(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Minecraft filter with a random size."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        # Choose a random size between 10 and 100 inclusive
        size = random.randint(10, 100)

        await ctx.send(f"🔄 Applying Minecraft filter… (size={size})")
        try:
            data = await self._fetch(
                endpoint="v2/image/minecraft",
                api_key=api_key,
                method="GET",
                params={
                    "image_url": img_url,
                    "size": size,
                },
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "minecraft.gif"))


    @imgmanip.command(name="neon")
    async def neon(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Neon filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Neon filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/neon",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "neon.gif"))

    @imgmanip.command(name="optics")
    async def optics(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Optics filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Optics filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/optics",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "optics.gif"))

    @imgmanip.command(name="painting")
    async def painting(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Painting filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Painting filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/painting",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "painting.gif"))

    @imgmanip.command(name="paparazzi")
    async def paparazzi(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Paparazzi filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Paparazzi filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/paparazzi",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "paparazzi.gif"))

    @imgmanip.command(name="patpat")
    async def patpat(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Patpat filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Patpat filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/patpat",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "patpat.gif"))

    @imgmanip.command(name="pattern")
    async def pattern(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Pattern filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Pattern filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/pattern",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "pattern.gif"))

    @imgmanip.command(name="phase")
    async def phase(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Phase filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Phase filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/phase",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "phase.gif"))

    @imgmanip.command(name="phone")
    async def phone(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Phone filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Phone filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/phone",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "phone.gif"))

    @imgmanip.command(name="pizza")
    async def pizza(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Pizza filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Pizza filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/pizza",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "pizza.gif"))

    @imgmanip.command(name="plank")
    async def plank(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Plank filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Plank filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/plank",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "plank.gif"))

    @imgmanip.command(name="plates")
    async def plates(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Plates filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Plates filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/plates",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "plates.gif"))

    @imgmanip.command(name="poly")
    async def poly(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Poly filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Poly filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/poly",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "poly.gif"))

    @imgmanip.command(name="print")
    async def print(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Print filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Print filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/print",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "print.gif"))

    @imgmanip.command(name="pyramid")
    async def pyramid(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Pyramid filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Pyramid filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/pyramid",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "pyramid.gif"))

    @imgmanip.command(name="quarter")
    async def quarter(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Quarter filter using the API default size."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Quarter filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/quarter",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "quarter.gif"))




    @imgmanip.command(name="radiate")
    async def radiate(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Radiate filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Radiate filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/radiate",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "radiate.gif"))

    @imgmanip.command(name="rain")
    async def rain(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Rain filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Rain filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/rain",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "rain.gif"))

    @imgmanip.command(name="reflection")
    async def reflection(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Reflection filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Reflection filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/reflection",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "reflection.gif"))

    @imgmanip.command(name="ripped")
    async def ripped(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Ripped filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Ripped filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/ripped",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "ripped.gif"))

    @imgmanip.command(name="ripple")
    async def ripple(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Ripple filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Ripple filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/ripple",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "ripple.gif"))

    @imgmanip.command(name="roll")
    async def roll(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Roll filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Roll filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/roll",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "roll.gif"))

    @imgmanip.command(name="scrapbook")
    async def scrapbook(self, ctx, *, text: str):
        """Generate a scrapbook-style image from your text."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        if not text:
            return await ctx.send("❌ Please provide some text to generate the scrapbook image.")

        await ctx.send("🔄 Generating Scrapbook image…")
        try:
            data = await self._fetch(
                endpoint="v2/image/scrapbook",
                api_key=api_key,
                method="GET",
                params={"text": text},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error generating scrapbook: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "scrapbook.gif"))

    @imgmanip.command(name="sensitive")
    async def sensitive(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Sensitive filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Sensitive filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/sensitive",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "sensitive.gif"))

    @imgmanip.command(name="shear")
    async def shear(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Shear filter with random axis and offsets."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        # Pick a random axis and offsets
        axis = random.choice(['x', 'X', 'y', 'Y'])
        x_offset = round(random.uniform(-1.0, 1.0), 2)
        y_offset = round(random.uniform(-1.0, 1.0), 2)

        await ctx.send(f"🔄 Applying Shear filter… (axis={axis}, x={x_offset}, y={y_offset})")
        try:
            data = await self._fetch(
                endpoint="v2/image/shear",
                api_key=api_key,
                method="GET",
                params={
                    "image_url": img_url,
                    "axis": axis,
                    "x": x_offset,
                    "y": y_offset,
                },
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "shear.gif"))

    @imgmanip.command(name="shine")
    async def shine(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Shine filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Shine filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/shine",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "shine.gif"))

    @imgmanip.command(name="shock")
    async def shock(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Shock filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Shock filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/shock",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "shock.gif"))

    @imgmanip.command(name="shoot")
    async def shoot(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Shoot filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Shoot filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/shoot",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "shoot.gif"))

    @imgmanip.command(name="shred")
    async def shred(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Shred filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Shred filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/shred",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "shred.gif"))

    @imgmanip.command(name="slice")
    async def slice(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Slice filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Slice filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/slice",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "slice.gif"))

    @imgmanip.command(name="soap")
    async def soap(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Soap filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Soap filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/soap",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "soap.gif"))

    @imgmanip.command(name="spikes")
    async def spikes(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Spikes filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Spikes filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/spikes",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "spikes.gif"))

    @imgmanip.command(name="spin")
    async def spin(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Spin filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Spin filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/spin",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "spin.gif"))

    @imgmanip.command(name="stereo")
    async def stereo(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Stereo filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Stereo filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/stereo",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "stereo.gif"))

    @imgmanip.command(name="stretch")
    async def stretch(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Stretch filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Stretch filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/stretch",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "stretch.gif"))

    @imgmanip.command(name="tiles")
    async def tiles(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Tiles filter with a random n_edges."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        # Pick a random n_edges from the allowed values
        n_edges = random.choice(['3', '4', '5', '6', '7', '8'])

        await ctx.send(f"🔄 Applying Tiles filter… (n_edges={n_edges})")
        try:
            data = await self._fetch(
                endpoint="v2/image/tiles",
                api_key=api_key,
                method="GET",
                params={
                    "image_url": img_url,
                    "n_edges": n_edges,
                },
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "tiles.gif"))

    @imgmanip.command(name="tunnel")
    async def tunnel(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Tunnel filter with a random direction."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        # Pick a random direction from the allowed values
        direction = random.choice(['h', 'v', 'c', 'r'])

        await ctx.send(f"🔄 Applying Tunnel filter… (direction={direction})")
        try:
            data = await self._fetch(
                endpoint="v2/image/tunnel",
                api_key=api_key,
                method="GET",
                params={
                    "image_url": img_url,
                    "direction": direction,
                },
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "tunnel.gif"))

    @imgmanip.command(name="tv")
    async def tv(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Tv filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Tv filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/tv",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "tv.gif"))

    @imgmanip.command(name="wall")
    async def wall(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Wall filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Wall filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/wall",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "wall.gif"))

    @imgmanip.command(name="warp")
    async def warp(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Warp filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Warp filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/warp",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "warp.gif"))

    @imgmanip.command(name="wave")
    async def wave(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Wave filter with random frequency and amplitude."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        # Pick random values
        frequency = round(random.uniform(0.01, 0.20), 3)
        amplitude = random.choice(['1', '2', '3', '4', '5'])

        await ctx.send(f"🔄 Applying Wave filter… (frequency={frequency}, amplitude={amplitude})")
        try:
            data = await self._fetch(
                endpoint="v2/image/wave",
                api_key=api_key,
                method="GET",
                params={
                    "image_url": img_url,
                    "frequency": frequency,
                    "amplitude": amplitude,
                },
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "wave.gif"))

    @imgmanip.command(name="wiggle")
    async def wiggle(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Wiggle filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Wiggle filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/wiggle",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "wiggle.gif"))

    @imgmanip.command(name="zonk")
    async def zonk(self, ctx, target: Optional[Union[discord.Member, str]] = None):
        """Apply Zonk filter."""
        api_key = await self.config.user(ctx.author).api_key()
        if not api_key:
            return await ctx.send("❌ Set your API key: `[p]imgmanip setkey YOUR_KEY`.")

        img_url = await self._resolve_image_url(ctx, target)
        if not img_url:
            return await ctx.send("❌ Please provide an image (mention, URL, or attachment).")

        await ctx.send("🔄 Applying Zonk filter…")
        try:
            data = await self._fetch(
                endpoint="v2/image/zonk",
                api_key=api_key,
                method="GET",
                params={"image_url": img_url},
            )
        except Exception as e:
            return await ctx.send(f"❌ Error fetching filter: {e}")

        fp = io.BytesIO(data)
        fp.seek(0)
        await ctx.send(file=discord.File(fp, "zonk.gif"))



