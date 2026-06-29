import asyncio
import random
import io
import math
import logging
import aiosqlite
import regex as re
from datetime import datetime

import discord
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import aiohttp
from collections import OrderedDict
from wordcloud import WordCloud

from pathlib import Path
from redbot.core.data_manager import cog_data_path
from redbot.core import commands, checks
from discord.ext import tasks
from redbot.core.bot import Red

log = logging.getLogger("red.wordcloud")

# Basic stopwords
STOPWORDS = {
    "the", "and", "for", "that", "with", "you", "this", "have", "are",
    "but", "not", "was", "from", "they", "she", "he", "it", "in", "on",
    "a", "an", "of", "to", "is", "i", "we", "me", "my", "our", "be",
    "as", "at", "by", "or", "if", "so", "do", "did", "does", "got",
}

# Emoji regexes
# Matches a single emoji "character" within a grapheme cluster (used together
# with GRAPHEME_RE below so skin-tone modifiers, ZWJ sequences like family
# emoji, flags, and keycaps (3️⃣) are grouped into one token instead of being
# split into several).
UNICODE_EMOJI_RE = re.compile(
    r'(\p{Emoji_Presentation}|\p{Emoji}\uFE0F|\p{Emoji}(?=\u20E3))'
)
# Splits text into grapheme clusters (user-perceived "characters"). Combined
# with UNICODE_EMOJI_RE, this lets us detect whole emoji clusters atomically.
GRAPHEME_RE = re.compile(r"\X")
CUSTOM_EMOJI_RE = re.compile(r"<a?:([a-zA-Z0-9_]+):([0-9]{17,22})>")

# Words only
WORD_REGEX = re.compile(r"\b[^\W\d_]{2,}\b", flags=re.UNICODE)

def is_emoji_token(token: str) -> bool:
    """True for custom Discord emoji tokens or unicode emoji clusters."""
    if token.startswith("custom_"):
        return True
    return UNICODE_EMOJI_RE.match(token) is not None

def random_color_func(word, font_size, position, orientation, random_state=None, **kwargs):
    return "rgb({}, {}, {})".format(
        random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)
    )

def build_shape_mask(shape: str, width: int, height: int):
    """Build a numpy mask array for WordCloud's `mask` parameter.

    WordCloud treats pure-white (255,255,255) pixels as "no text here" and
    any other pixel as fillable area, so we draw a solid black shape on a
    white background. Returns None for "none"/unrecognized shapes (no mask).
    """
    if not shape or shape == "none":
        return None

    img = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(img)
    cx, cy = width / 2, height / 2

    if shape == "circle":
        r = min(width, height) / 2 * 0.95
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=0)
    elif shape == "square":
        s = min(width, height) * 0.95
        draw.rectangle([cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2], fill=0)
    elif shape == "triangle":
        h = height * 0.95
        w = h * 1.1
        pts = [(cx, cy - h / 2), (cx - w / 2, cy + h / 2), (cx + w / 2, cy + h / 2)]
        draw.polygon(pts, fill=0)
    elif shape == "star":
        outer = min(width, height) / 2 * 0.95
        inner = outer * 0.4
        pts = []
        for i in range(10):
            ang = (math.pi / 2) + i * (math.pi / 5)
            r = outer if i % 2 == 0 else inner
            pts.append((cx + r * math.cos(ang), cy - r * math.sin(ang)))
        draw.polygon(pts, fill=0)
    elif shape == "heart":
        pts = []
        for t in range(0, 360, 2):
            a = math.radians(t)
            x = 16 * math.sin(a) ** 3
            y = 13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)
            pts.append((x, y))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        scale = min(width / (maxx - minx), height / (maxy - miny)) * 0.9
        pts2 = [
            (cx + (x - (minx + maxx) / 2) * scale, cy - (y - (miny + maxy) / 2) * scale)
            for x, y in pts
        ]
        draw.polygon(pts2, fill=0)
    else:
        return None

    return np.array(img)

class WordCloudCog(commands.Cog):
    AVAILABLE_SHAPES = ("none", "circle", "square", "triangle", "star", "heart")

    def __init__(self, bot: Red):
        self.bot = bot
        self.db_ready = False

        self._session: aiohttp.ClientSession | None = None
        self._emoji_cache: OrderedDict[str, Image.Image] = OrderedDict()
        self._cache_max = 200

        # Where to store our SQLite DB
        data_folder = Path(cog_data_path(self))
        data_folder.mkdir(parents=True, exist_ok=True)
        self.db_path = str(data_folder / "wordcloud_data.sqlite3")

    async def cog_load(self):
        await self._ensure_db()
        self._session = aiohttp.ClientSession()
        self.autogen_loop.start()

    def cog_unload(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
    
        if loop:
            loop.create_task(self._shutdown())
        else:
            try:
                if self.autogen_loop.is_running():
                    self.autogen_loop.cancel()
                    task = getattr(self.autogen_loop, "_task", None)
                    if task:
                        try:
                            task.cancel()
                        except Exception:
                            pass
            except Exception:
                pass
    
    async def _shutdown(self):
        try:
            if self.autogen_loop.is_running():
                self.autogen_loop.cancel()
            task = getattr(self.autogen_loop, "_task", None)
            if task:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        except Exception:
            pass
    
        
        if getattr(self, "_session", None) is not None:
            try:
                await self._session.close()
            except Exception:
                pass
    

    async def _ensure_db(self):
        # Create tables and add 'mask' column if missing
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    "ALTER TABLE config ADD COLUMN mask TEXT DEFAULT 'none'"
                )
                await db.commit()
            except aiosqlite.OperationalError:
                pass

    async def init_db(self):
        if self.db_ready:
            return
        async with aiosqlite.connect(self.db_path) as db:
            # WAL lets writes (incoming messages) proceed while a long-running
            # read is open elsewhere (e.g. the autogen loop scanning counts and
            # rendering an image), instead of queuing behind the default
            # rollback-journal lock until the 5s busy_timeout expires.
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                """CREATE TABLE IF NOT EXISTS counts (
                     guild_id INTEGER,
                     user_id INTEGER,
                     token TEXT,
                     count INTEGER,
                     PRIMARY KEY (guild_id, user_id, token)
                   )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS config (
                    guild_id         INTEGER PRIMARY KEY,
                    autogen          INTEGER DEFAULT 0,
                    autogen_interval INTEGER DEFAULT 3600,
                    autogen_channel  INTEGER,
                    mask             TEXT    DEFAULT 'none'
                )"""
            )            
            await db.execute(
                """CREATE TABLE IF NOT EXISTS ignored_channels (
                     guild_id   INTEGER,
                     channel_id INTEGER,
                     PRIMARY KEY (guild_id, channel_id)
                   )"""
            )
            await db.commit()
            try:
                await db.execute(
                    "ALTER TABLE config ADD COLUMN mask TEXT DEFAULT 'none'"
                )
                await db.commit()
            except aiosqlite.OperationalError:
                # column already exists, or older SQLite without support—ignore
                pass
                
        self.db_ready = True

    async def _get_mask_for_guild(self, guild_id: int) -> str:
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT mask FROM config WHERE guild_id = ?", (guild_id,)
            )
            row = await cur.fetchone()
        return row[0] if row else "none"

    ###########################################################################
    # Data collection
    ###########################################################################

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        await self.init_db()
        # skip ignored
        async with aiosqlite.connect(self.db_path, timeout=10) as db:
            cur = await db.execute(
                "SELECT 1 FROM ignored_channels WHERE guild_id = ? AND channel_id = ?",
                (message.guild.id, message.channel.id),
            )
            if await cur.fetchone():
                return

        raw = message.content or ""
        tokens = []

        # custom emojis, e.g. <:pog:123456789012345678>
        def repl_custom(m):
            name, eid = m.groups()
            tokens.append(f"custom_{name}:{eid}")
            return " "
        text = CUSTOM_EMOJI_RE.sub(repl_custom, raw)

        # unicode emojis — walk grapheme clusters so multi-codepoint emoji
        # (skin tones, ZWJ family sequences, flags, keycaps like 3️⃣) are kept
        # together as a single token instead of being split apart.
        remaining_chars = []
        for cluster in GRAPHEME_RE.findall(text):
            if UNICODE_EMOJI_RE.search(cluster):
                tokens.append(cluster)
            else:
                remaining_chars.append(cluster)
        text = "".join(remaining_chars)

        # words
        for m in WORD_REGEX.finditer(text.lower()):
            w = m.group(0)
            if w in STOPWORDS:
                continue
            tokens.append(w)

        if tokens:
            await self._increment_tokens(message.guild.id, message.author.id, tokens)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.abc.User):
        if user.bot or not reaction.message.guild:
            return
        await self.init_db()
        # skip ignored
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT 1 FROM ignored_channels WHERE guild_id = ? AND channel_id = ?",
                (reaction.message.guild.id, reaction.message.channel.id),
            )
            if await cur.fetchone():
                return

        e = reaction.emoji
        if isinstance(e, str):
            token = e
        else:
            token = (
                f"custom_{e.name}:{e.id}"
                if getattr(e, "id", None)
                else f"custom_{e.name}:none"
            )
        await self._increment_tokens(reaction.message.guild.id, user.id, [token])

    async def _increment_tokens(self, guild_id: int, user_id: int, tokens: list):
        await self.init_db()
        norm = [str(t)[:200] for t in tokens if t]
        if not norm:
            return

        # Retry on transient "database is locked" contention instead of
        # letting it bubble up into discord.py's generic on_message error
        # handler, where it gets logged once and the tokens are gone for
        # good with no obvious sign anything was missed.
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                async with aiosqlite.connect(self.db_path, timeout=10) as db:
                    cur = await db.cursor()
                    for t in norm:
                        await cur.execute(
                            """
                            INSERT INTO counts(guild_id, user_id, token, count)
                            VALUES(?, ?, ?, 1)
                            ON CONFLICT(guild_id, user_id, token)
                            DO UPDATE SET count = count + 1
                            """,
                            (guild_id, user_id, t),
                        )
                    await db.commit()
                return
            except aiosqlite.OperationalError:
                if attempt == attempts:
                    log.exception(
                        "Giving up writing token counts for guild=%s user=%s after %d attempts",
                        guild_id, user_id, attempts,
                    )
                    return
                await asyncio.sleep(0.25 * attempt)
            except Exception:
                log.exception(
                    "Unexpected error writing token counts for guild=%s user=%s",
                    guild_id, user_id,
                )
                return

    async def _get_frequencies_for_guild(self, guild_id: int):
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                SELECT token, SUM(count) as count
                FROM counts
                WHERE guild_id = ?
                GROUP BY token
                ORDER BY count DESC
                """,
                (guild_id,),
            )
            rows = await cur.fetchall()
        return {r[0]: r[1] for r in rows}

    async def _get_frequencies_for_user(self, guild_id: int, user_id: int):
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                SELECT token, count
                FROM counts
                WHERE guild_id = ? AND user_id = ?
                ORDER BY count DESC
                """,
                (guild_id, user_id),
            )
            rows = await cur.fetchall()
        return {r[0]: r[1] for r in rows}

    async def _get_frequencies_for_users(self, guild_id: int, user_ids: list):
        if not user_ids:
            return {}
        await self.init_db()
        placeholders = ",".join("?" for _ in user_ids)
        params = [guild_id] + user_ids
        query = f"""
            SELECT token, SUM(count) as count
            FROM counts
            WHERE guild_id = ? AND user_id IN ({placeholders})
            GROUP BY token
            ORDER BY count DESC
        """
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(query, params)
            rows = await cur.fetchall()
        return {r[0]: r[1] for r in rows}

    ###########################################################################
    # Rendering
    ###########################################################################
    async def _render_wordcloud_image(
        self,
        frequencies: dict,
        mask_name: str = None,
        width: int = 1200,
        height: int = 675,
    ):
        buf = io.BytesIO()
        if not frequencies:
            img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            img.save(buf, format="PNG")
            buf.seek(0)
            return buf

        mask = build_shape_mask(mask_name, width, height)

        wc_kwargs = {
            "width": width,
            "height": height,
            "margin": 0,
            "mode": "RGBA",
            "background_color": None,
            "prefer_horizontal": 0.9,
            "collocations": False,
            # Compresses the gap between the biggest and smallest font sizes
            # so a few very frequent tokens don't dominate the canvas and
            # leave large empty gaps around them; smaller words fill in
            # tighter as a result. 'auto'/1.0 (the wordcloud default) is
            # closer to true-proportional sizing but leaves much more
            # whitespace on Zipfian-distributed chat data.
            "relative_scaling": 0.5,
        }
        if mask is not None:
            wc_kwargs["mask"] = mask

        # WordCloud sizes each placeholder's font from the LENGTH of its
        # token string, not its frequency rank. Custom-emoji tokens like
        # "custom_pog:123456789012345678" are long, so they'd be sized as if
        # they were a long word and come out tiny regardless of how often
        # they were used. Swap every emoji token for a short fixed-length
        # surrogate before generating the layout, then map back to the real
        # token afterwards, so font size reflects frequency correctly.
        surrogate_to_token = {}
        display_freqs = {}
        counter = 0
        for token, count in frequencies.items():
            if is_emoji_token(token):
                # A single Private-Use-Area character. Every PUA codepoint
                # renders with the font's .notdef fallback glyph, which is
                # roughly square — much closer to square than a multi-char
                # placeholder (a 4-char string like "\ue000123" renders as a
                # wide ~3.3:1 rectangle, not the font_size x font_size square
                # we used to assume when pasting, which is what let emoji
                # spill into neighboring words/outside mask shapes).
                surrogate = chr(0xE000 + counter)
                surrogate_to_token[surrogate] = token
                display_freqs[surrogate] = count
                counter += 1
            else:
                display_freqs[token] = count

        wc = WordCloud(**wc_kwargs)
        wc.generate_from_frequencies(display_freqs)
        wc.recolor(
            color_func=lambda word, font_size, position, orientation, random_state=None, **kwargs: (
                "rgba(0,0,0,0)" if word in surrogate_to_token
                else random_color_func(word, font_size, position, orientation)
            ),
            random_state=42,
        )

        # split layout into words vs emojis (mapping surrogates back to the
        # real token so the rest of the pipeline never sees placeholders)
        full_layout = wc.layout_
        word_entries, emoji_entries = [], []
        for entry in full_layout:
            raw = entry[0]
            surrogate = raw[0] if isinstance(raw, tuple) else raw
            real_token = surrogate_to_token.get(surrogate)
            if real_token is not None:
                fixed_entry = (real_token,) + entry[1:]
                emoji_entries.append(fixed_entry)
            else:
                word_entries.append(entry)

        # render words only; the space reserved for emoji during layout
        # stays blank here and gets filled in by the paste step below
        wc.layout_ = word_entries
        base_img = wc.to_image().convert("RGBA")

        try:
            resample = Image.Resampling.LANCZOS
        except AttributeError:
            resample = Image.LANCZOS

        # The exact pixel box WordCloud reserved for a surrogate at a given
        # font_size comes from draw.textbbox(..., anchor="lt") — see
        # WordCloud.generate_from_frequencies, which samples placement using
        # exactly this box. Critically, the box's height is NOT font_size;
        # a font's nominal point size includes internal leading the glyph's
        # ink doesn't fill, so the real reserved height is only a fraction
        # of font_size (around ~0.71x for this font). Treating box_h as
        # font_size directly overstated the reserved box by ~40%, which is
        # exactly what let a large, frequent emoji visually bleed past its
        # actual slot into neighboring words. All PUA codepoints share the
        # same fallback glyph, so the two ratios only need measuring once.
        _img_grey = Image.new("L", (1, 1))
        _draw = ImageDraw.Draw(_img_grey)
        _ref_font = ImageFont.truetype(wc.font_path, 100)
        _ref_box = _draw.textbbox((0, 0), chr(0xE000), font=_ref_font, anchor="lt")
        w_ratio = (_ref_box[2] - _ref_box[0]) / 100
        h_ratio = (_ref_box[3] - _ref_box[1]) / 100

        # Emoji are rendered a bit smaller than the box reserved for them
        # (which stays full-size for layout/spacing purposes) so they don't
        # visually dominate text of the same frequency rank.
        EMOJI_SCALE = 0.75

        # overlay emojis
        for entry in emoji_entries:
            token, font_size, position, orientation, _color = entry

            box_w = max(1, int(font_size * w_ratio))
            box_h = max(1, int(font_size * h_ratio))
            target_w = max(1, int(box_w * EMOJI_SCALE))
            target_h = max(1, int(box_h * EMOJI_SCALE))

            # build URL + cache key
            if token.startswith("custom_"):
                _, rest = token.split("custom_", 1)
                _, eid = rest.split(":", 1)
                urls = [f"https://cdn.discordapp.com/emojis/{eid}.png?size=64"]
                key = f"custom:{eid}"
            else:
                cps_full = "-".join(f"{ord(c):x}" for c in token)
                # Twemoji's asset filenames inconsistently drop trailing
                # variation-selector (fe0f) codepoints, so try the exact
                # codepoint sequence first and fall back to the version
                # with trailing fe0f parts stripped.
                cps_stripped = "-".join(
                    part for part in cps_full.split("-") if part != "fe0f"
                )
                urls = [
                    f"https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72/{cps_full}.png"
                ]
                if cps_stripped != cps_full:
                    urls.append(
                        f"https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72/{cps_stripped}.png"
                    )
                key = f"unicode:{cps_full}"

            # fetch or reuse — cache key includes the target box size since
            # the same emoji can be requested at very different sizes
            cache_key = f"{key}@{target_w}x{target_h}in{box_w}x{box_h}"
            if cache_key in self._emoji_cache:
                em = self._emoji_cache[cache_key]
                self._emoji_cache.move_to_end(cache_key)
            else:
                em = None
                for url in urls:
                    try:
                        async with self._session.get(url) as resp:
                            if resp.status != 200:
                                continue
                            data = await resp.read()
                            em = Image.open(io.BytesIO(data)).convert("RGBA")
                            break
                    except Exception:
                        continue
                if em is None:
                    continue
                # Fit the (usually square) emoji image inside its shrunk
                # target size without distorting it: scale to the largest
                # size that fits both dimensions, then center it on a
                # transparent canvas the size of the full reserved box (so
                # it still lines up with the slot WordCloud allocated, just
                # smaller within it). A plain stretch-to-box would visibly
                # squash square emoji images into a non-square box anyway.
                src_w, src_h = em.size
                scale = min(target_w / src_w, target_h / src_h)
                fit_w, fit_h = max(1, int(src_w * scale)), max(1, int(src_h * scale))
                em_resized = em.resize((fit_w, fit_h), resample)
                canvas = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
                canvas.paste(
                    em_resized,
                    ((box_w - fit_w) // 2, (box_h - fit_h) // 2),
                    em_resized,
                )
                em = canvas
                self._emoji_cache[cache_key] = em
                if len(self._emoji_cache) > self._cache_max:
                    self._emoji_cache.popitem(last=False)

            # paste — `position` from WordCloud's layout_ is (row, col) i.e.
            # (top, left), but PIL's Image.paste() box argument is (left,
            # top). Pasting at (row, col) directly — as if it were already
            # (left, top) — silently transposes every placement, which is
            # why emoji used to land on top of text or outside mask shapes
            # instead of in the gap actually reserved for them.
            row, col = position
            left, top = col, row
            base_img.paste(em, (int(left), int(top)), em)

        base_img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    ###########################################################################
    # Autogen loop
    ###########################################################################

    @tasks.loop(minutes=1)
    async def autogen_loop(self):
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT guild_id, autogen_interval, autogen_channel, mask "
                "FROM config WHERE autogen = 1"
            )
            rows = await cur.fetchall()

        for guild_id, interval, channel_id, mask_name in rows:
            key = f"last_autogen_{guild_id}"
            last = getattr(self, key, None)
            now = datetime.utcnow()
            if last is None or (now - last).total_seconds() >= interval:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue
                ch = guild.get_channel(channel_id) if channel_id else None
                if not ch:
                    for c in guild.text_channels:
                        if c.permissions_for(guild.me).send_messages:
                            ch = c
                            break
                if not ch:
                    continue
                freqs = await self._get_frequencies_for_guild(guild_id)
                buf = await self._render_wordcloud_image(freqs, mask_name=mask_name)
                try:
                    await ch.send(file=discord.File(fp=buf, filename="wordcloud.png"))
                except Exception:
                    pass
                setattr(self, key, now)

    @autogen_loop.before_loop
    async def before_autogen(self):
        await self.bot.wait_until_ready()

    ###########################################################################
    # Commands
    ###########################################################################

    @commands.group(invoke_without_command=True)
    async def wordcloud(self, ctx: commands.Context):
        """Wordcloud management."""
        await ctx.send_help()

    @wordcloud.command(name="shape")
    @checks.admin()
    async def shape(self, ctx: commands.Context, shape: str = None):
        """View or set the wordcloud shape. Available: none, circle, square, triangle, star, heart."""
        current = await self._get_mask_for_guild(ctx.guild.id)
        if not shape:
            await ctx.send(
                f"Current shape: **{current}**\n"
                f"Available shapes: {', '.join(self.AVAILABLE_SHAPES)}"
            )
            return

        shape = shape.lower()
        if shape not in self.AVAILABLE_SHAPES:
            return await ctx.send(f"Invalid shape. Choose from: {', '.join(self.AVAILABLE_SHAPES)}")

        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO config(guild_id, mask) VALUES(?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET mask = ?",
                (ctx.guild.id, shape, shape),
            )
            await db.commit()
        await ctx.send(f"Wordcloud shape set to **{shape}**.")

    @wordcloud.command(name="ignore")
    @checks.admin()
    async def ignore(self, ctx, channel: discord.TextChannel):
        """Ignore a channel from data collection."""
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO ignored_channels(guild_id, channel_id) VALUES(?, ?)",
                (ctx.guild.id, channel.id),
            )
            await db.commit()
        await ctx.send(f"Ignoring {channel.mention}.")

    @wordcloud.command(name="unignore")
    @checks.admin()
    async def unignore(self, ctx, channel: discord.TextChannel):
        """Resume data collection in a channel."""
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM ignored_channels WHERE guild_id = ? AND channel_id = ?",
                (ctx.guild.id, channel.id),
            )
            await db.commit()
        await ctx.send(f"Resumed collection in {channel.mention}.")

    @wordcloud.command(name="ignored")
    @checks.admin()
    async def ignored(self, ctx: commands.Context):
        """List all ignored channels."""
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT channel_id FROM ignored_channels WHERE guild_id = ?",
                (ctx.guild.id,),
            )
            rows = await cur.fetchall()
        if not rows:
            return await ctx.send("No ignored channels.")
        mentions = []
        for (cid,) in rows:
            ch = ctx.guild.get_channel(cid)
            mentions.append(ch.mention if ch else f"<#{cid}>")
        await ctx.send("Ignored channels: " + ", ".join(mentions))

    @wordcloud.command(name="generate")
    async def generate(self, ctx: commands.Context, *members: discord.Member):
        """Generate a wordcloud. No args=all, mention users to limit."""
        if not members:
            freqs = await self._get_frequencies_for_guild(ctx.guild.id)
            title = f"Guild cloud: {ctx.guild.name}"
        elif len(members) == 1:
            freqs = await self._get_frequencies_for_user(ctx.guild.id, members[0].id)
            title = f"User cloud: {members[0].display_name}"
        else:
            ids = [m.id for m in members]
            freqs = await self._get_frequencies_for_users(ctx.guild.id, ids)
            names = ", ".join(m.display_name for m in members)
            title = f"Cloud for: {names}"

        if not freqs:
            return await ctx.send("No data to generate.")

        shape = await self._get_mask_for_guild(ctx.guild.id)
        buf = await self._render_wordcloud_image(freqs, mask_name=shape)
        await ctx.send(content=title, file=discord.File(fp=buf, filename="wordcloud.png"))

    @wordcloud.command(name="me")
    async def me(self, ctx: commands.Context):
        """Your personal wordcloud."""
        freqs = await self._get_frequencies_for_user(ctx.guild.id, ctx.author.id)
        if not freqs:
            return await ctx.send("No data for you yet.")
        shape = await self._get_mask_for_guild(ctx.guild.id)
        buf = await self._render_wordcloud_image(freqs, mask_name=shape)
        await ctx.send(
            f"Wordcloud for {ctx.author.display_name}",
            file=discord.File(fp=buf, filename="wordcloud.png"),
        )

    @wordcloud.command(name="stats")
    async def stats(self, ctx: commands.Context, limit: int = 20):
        """Show top words & emojis by reactions."""
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT token, SUM(count) as c FROM counts "
                "WHERE guild_id = ? GROUP BY token ORDER BY c DESC",
                (ctx.guild.id,),
            )
            rows = await cur.fetchall()
        if not rows:
            return await ctx.send("No data yet.")

        def disp(tok):
            if tok.startswith("custom_"):
                name, eid = tok.split("custom_", 1)[1].split(":", 1)
                return f"<:{name}:{eid}>"
            return tok

        # Rank words and emoji independently so a guild with far more word
        # volume than emoji volume doesn't starve the emoji list out of a
        # single combined top-N before the split happens.
        emojis = [(disp(tok), cnt) for tok, cnt in rows if is_emoji_token(tok)][:limit]
        words  = [(tok, cnt) for tok, cnt in rows if not is_emoji_token(tok)][:limit]

        e_emb = discord.Embed(
            title="📊 Top Emojis",
            description="\n".join(f"{t}: {c}" for t, c in emojis) or "None",
        )
        w_emb = discord.Embed(
            title="📊 Top Words",
            description="\n".join(f"{t}: {c}" for t, c in words) or "None",
        )
        pages = [e_emb, w_emb]
        msg = await ctx.send(embed=pages[0])
        await msg.add_reaction("◀️")
        await msg.add_reaction("▶️")

        def check(r, u):
            return u == ctx.author and r.message.id == msg.id and str(r.emoji) in ("◀️","▶️")

        idx = 0
        try:
            while True:
                r, u = await self.bot.wait_for("reaction_add", timeout=60, check=check)
                idx = (idx + (1 if r.emoji == "▶️" else -1)) % len(pages)
                await msg.edit(embed=pages[idx])
                await msg.remove_reaction(r.emoji, u)
        except asyncio.TimeoutError:
            try:
                await msg.clear_reactions()
            except:
                pass
                
    @wordcloud.command()
    @checks.admin()
    async def reset(self, ctx: commands.Context):
        """Reset stored counts for this guild."""
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM counts WHERE guild_id = ?", (ctx.guild.id,))
            await db.commit()
        await ctx.send("Word counts reset for this guild.")

    @wordcloud.command()
    @checks.admin()
    async def set_autogen(self, ctx: commands.Context, enabled: bool):
        """Enable or disable periodic generation."""
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO config(guild_id, autogen) VALUES(?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET autogen = ?",
                (ctx.guild.id, int(enabled), int(enabled)),
            )
            await db.commit()
        await ctx.send(f"Autogen set to {enabled}.")

    @wordcloud.command()
    @checks.admin()
    async def set_autogen_channel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Set channel where autogen will post. If omitted, uses the current channel."""
        ch = channel or ctx.channel
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO config(guild_id, autogen_channel) VALUES(?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET autogen_channel = ?",
                (ctx.guild.id, ch.id, ch.id),
            )
            await db.commit()
        await ctx.send(f"Autogen channel set to {ch.mention}.")

    @wordcloud.command()
    @checks.admin()
    async def set_autogen_interval(self, ctx: commands.Context, seconds: int):
        """Set autogen interval in seconds (minimum 60)."""
        if seconds < 60:
            return await ctx.send("Interval must be at least 60 seconds.")
        await self.init_db()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO config(guild_id, autogen_interval) VALUES(?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET autogen_interval = ?",
                (ctx.guild.id, seconds, seconds),
            )
            await db.commit()
        await ctx.send(f"Autogen interval set to {seconds} seconds.")

async def setup(bot):
    cog = WordCloudCog(bot)
    await bot.add_cog(cog)                