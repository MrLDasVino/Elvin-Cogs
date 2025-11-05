import asyncio
import time
import re
import aiohttp
from typing import Optional, List, Union
import discord
from redbot.core import commands, Config
from redbot.core.utils.chat_formatting import box

BASE_API = "https://retroachievements.org/API/"
BASE_SITE = "https://retroachievements.org"

# Colors
COLOR_INFO = 0x2ECC71
COLOR_WARN = 0xE67E22
COLOR_ERROR = 0xE74C3C
COLOR_NEUTRAL = 0x3498DB

PAGINATION_TIMEOUT = 120  # seconds
PAGINATION_EMOJIS = ("◀️", "▶️", "⛔")

# debugging and caching globals
_last_resolve_attempts: List[dict] = []
_resolve_cache: dict = {}  # name_lower -> game id (in-memory)
_endpoint_disabled_until: dict = {}  # endpoint -> unix timestamp


def _record_resolve_attempt(ep, params, res):
    try:
        summary = {"endpoint": ep, "params": params, "type": type(res).__name__}
        if isinstance(res, (dict, list)):
            s = str(res)
            summary["preview"] = s[:400]
        else:
            summary["preview"] = str(res)[:400]
        _last_resolve_attempts.append(summary)
        if len(_last_resolve_attempts) > 80:
            _last_resolve_attempts.pop(0)
    except Exception:
        pass


class RetroAchievements(commands.Cog):
    """Interact with the RetroAchievements API with site-scrape fallback for name lookups."""

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.config = Config.get_conf(self, identifier=0xA1B2C3D4E7)
        default_global = {"api_key": None, "username": None, "name_map": {}}
        self.config.register_global(**default_global)
        # load persistent name_map into in-memory cache asynchronously
        try:
            asyncio.create_task(self._load_persistent_name_map())
        except Exception:
            pass

    async def _load_persistent_name_map(self):
        try:
            cfg = await self.config.all()
            pm = cfg.get("name_map") or {}
            for k, v in pm.items():
                try:
                    _resolve_cache[k.lower()] = int(v)
                except Exception:
                    pass
        except Exception:
            pass

    def cog_unload(self):
        try:
            if not self.session.closed:
                asyncio.create_task(self.session.close())
        except Exception:
            pass

    async def _api_get(self, endpoint: str, params: dict = None, timeout: int = 15):
        base = BASE_API.rstrip("/")
        ep = endpoint.lstrip("/")
        url = f"{base}/{ep}"

        headers = {
            "User-Agent": "RedBot/RetroAchievementsCog (+https://your.bot/info)",
            "Accept": "application/json, text/plain, */*",
        }
        try:
            async with self.session.get(url, params=params, headers=headers, timeout=timeout) as resp:
                text = await resp.text()
                if resp.status == 200:
                    try:
                        return await resp.json(content_type=None)
                    except Exception:
                        return text
                return {
                    "error": f"HTTP {resp.status}",
                    "status": resp.status,
                    "body": text,
                    "url": url,
                    "params": params,
                }
        except asyncio.TimeoutError:
            return {"error": "Request timed out", "url": url, "params": params}
        except aiohttp.ClientError as e:
            return {"error": f"HTTP error: {e}", "url": url, "params": params}
        except Exception as e:
            return {"error": f"Unexpected error: {e}", "url": url, "params": params}

    async def _ensure_api_key(self, ctx):
        cfg = await self.config.all()
        api_key = cfg.get("api_key")
        if not api_key:
            await ctx.send(
                embed=self._error_embed(
                    "API key not configured. Use `retroachievements set <API_KEY> [default_username]` to configure."
                )
            )
            return None
        return api_key

    def _error_embed(self, message: str):
        return discord.Embed(description=message, color=COLOR_ERROR)

    def _info_embed(self, title: str, description: str = None):
        e = discord.Embed(title=title, color=COLOR_INFO)
        if description:
            e.description = description
        return e

    async def _get_auth(self, username: Optional[str] = None):
        cfg = await self.config.all()
        api_key = cfg.get("api_key")
        cfg_username = cfg.get("username")
        use_username = username or cfg_username
        return api_key, use_username

    async def _paginate_embeds(self, ctx, embeds: List[discord.Embed]):
        if not embeds:
            await ctx.send(embed=self._error_embed("Nothing to show."))
            return

        index = 0
        message = await ctx.send(embed=embeds[index])
        if len(embeds) > 1:
            try:
                for e in PAGINATION_EMOJIS:
                    await message.add_reaction(e)
            except Exception:
                return

            def check(reaction, user):
                return (
                    reaction.message.id == message.id
                    and user == ctx.author
                    and str(reaction.emoji) in PAGINATION_EMOJIS
                )

            while True:
                try:
                    reaction, user = await self.bot.wait_for("reaction_add", timeout=PAGINATION_TIMEOUT, check=check)
                except asyncio.TimeoutError:
                    try:
                        await message.clear_reactions()
                    except Exception:
                        pass
                    break

                em = str(reaction.emoji)
                try:
                    await message.remove_reaction(reaction.emoji, user)
                except Exception:
                    pass

                if em == "◀️":
                    index = (index - 1) % len(embeds)
                    try:
                        await message.edit(embed=embeds[index])
                    except Exception:
                        pass
                elif em == "▶️":
                    index = (index + 1) % len(embeds)
                    try:
                        await message.edit(embed=embeds[index])
                    except Exception:
                        pass
                elif em == "⛔":
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    break
        else:
            return

    # --- SCRAPE HELPERS ---
    async def _scrape_site_search(self, query: str) -> Optional[int]:
        """
        Scrape the RetroAchievements site for a query and return the first numeric game ID found.
        Tries several known search paths and parses HTML to find the first /Game/<id>/ link.
        """
        # Respect caching: if in-memory cached already, return quickly
        key = query.strip().lower()
        if key in _resolve_cache:
            return _resolve_cache[key]

        # common site search paths to try (order matters)
        paths = [
            f"/Search?search={aiohttp.helpers.quote(query)}",
            f"/Game/Search?search={aiohttp.helpers.quote(query)}",
            f"/Search?Search={aiohttp.helpers.quote(query)}",
            f"/Search?query={aiohttp.helpers.quote(query)}",
        ]

        headers = {"User-Agent": "RedBot/RetroAchievementsCog (+https://your.bot/info)", "Accept": "text/html"}
        # small throttle across site requests
        for path in paths:
            url = BASE_SITE.rstrip("/") + path
            # skip if we've disabled site scraping recently (avoid hammering)
            disabled_until = _endpoint_disabled_until.get("site_scrape")
            if disabled_until and time.time() < disabled_until:
                continue
            try:
                async with self.session.get(url, headers=headers, timeout=10) as resp:
                    text = await resp.text()
                    # handle rate-limited or blocked responses (common)
                    if resp.status == 429:
                        # back off site scraping for a while
                        _endpoint_disabled_until["site_scrape"] = time.time() + 60.0
                        _record_resolve_attempt("site_scrape", {"url": url}, {"status": 429, "body": text[:400]})
                        await asyncio.sleep(1.0)
                        continue
                    if resp.status >= 400:
                        _record_resolve_attempt("site_scrape", {"url": url}, {"status": resp.status, "body": text[:400]})
                        continue
                    # try to find first /Game/<id>/ link
                    # Example link formats: /Game/9190/the-legend-of-zelda-the-wind-waker or /Game/9190
                    m = re.search(r'href=["\'](?:/Game/)(\d+)(?:/[^"\']*)?["\']', text, re.IGNORECASE)
                    if m:
                        gid = int(m.group(1))
                        _record_resolve_attempt("site_scrape", {"url": url}, {"found": gid})
                        # cache persistently
                        _resolve_cache[key] = gid
                        await self._persist_name_map_entry(key, gid)
                        return gid
                    # sometimes site shows JSON or script-embedded results containing game id
                    m2 = re.search(r'GameId["\']?\s*[:=]\s*["\']?(\d+)["\']?', text, re.IGNORECASE)
                    if m2:
                        gid = int(m2.group(1))
                        _record_resolve_attempt("site_scrape", {"url": url}, {"found": gid})
                        _resolve_cache[key] = gid
                        await self._persist_name_map_entry(key, gid)
                        return gid
                    _record_resolve_attempt("site_scrape", {"url": url}, {"found": None, "preview": text[:200]})
            except asyncio.TimeoutError:
                _record_resolve_attempt("site_scrape", {"url": url}, {"error": "timeout"})
                continue
            except aiohttp.ClientError as e:
                _record_resolve_attempt("site_scrape", {"url": url}, {"error": f"client_error:{e}"})
                continue
            except Exception as e:
                _record_resolve_attempt("site_scrape", {"url": url}, {"error": f"exception:{e}"})
                continue
            # polite pause between tries
            await asyncio.sleep(0.35)
        return None

    async def _persist_name_map_entry(self, name_lower: str, gid: int):
        """
        Persist a single name->id entry into Red Config name_map.
        This keeps mappings across restarts to avoid re-scraping.
        """
        try:
            cfg = await self.config.all()
            pm = cfg.get("name_map") or {}
            if pm.get(name_lower) == gid:
                return
            pm[name_lower] = int(gid)
            await self.config.name_map.set(pm)
        except Exception:
            pass

    # --- RESOLVER: tries API endpoints first, then site-scrape fallback ---
    async def _resolve_game_id(self, api_key: str, game: Union[str, int]) -> Optional[int]:
        # numeric quick path
        if isinstance(game, int):
            return game
        s = str(game).strip()
        if s.isdigit():
            return int(s)

        key = s.lower()
        # in-memory cache
        if key in _resolve_cache:
            return _resolve_cache[key]

        # attempt API-based lookup (existing resilient approach)
        candidates_base = [
            ("API_SearchGames.php", "q"),
            ("API_Search.php", "q"),
            ("API_GetGames.php", "title"),
            ("API_GetGameByName.php", "name"),
            ("API_GetGame.php", "title"),
        ]

        def _extract_id_from_obj(obj) -> Optional[int]:
            for k in ("ID", "GameID", "GameId", "i", "id", "Game_Id", "game_id", "gameid"):
                if k in obj:
                    try:
                        return int(obj[k])
                    except Exception:
                        pass
            return None

        # internal backoff caller for API endpoints
        async def _call_api_with_backoff(ep, params, max_retries=3):
            backoff = 1.0
            for attempt in range(max_retries):
                disabled_until = _endpoint_disabled_until.get(ep)
                if disabled_until and time.time() < disabled_until:
                    return {"error": "disabled", "status": 404, "body": "endpoint disabled due to previous 404"}
                res = await self._api_get(ep, params=params)
                if isinstance(res, dict) and "status" in res:
                    st = res.get("status")
                    if st == 404:
                        _endpoint_disabled_until[ep] = time.time() + 600.0
                        return res
                    if st == 429:
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue
                    return res
                return res
            return res

        # queries to try (try exact, a "The " prefixed variation, and stripped region tags)
        alt_queries = [s]
        if not s.lower().startswith("the "):
            alt_queries.append("The " + s)
        alt_queries.append(s.replace(" (USA)", "").replace(" (Europe)", "").strip())

        for q in alt_queries:
            for ep, param_key in candidates_base:
                params = {param_key: q, "y": api_key}
                res = await _call_api_with_backoff(ep, params)
                await asyncio.sleep(0.25)
                _record_resolve_attempt(ep, params, res)

                if isinstance(res, dict) and "status" in res:
                    st = res.get("status")
                    if st in (404, 429):
                        continue
                    continue

                # list response
                if isinstance(res, list) and res:
                    for entry in res:
                        if not isinstance(entry, dict):
                            continue
                        title = entry.get("Title") or entry.get("Name") or entry.get("title") or ""
                        if isinstance(title, str) and title.lower() == q.lower():
                            gid = _extract_id_from_obj(entry)
                            if gid:
                                _resolve_cache[key] = gid
                                await self._persist_name_map_entry(key, gid)
                                return gid
                    for entry in res:
                        if not isinstance(entry, dict):
                            continue
                        title = entry.get("Title") or entry.get("Name") or entry.get("title") or ""
                        if isinstance(title, str) and q.lower() in title.lower():
                            gid = _extract_id_from_obj(entry)
                            if gid:
                                _resolve_cache[key] = gid
                                await self._persist_name_map_entry(key, gid)
                                return gid
                    first = res[0]
                    if isinstance(first, dict):
                        gid = _extract_id_from_obj(first)
                        if gid:
                            _resolve_cache[key] = gid
                            await self._persist_name_map_entry(key, gid)
                            return gid
                    continue

                # dict response: look for list keys or id->object map or single object
                if isinstance(res, dict):
                    for list_key in ("Results", "Games", "GamesList", "results", "games", "ResultSet"):
                        if list_key in res and isinstance(res[list_key], list) and res[list_key]:
                            for entry in res[list_key]:
                                if not isinstance(entry, dict):
                                    continue
                                title = entry.get("Title") or entry.get("Name") or entry.get("title") or ""
                                if isinstance(title, str) and title.lower() == q.lower():
                                    gid = _extract_id_from_obj(entry)
                                    if gid:
                                        _resolve_cache[key] = gid
                                        await self._persist_name_map_entry(key, gid)
                                        return gid
                            for entry in res[list_key]:
                                if not isinstance(entry, dict):
                                    continue
                                title = entry.get("Title") or entry.get("Name") or entry.get("title") or ""
                                if isinstance(title, str) and q.lower() in title.lower():
                                    gid = _extract_id_from_obj(entry)
                                    if gid:
                                        _resolve_cache[key] = gid
                                        await self._persist_name_map_entry(key, gid)
                                        return gid
                            first = res[list_key][0]
                            if isinstance(first, dict):
                                gid = _extract_id_from_obj(first)
                                if gid:
                                    _resolve_cache[key] = gid
                                    await self._persist_name_map_entry(key, gid)
                                    return gid

                    # mapping id->object
                    is_map = all(isinstance(k, str) and isinstance(v, dict) for k, v in res.items()) if res else False
                    if is_map:
                        for k, v in res.items():
                            title = v.get("Title") or v.get("Name") or ""
                            if isinstance(title, str) and title.lower() == q.lower():
                                try:
                                    gid = int(k)
                                    _resolve_cache[key] = gid
                                    await self._persist_name_map_entry(key, gid)
                                    return gid
                                except Exception:
                                    pass
                        for k, v in res.items():
                            title = v.get("Title") or v.get("Name") or ""
                            if isinstance(title, str) and q.lower() in title.lower():
                                try:
                                    gid = int(k)
                                    _resolve_cache[key] = gid
                                    await self._persist_name_map_entry(key, gid)
                                    return gid
                                except Exception:
                                    pass
                        try:
                            gid = int(next(iter(res.keys())))
                            _resolve_cache[key] = gid
                            await self._persist_name_map_entry(key, gid)
                            return gid
                        except Exception:
                            pass

                    # single object: try extract id directly
                    gid = None
                    try:
                        gid = None
                        for k in ("ID", "GameID", "GameId", "i", "id", "Game_Id", "game_id", "gameid"):
                            if k in res:
                                gid = int(res[k])
                                break
                    except Exception:
                        gid = None
                    if gid:
                        _resolve_cache[key] = gid
                        await self._persist_name_map_entry(key, gid)
                        return gid

        # if API-based attempts failed, try scraping the site (if not disabled)
        site_gid = await self._scrape_site_search(s)
        if site_gid:
            return site_gid

        return None

    # --- commands below are unchanged except they benefit from new resolver and persistent name_map ---
    @commands.group(name="retroachievements", aliases=["ra"], invoke_without_command=True)
    @commands.guild_only()
    async def retroachievements(self, ctx):
        """Top-level RetroAchievements command."""
        await ctx.send_help(ctx.command)

    @retroachievements.command(name="set")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_credentials(self, ctx, api_key: Optional[str] = None, username: Optional[str] = None):
        """Set the RetroAchievements API key and optional default username."""
        if api_key is None:
            await ctx.send(embed=self._error_embed("No API key provided. You must provide your RetroAchievements web API key."))
            return

        if api_key == "-":
            await self.config.api_key.set(None)
            api_key_set = None
        else:
            await self.config.api_key.set(api_key)
            api_key_set = api_key

        if username is not None:
            if username == "-":
                await self.config.username.set(None)
                username_set = None
            else:
                await self.config.username.set(username)
                username_set = username
        else:
            username_set = (await self.config.username())

        embed = discord.Embed(title="Configuration updated", color=COLOR_INFO)
        embed.add_field(name="API key", value="(set)" if api_key_set else "(cleared)", inline=True)
        embed.add_field(name="Default username", value=username_set or "(none)", inline=True)
        embed.set_footer(text="The API key is required for most commands")
        await ctx.send(embed=embed)
        await ctx.tick()

    @retroachievements.command(name="profile", aliases=["user"])
    async def profile(self, ctx, username: Optional[str] = None):
        """Get a RetroAchievements user profile summary."""
        api_key = await self._ensure_api_key(ctx)
        if not api_key:
            return

        cfg_api, cfg_username = await self._get_auth(username)
        if not cfg_username:
            await ctx.send(embed=self._error_embed("No username configured and none provided. Provide a username or set a default with `retroachievements set <API_KEY> <username>`."))
            return

        params = {"u": cfg_username, "y": api_key}
        data = await self._api_get("API_GetUserSummary.php", params=params)
        if isinstance(data, dict) and "error" in data:
            err = data.get("error")
            body = data.get("body") or ""
            await ctx.send(embed=self._error_embed(f"API error: {err}\n{body}"))
            return

        if not isinstance(data, dict):
            await ctx.send(embed=self._error_embed("Unexpected API response format for user profile."))
            return

        embed = discord.Embed(title=f"{cfg_username} — RetroAchievements profile", color=COLOR_NEUTRAL)

        def maybe_add(key, label=None):
            val = data.get(key)
            if val not in (None, "", "0"):
                embed.add_field(name=(label or key), value=str(val), inline=True)

        maybe_add("UserName", "Username")
        maybe_add("Points", "Points")
        maybe_add("Rank", "Rank")
        maybe_add("TotalGames", "Total Games")
        maybe_add("TotalAchievements", "Total Achievements")
        maybe_add("PossiblePoints", "Possible Points")
        maybe_add("JoinDate", "Join Date")
        maybe_add("LastActive", "Last Active")
        avatar = data.get("Avatar")
        if avatar:
            if isinstance(avatar, str) and avatar.startswith("/"):
                avatar = f"https://retroachievements.org{avatar}"
            embed.set_thumbnail(url=avatar)

        if not embed.fields:
            await ctx.send(box(str(data)))
            return

        embed.set_footer(text="Data from RetroAchievements.org")
        await ctx.send(embed=embed)

    @retroachievements.command(name="game")
    async def game(self, ctx, *, game: str):
        """Get game info by RetroAchievements game ID or name."""
        api_key = await self._ensure_api_key(ctx)
        if not api_key:
            return

        gid = await self._resolve_game_id(api_key, game)
        if not gid:
            await ctx.send(embed=self._error_embed("Could not resolve game name to an ID. Try the owner-only raw command to probe search endpoints."))
            try:
                if await self.bot.is_owner(ctx.author):
                    lines = []
                    for a in _last_resolve_attempts[-8:]:
                        lines.append(f"{a['endpoint']} params={a['params']} -> {a['type']} preview={a.get('preview','')}")
                    try:
                        await ctx.author.send("Resolve attempts:\n" + "\n\n".join(lines)[:1900])
                    except Exception:
                        pass
            except Exception:
                pass
            return

        params = {"i": str(gid), "y": api_key}
        data = await self._api_get("API_GetGame.php", params=params)
        if isinstance(data, dict) and "error" in data:
            body = data.get("body") or ""
            await ctx.send(embed=self._error_embed(f"API error: {data['error']}\nBody: {body}"))
            return

        if not isinstance(data, dict):
            await ctx.send(embed=self._error_embed("Unexpected API response format for game info."))
            return

        title = data.get("Title") or f"Game {gid}"
        embed = discord.Embed(title=title, color=COLOR_NEUTRAL)

        console_name = data.get("ConsoleName") or data.get("Console") or data.get("ConsoleTitle") or "Unknown"
        embed.add_field(name="System", value=console_name, inline=True)
        embed.add_field(name="Publisher", value=data.get("Publisher", "Unknown"), inline=True)
        embed.add_field(name="Developer", value=data.get("Developer", "Unknown"), inline=True)
        embed.add_field(name="Achievements", value=str(data.get("AchievementCount", "Unknown")), inline=True)
        embed.add_field(name="Possible Points", value=str(data.get("PossiblePoints", "Unknown")), inline=True)

        desc = data.get("Description")
        if desc:
            embed.description = (desc[:2040] + "...") if len(desc) > 2048 else desc

        boxart = (
            data.get("ImageBoxArt")
            or data.get("ImageBox")
            or data.get("ImageTitle")
            or data.get("ImageIcon")
            or data.get("BoxArt")
        )
        if boxart and isinstance(boxart, str):
            if boxart.startswith("/"):
                boxart = f"https://retroachievements.org{boxart}"
            embed.set_thumbnail(url=boxart)

        embed.set_footer(text="Data from RetroAchievements.org")
        await ctx.send(embed=embed)

    @retroachievements.command(name="recent")
    async def recent_global(self, ctx, limit: int = 5):
        """Show recent achievements unlocked globally."""
        api_key = await self._ensure_api_key(ctx)
        if not api_key:
            return

        limit = max(1, min(50, limit))
        params = {"c": str(limit), "y": api_key}
        data = await self._api_get("API_GetRecentAchievements.php", params=params)
        if isinstance(data, dict) and "error" in data:
            body = data.get("body") or ""
            await ctx.send(embed=self._error_embed(f"API error: {data['error']}\n{body}"))
            return

        if not isinstance(data, list) or not data:
            await ctx.send(embed=self._error_embed("No recent achievements found or unexpected response format."))
            return

        pages = []
        chunk_size = 12
        lines = []
        for item in data:
            user = item.get("User") or item.get("UserName") or item.get("Username") or "Unknown"
            game = item.get("GameTitle") or item.get("Title") or item.get("Game") or "Unknown"
            ach = item.get("Title") or item.get("AchievementTitle") or item.get("Achievement") or "Unknown"
            when = item.get("TimeStamp") or item.get("Date") or item.get("Time") or "Unknown"
            lines.append(f"**{user}** — {game} — {ach} — {when}")

        for i in range(0, len(lines), chunk_size):
            emb = discord.Embed(title="Recent RetroAchievements Unlocks", description="\n".join(lines[i:i + chunk_size]), color=COLOR_INFO)
            emb.set_footer(text=f"Showing {i+1}-{min(i+chunk_size, len(lines))} of {len(lines)}")
            pages.append(emb)

        await self._paginate_embeds(ctx, pages)

    @retroachievements.command(name="leaderboard", aliases=["top"])
    async def leaderboard(self, ctx, game: Optional[str] = None, top: int = 10):
        """Get global or per-game leaderboard."""
        api_key = await self._ensure_api_key(ctx)
        if not api_key:
            return

        top = max(1, min(50, top))

        if game:
            gid = await self._resolve_game_id(api_key, game)
            if not gid:
                await ctx.send(embed=self._error_embed("Could not resolve game name to an ID. Try the owner-only raw command to probe search endpoints."))
                try:
                    if await self.bot.is_owner(ctx.author):
                        lines = []
                        for a in _last_resolve_attempts[-8:]:
                            lines.append(f"{a['endpoint']} params={a['params']} -> {a['type']} preview={a.get('preview','')}")
                        try:
                            await ctx.author.send("Resolve attempts:\n" + "\n\n".join(lines)[:1900])
                        except Exception:
                            pass
                except Exception:
                    pass
                return

            endpoint = "API_GetGameLeaderboards.php"
            params = {"i": str(gid), "y": api_key}
            data = await self._api_get(endpoint, params=params)
            if isinstance(data, dict) and "error" in data:
                body = data.get("body") or ""
                await ctx.send(embed=self._error_embed(f"API error: {data['error']}\nBody: {body}"))
                return

            results = data.get("Results") if isinstance(data, dict) else None
            if not isinstance(results, list) or not results:
                await ctx.send(embed=self._error_embed("No leaderboards returned for that game."))
                return

            lines = []
            for entry in results:
                title = entry.get("Title") or "Unknown"
                top_entry = entry.get("TopEntry") or {}
                user = top_entry.get("User") or top_entry.get("ULID") or "—"
                score = top_entry.get("Score") or top_entry.get("FormattedScore") or "—"
                lines.append(f"**{title}** — {user} — {score}")

            pages = []
            chunk = 12
            for i in range(0, len(lines), chunk):
                emb = discord.Embed(title=f"Leaderboards for game {gid}", description="\n".join(lines[i:i + chunk]), color=COLOR_INFO)
                emb.set_footer(text=f"Showing {i+1}-{min(i+chunk, len(lines))} of {len(lines)}")
                pages.append(emb)

            await self._paginate_embeds(ctx, pages)
            return

        endpoint = "API_GetTopTenUsers.php"
        params = {"y": api_key}
        data = await self._api_get(endpoint, params=params)
        if isinstance(data, dict) and "error" in data:
            body = data.get("body") or ""
            await ctx.send(embed=self._error_embed(f"API error: {data['error']}\n{body}"))
            return

        if not isinstance(data, list) or not data:
            await ctx.send(embed=self._error_embed("No global leaderboard data returned."))
            return

        lines = []
        for idx, e in enumerate(data, start=1):
            name = e.get("UserName") or e.get("User") or e.get("Username") or "Unknown"
            pts = e.get("Points") or e.get("Score") or e.get("TotalPoints") or "0"
            lines.append(f"{idx}. **{name}** — {pts} pts")

        pages = []
        chunk = 12
        for i in range(0, len(lines), chunk):
            emb = discord.Embed(title="Top users", description="\n".join(lines[i:i + chunk]), color=COLOR_INFO)
            emb.set_footer(text=f"Showing {i+1}-{min(i+chunk, len(lines))} of {len(lines)}")
            pages.append(emb)

        await self._paginate_embeds(ctx, pages)

    @retroachievements.group(name="achievements", invoke_without_command=True)
    async def achievements_group(self, ctx):
        """Achievements related commands."""
        await ctx.send_help(ctx.command)

    @achievements_group.command(name="list")
    async def achievements_list(self, ctx, game: str, details: bool = False):
        """List achievements for a game by ID or name. Use details True for descriptions."""
        api_key = await self._ensure_api_key(ctx)
        if not api_key:
            return

        gid = await self._resolve_game_id(api_key, game)
        if not gid:
            await ctx.send(embed=self._error_embed("Could not resolve game name to an ID. Try the owner-only raw command to probe search endpoints."))
            try:
                if await self.bot.is_owner(ctx.author):
                    lines = []
                    for a in _last_resolve_attempts[-8:]:
                        lines.append(f"{a['endpoint']} params={a['params']} -> {a['type']} preview={a.get('preview','')}")
                    try:
                        await ctx.author.send("Resolve attempts:\n" + "\n\n".join(lines)[:1900])
                    except Exception:
                        pass
            except Exception:
                pass
            return

        params = {"i": str(gid), "y": api_key}
        data = await self._api_get("API_GetGame.php", params=params)
        if isinstance(data, dict) and "error" in data:
            await ctx.send(embed=self._error_embed(f"API error: {data['error']}"))
            return

        achs = None
        for key in ("Achievements", "achievements", "AchievementList", "AchievementsList", "Achievement"):
            if isinstance(data, dict) and key in data:
                achs = data[key]
                break

        if achs is None and isinstance(data, dict) and "AchievementCount" in data:
            await ctx.send(embed=self._info_embed("No achievement list returned", "The API did not return a detailed achievement list for this game. Use the raw command for debugging."))
            return

        items = []
        if isinstance(achs, dict):
            items = list(achs.values())
        elif isinstance(achs, list):
            items = achs

        if not items:
            await ctx.send(embed=self._error_embed("No achievements data found for that game."))
            return

        lines = []
        for a in items:
            if not isinstance(a, dict):
                continue
            title = a.get("Title") or a.get("Name") or a.get("AchievementTitle") or "Unnamed"
            points = a.get("Points") or a.get("PointValue") or ""
            if details:
                desc = a.get("Description") or a.get("Detail") or ""
                lines.append(f"**{title}** — {points} pts — {desc}")
            else:
                lines.append(f"**{title}** — {points} pts")

        pages = []
        chunk = 10
        for i in range(0, len(lines), chunk):
            emb = discord.Embed(title=f"Achievements for Game {gid}", description="\n".join(lines[i:i + chunk]), color=COLOR_NEUTRAL)
            emb.set_footer(text=f"Showing {i+1}-{min(i+chunk, len(lines))} of {len(lines)}")
            pages.append(emb)

        await self._paginate_embeds(ctx, pages)

    @retroachievements.command(name="recentgames")
    async def recent_games(self, ctx, username: Optional[str] = None, limit: int = 5):
        """Show recent games a user has played (based on recent achievements). Uses configured username if none provided."""
        api_key = await self._ensure_api_key(ctx)
        if not api_key:
            return

        cfg_api, cfg_username = await self._get_auth(username)
        if not cfg_username:
            await ctx.send(embed=self._error_embed("No username configured and none provided. Provide a username or set a default with `retroachievements set <API_KEY> <username>`."))
            return

        limit = max(1, min(50, limit))
        params = {"u": cfg_username, "c": str(limit), "y": api_key}
        data = await self._api_get("API_GetRecentAchievements.php", params=params)
        if isinstance(data, dict) and "error" in data:
            await ctx.send(embed=self._error_embed(f"API error: {data['error']}"))
            return

        if not isinstance(data, list) or not data:
            await ctx.send(embed=self._info_embed("No recent games found", f"No recent achievements or games found for user {cfg_username}."))
            return

        seen = set()
        games = []
        for item in data:
            title = item.get("GameTitle") or item.get("Title") or item.get("Game")
            if title and title not in seen:
                seen.add(title)
                games.append(title)
            if len(games) >= limit:
                break

        if not games:
            await ctx.send(embed=self._info_embed("No recent games found", f"No recent games found for user {cfg_username}."))
            return

        lines = [f"- {g}" for g in games]
        pages = []
        chunk = 12
        for i in range(0, len(lines), chunk):
            emb = discord.Embed(title=f"Recent games for {cfg_username}", description="\n".join(lines[i:i + chunk]), color=COLOR_INFO)
            emb.set_footer(text=f"Showing {i+1}-{min(i+chunk, len(lines))} of {len(lines)}")
            pages.append(emb)

        await self._paginate_embeds(ctx, pages)

    @retroachievements.command(name="progress")
    async def progress(self, ctx, username: Optional[str] = None, game: Optional[str] = None):
        """Show achievements progress."""
        api_key = await self._ensure_api_key(ctx)
        if not api_key:
            return

        cfg_api, cfg_username = await self._get_auth(username)
        if not cfg_username:
            await ctx.send(embed=self._error_embed("No username configured and none provided. Provide a username or set a default with `retroachievements set <API_KEY> <username>`."))
            return

        if game:
            gid = await self._resolve_game_id(api_key, game)
            if not gid:
                await ctx.send(embed=self._error_embed("Could not resolve game name to an ID. Try the owner-only raw command to probe search endpoints."))
                try:
                    if await self.bot.is_owner(ctx.author):
                        lines = []
                        for a in _last_resolve_attempts[-8:]:
                            lines.append(f"{a['endpoint']} params={a['params']} -> {a['type']} preview={a.get('preview','')}")
                        try:
                            await ctx.author.send("Resolve attempts:\n" + "\n\n".join(lines)[:1900])
                        except Exception:
                            pass
                except Exception:
                    pass
                return

            params = {"u": cfg_username, "i": str(gid), "y": api_key}
            data = await self._api_get("API_GetUnachieved.php", params=params)
            if isinstance(data, dict) and "error" in data:
                await ctx.send(embed=self._error_embed(f"API error: {data['error']}"))
                return

            if not isinstance(data, list):
                await ctx.send(embed=self._error_embed("Unexpected response format for per-game progress."))
                return

            total = len(data)
            if total == 0:
                await ctx.send(embed=self._info_embed("All achievements unlocked", f"{cfg_username} has unlocked all achievements for game {gid}."))
                return

            lines = []
            for item in data:
                title = item.get("Title") or item.get("Name") or "Unnamed"
                points = item.get("Points") or ""
                lines.append(f"**{title}** — {points} pts")

            pages = []
            chunk = 10
            for i in range(0, len(lines), chunk):
                emb = discord.Embed(title=f"{cfg_username}'s unachieved on game {gid}", description="\n".join(lines[i:i + chunk]), color=COLOR_WARN)
                emb.set_footer(text=f"{i+1}-{min(i+chunk, total)} of {total} unachieved")
                pages.append(emb)

            await self._paginate_embeds(ctx, pages)
            return

        params = {"u": cfg_username, "y": api_key}
        data = await self._api_get("API_GetUserSummary.php", params=params)
        if isinstance(data, dict) and "error" in data:
            await ctx.send(embed=self._error_embed(f"API error: {data['error']}"))
            return

        if not isinstance(data, dict):
            await ctx.send(embed=self._error_embed("Unexpected response format for user summary progress."))
            return

        points = data.get("Points") or data.get("TotalPoints") or 0
        possible = data.get("PossiblePoints") or data.get("PossiblePointsTotal") or 0
        unlocked = data.get("TotalAchievements") or data.get("AchievementsUnlocked") or 0
        possible_achs = data.get("PossibleAchievements") or data.get("TotalPossibleAchievements") or 0

        embed = discord.Embed(title=f"{cfg_username} — progress summary", color=COLOR_NEUTRAL)
        embed.add_field(name="Points", value=str(points), inline=True)
        embed.add_field(name="Possible Points", value=str(possible), inline=True)
        embed.add_field(name="Achievements unlocked", value=str(unlocked), inline=True)
        embed.add_field(name="Possible achievements", value=str(possible_achs), inline=True)
        embed.set_footer(text="Data from RetroAchievements.org")
        await ctx.send(embed=embed)

    @commands.is_owner()
    @retroachievements.command(name="raw")
    async def raw(self, ctx, endpoint: str, *, params: str = ""):
        """Owner-only: raw API request for debugging."""
        api_key = await self._ensure_api_key(ctx)
        if not api_key:
            return

        param_dict = {}
        if params:
            for pair in params.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    param_dict[k] = v
        if "y" not in param_dict:
            param_dict["y"] = await self.config.api_key()

        data = await self._api_get(endpoint, params=param_dict)
        if isinstance(data, str):
            await ctx.send(box(data[:1900]))
        else:
            try:
                s = str(data)
            except Exception:
                s = repr(data)
            await ctx.send(box(s[:1900]))
