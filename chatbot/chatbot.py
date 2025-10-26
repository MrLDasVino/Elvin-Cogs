import asyncio
import json
import os
import random
import re
from typing import Dict, List

from redbot.core import commands, checks
from discord import Message, Forbidden

TOKEN_RE = re.compile(r"<@!?(\d+)>")
WORD_RE = re.compile(r"\w+|[.!?]")
LINK_RE = re.compile(r"https?://\S+|www\.\S+")

COG_FOLDER = os.path.join(os.path.dirname(__file__), "data")
if not os.path.isdir(COG_FOLDER):
    os.makedirs(COG_FOLDER, exist_ok=True)

DEFAULT_DATA = {
    "enabled": True,
    "frequency": 5,
    "model": {},   # { token: [next_token, ...], ... }
    "starts": []   # list of first tokens observed
}

class ChatBot(commands.Cog):
    """
    Chatbot that stores models and settings in per-guild JSON files.
    Learns without trimming and ignores links and messages with attachments.
    Commands are admin-only. Provides purge and forget commands.
    """

    def __init__(self, bot):
        self.bot = bot
        self._locks: Dict[int, asyncio.Lock] = {}

    # ---------- Commands ----------

    @commands.group()
    @commands.guild_only()
    async def chatbot(self, ctx):
        """Chatbot configuration commands."""
        pass

    @chatbot.command(name="enable")
    @checks.admin_or_permissions(administrator=True)
    async def chatbot_enable(self, ctx, state: str):
        """Enable or disable the chatbot for this guild. Usage: [p]chatbot enable on|off"""
        state_lower = state.lower()
        if state_lower not in ("on", "off", "enable", "disable", "true", "false"):
            await ctx.send("Please specify on or off.")
            return
        enabled = state_lower in ("on", "enable", "true")
        data = await self._read_data(ctx.guild.id)
        data["enabled"] = enabled
        await self._write_data(ctx.guild.id, data)
        await ctx.send(f"Chatbot replies set to {'enabled' if enabled else 'disabled'}.")

    @chatbot.command(name="frequency")
    @checks.admin_or_permissions(administrator=True)
    async def chatbot_frequency(self, ctx, percent: int):
        """Set reply frequency as a percent 0-100"""
        if percent < 0 or percent > 100:
            await ctx.send("Frequency must be between 0 and 100.")
            return
        data = await self._read_data(ctx.guild.id)
        data["frequency"] = percent
        await self._write_data(ctx.guild.id, data)
        await ctx.send(f"Chatbot reply frequency set to {percent}%.")

    @chatbot.command(name="purge")
    @checks.admin_or_permissions(administrator=True)
    async def chatbot_purge(self, ctx, confirm: str = ""):
        """
        Purge this guild's chatbot database.
        Usage: [p]chatbot purge confirm
        You must pass the literal word 'confirm' to perform the purge.
        """
        if confirm.lower() != "confirm":
            await ctx.send("This will delete the chatbot database for this server. To confirm, run: `chatbot purge confirm`.")
            return

        guild_id = ctx.guild.id
        path = self._data_path(guild_id)

        lock = await self._get_lock(guild_id)
        async with lock:
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception:
                await ctx.send("Failed to delete the data file. Check file permissions.")
                return
            try:
                await self._write_data(guild_id, dict(DEFAULT_DATA))
            except Exception:
                await ctx.send("Purge completed but failed to reinitialize data file.")
                return

        await ctx.send("Chatbot database purged and reset to defaults for this server.")

    @chatbot.command(name="forget")
    @checks.admin_or_permissions(administrator=True)
    async def chatbot_forget(self, ctx, mode: str = None, *args):
        """
        Forget learned data.
        Modes:
          token <word>               - remove a token entirely from model and starts
          transition <from> <to>     - remove a single transition from model[from]
        Examples:
          chatbot forget token hello
          chatbot forget transition hello world
        """
        if not mode:
            await ctx.send("Usage: chatbot forget token <word> OR chatbot forget transition <from> <to>")
            return

        guild_id = ctx.guild.id
        lock = await self._get_lock(guild_id)
        async with lock:
            data = await self._read_data(guild_id)
            model: Dict[str, List[str]] = data.get("model", {}) or {}
            starts: List[str] = data.get("starts", []) or []

            if mode == "token":
                if len(args) < 1:
                    await ctx.send("Usage: chatbot forget token <word>")
                    return
                token = args[0].lower()

                removed_any = False
                # remove key from model
                if token in model:
                    del model[token]
                    removed_any = True

                # remove all occurrences in successor lists
                for k in list(model.keys()):
                    newlist = [x for x in model[k] if x != token]
                    if len(newlist) != len(model[k]):
                        model[k] = newlist
                        removed_any = True

                # remove from starts
                new_starts = [s for s in starts if s != token]
                if len(new_starts) != len(starts):
                    starts = new_starts
                    removed_any = True

                data["model"] = model
                data["starts"] = starts
                await self._write_data(guild_id, data)

                if removed_any:
                    await ctx.send(f"Token {token!r} removed from model and starts where present.")
                else:
                    await ctx.send(f"Token {token!r} not found in model or starts.")

            elif mode == "transition":
                if len(args) < 2:
                    await ctx.send("Usage: chatbot forget transition <from> <to>")
                    return
                frm = args[0].lower()
                to = args[1].lower()

                if frm not in model:
                    await ctx.send(f"No transitions found for {frm!r}.")
                    return

                old_len = len(model[frm])
                model[frm] = [x for x in model[frm] if x != to]
                new_len = len(model[frm])
                data["model"] = model
                await self._write_data(guild_id, data)

                if new_len < old_len:
                    await ctx.send(f"Removed {old_len - new_len} occurrence(s) of transition {frm!r} -> {to!r}.")
                else:
                    await ctx.send(f"No transitions {frm!r} -> {to!r} were found.")

            else:
                await ctx.send("Unknown mode. Use 'token' or 'transition'.")

    # ---------- Listener ----------

    @commands.Cog.listener()
    async def on_message(self, message: Message):
        if message.author.bot:
            return
        if message.guild is None:
            return
        content = (message.content or "").strip()
        if not content:
            return
        if message.attachments:
            return
        if LINK_RE.search(content):
            return

        try:
            prefixes = await self.bot.get_prefix(message)
        except Exception:
            prefixes = []
        if isinstance(prefixes, (list, tuple)):
            for p in prefixes:
                if not p:
                    continue
                if content.startswith(p):
                    return
        else:
            if prefixes and content.startswith(prefixes):
                return

        if content.strip().startswith(f"<@{self.bot.user.id}>") or content.strip().startswith(f"<@!{self.bot.user.id}>"):
            return

        try:
            await self._learn_from_message(message.guild.id, content)
        except Exception:
            return

        try:
            data = await self._read_data(message.guild.id)
        except Exception:
            return

        if not data.get("enabled", True):
            return

        freq = data.get("frequency", 5)
        roll = random.randint(1, 100)
        if roll > freq:
            return

        model = data.get("model", {}) or {}
        starts = data.get("starts", []) or []
        if not starts or not model:
            return

        try:
            resp = await asyncio.wait_for(self._generate_sentence(model, starts), timeout=2.5)
        except (asyncio.TimeoutError, Exception):
            return

        if not resp:
            return

        try:
            await message.channel.send(resp)
        except Forbidden:
            return
        except Exception:
            return

    # ---------- Storage and learning ----------

    async def _get_lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[guild_id] = lock
        return lock

    def _data_path(self, guild_id: int) -> str:
        return os.path.join(COG_FOLDER, f"chatbot_{guild_id}.json")

    async def _read_data(self, guild_id: int) -> Dict:
        path = self._data_path(guild_id)
        loop = asyncio.get_event_loop()
        if not os.path.isfile(path):
            return dict(DEFAULT_DATA)
        def _sync_read():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        try:
            data = await loop.run_in_executor(None, _sync_read)
            for k, v in DEFAULT_DATA.items():
                if k not in data:
                    data[k] = v
            return data
        except Exception:
            return dict(DEFAULT_DATA)

    async def _write_data(self, guild_id: int, data: Dict):
        path = self._data_path(guild_id)
        loop = asyncio.get_event_loop()
        lock = await self._get_lock(guild_id)
        def _sync_write():
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        async with lock:
            await loop.run_in_executor(None, _sync_write)

    async def _learn_from_message(self, guild_id: int, content: str):
        words = self._tokenize(content)
        if not words:
            return
        lock = await self._get_lock(guild_id)
        async with lock:
            data = await self._read_data(guild_id)
            model: Dict[str, List[str]] = data.get("model", {}) or {}
            starts: List[str] = data.get("starts", []) or []

            starts.append(words[0])

            for a, b in zip(words, words[1:]):
                model.setdefault(a, []).append(b)

            last = words[-1]
            model.setdefault(last, [])

            data["model"] = model
            data["starts"] = starts

            await self._write_data(guild_id, data)

    def _tokenize(self, content: str) -> List[str]:
        content = TOKEN_RE.sub("", content)
        tokens = WORD_RE.findall(content)
        result: List[str] = []
        for t in tokens:
            if t in ".!?":
                result.append(t)
            else:
                result.append(t.lower())
        return result

    async def _generate_sentence(self, model: Dict[str, List[str]], starts: List[str]) -> str:
        if not starts or not model:
            return ""
        word = random.choice(starts)
        out = [word]
        for _ in range(200):
            choices = model.get(word) or []
            if not choices:
                break
            word = random.choice(choices)
            out.append(word)
            if word in ".!?":
                break
        return self._untokenize(out)

    def _untokenize(self, tokens: List[str]) -> str:
        if not tokens:
            return ""
        s = ""
        for idx, t in enumerate(tokens):
            if t in ".!?":
                s = s.rstrip() + t + " "
            else:
                if idx == 0:
                    s += t.capitalize() + " "
                else:
                    s += t + " "
        return s.strip()
