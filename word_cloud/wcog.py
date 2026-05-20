import asyncio
import random
import io
import aiosqlite
import regex as re
from datetime import datetime

import discord
from PIL import Image, ImageDraw
import aiohttp
from collections import OrderedDict
from wordcloud import WordCloud

from pathlib import Path
from redbot.core.data_manager import cog_data_path
from redbot.core import commands, checks
from discord.ext import tasks
from redbot.core.bot import Red

# Basic stopwords
STOPWORDS = {
    "the", "and", "for", "that", "with", "you", "this", "have", "are",
    "but", "not", "was", "from", "they", "she", "he", "it", "in", "on",
    "a", "an", "of", "to", "is", "i", "we", "me", "my", "our", "be",
    "as", "at", "by", "or", "if", "so", "do", "did", "does", "got",
}

# Emoji regexes
UNICODE_EMOJI_RE = re.compile(r'(\p{Emoji_Presentation}|\p{Emoji}\uFE0F)', re.IGNORECASE)
CUSTOM_EMOJI_RE = re.compile(r"<a?:([a-zA-Z0-9_]+):([0-9]{17,22})>")

# Words only
WORD_REGEX = re.compile(r"\b[^\W\d_]{2,}\b", flags=re.UNICODE)

def random_color_func(word, font_size, position, orientation, random_state=None, **kwargs):
    return "rgb({}, {}, {})".format(
        random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)
    )

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


        self.bot.loop.create_task(self._ensure_db())

    async def cog_load(self):

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
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT 1 FROM ignored_channels WHERE guild_id = ? AND channel_id = ?",
                (message.guild.id, message.channel.id),
            )
            if await cur.fetchone():
                return

        raw = message.content or ""
        tokens = []

        # custom emojis
        def repl_custom(m):
            name, eid = m.groups()
            tokens.append(f"custom_{name}:{eid}")
            return ""
        text = CUSTOM_EMOJI_RE.sub(repl_custom, raw)

        # unicode emojis
        def repl_unicode(m):
            tokens.append(m.group(0))
            return ""
        text = UNICODE_EMOJI_RE.sub(repl_unicode, text)

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
        async with aiosqlite.connect(self.db_path) as db:
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
        import numpy as np

        buf = io.BytesIO()
        if not frequencies:
            img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            img.save(buf, format="PNG")
            buf.seek(0)
            return buf
              

        wc_kwargs = {
            "width": width,
            "height": height,
            "margin": 0,            
            "mode": "RGBA",
            "background_color": None,
            "prefer_horizontal": 0.9,
            "collocations": False,
        }

        wc = WordCloud(**wc_kwargs)
        wc.generate_from_frequencies(frequencies)
        wc.recolor(
            color_func=lambda word, font_size, position, orientation, random_state=None, **kwargs: (
                "rgba(0,0,0,0)" if word.startswith("custom_")
                else random_color_func(word, font_size, position, orientation)
            ),
            random_state=42,
        )

        # split layout into words vs emojis
        full_layout = wc.layout_
        word_entries, emoji_entries = [], []
        for entry in full_layout:
            raw = entry[0]
            token = raw[0] if isinstance(raw, tuple) else raw
            is_custom = token.startswith("custom_")
            is_unicode = UNICODE_EMOJI_RE.fullmatch(token) is not None
            if is_custom or is_unicode:
                emoji_entries.append(entry)
            else:
                word_entries.append(entry)

        # render words only
        wc.layout_ = word_entries
        base_img = wc.to_image().convert("RGBA")
                

        # overlay emojis
        for entry in emoji_entries:
            raw = entry[0]
            token = raw[0] if isinstance(raw, tuple) else raw
            # unpack
            if len(entry) == 6:
                _, _, font_size, position, orientation, _ = entry
            else:
                _, font_size, position, orientation, _ = entry

            # build URL + cache key
            if token.startswith("custom_"):
                _, rest = token.split("custom_", 1)
                _, eid = rest.split(":", 1)
                url = f"https://cdn.discordapp.com/emojis/{eid}.png?size=64"
                key = f"custom:{eid}"
            else:
                cps = "-".join(f"{ord(c):x}" for c in token)
                url = f"https://twemoji.maxcdn.com/v/latest/72x72/{cps}.png"
                key = f"unicode:{cps}"

            # fetch or reuse
            if key in self._emoji_cache:
                em = self._emoji_cache[key]
                self._emoji_cache.move_to_end(key)
            else:
                try:
                    async with self._session.get(url) as resp:
                        data = await resp.read()
                        em = Image.open(io.BytesIO(data)).convert("RGBA")
                except Exception:
                    continue
                # resize
                try:
                    resample = Image.Resampling.LANCZOS
                except AttributeError:
                    resample = Image.LANCZOS
                em = em.resize((font_size, font_size), resample)
                self._emoji_cache[key] = em
                if len(self._emoji_cache) > self._cache_max:
                    self._emoji_cache.popitem(last=False)

            # paste
            x, y = position
            base_img.paste(em, (int(x), int(y)), em)

            
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

    @wordcloud.command(name="shape", hidden=True)
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
                "SELECT token, SUM(count) FROM counts "
                "WHERE guild_id = ? GROUP BY token ORDER BY SUM(count) DESC LIMIT ?",
                (ctx.guild.id, limit * 2),
            )
            rows = await cur.fetchall()
        if not rows:
            return await ctx.send("No data yet.")

        def disp(tok):
            if tok.startswith("custom_"):
                name, eid = tok.split("custom_", 1)[1].split(":", 1)
                return f"<:{name}:{eid}>"
            return tok

        emojis = [(disp(tok), cnt) for tok, cnt in rows if tok.startswith("custom_")]
        words  = [(tok, cnt) for tok, cnt in rows if not tok.startswith("custom_")]

        e_emb = discord.Embed(
            title="📊 Top Emojis",
            description="\n".join(f"{t}: {c}" for t, c in emojis[:limit]) or "None",
        )
        w_emb = discord.Embed(
            title="📊 Top Words",
            description="\n".join(f"{t}: {c}" for t, c in words[:limit]) or "None",
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
            await db.execute("DELETE FROM config WHERE guild_id = ?", (ctx.guild.id,))
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