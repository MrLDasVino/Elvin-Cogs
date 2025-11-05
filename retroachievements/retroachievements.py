import asyncio
import aiohttp
from typing import Optional, List
import discord
from redbot.core import commands, Config
from redbot.core.utils.chat_formatting import box

BASE_API = "https://retroachievements.org/API/"

# Colors
COLOR_INFO = 0x2ECC71
COLOR_WARN = 0xE67E22
COLOR_ERROR = 0xE74C3C
COLOR_NEUTRAL = 0x3498DB

PAGINATION_TIMEOUT = 120  # seconds
PAGINATION_EMOJIS = ("◀️", "▶️", "⛔")

class RetroAchievements(commands.Cog):
    """Interact with the RetroAchievements API."""

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.config = Config.get_conf(self, identifier=0xA1B2C3D4E7)
        default_global = {
            "api_key": None,
            "username": None
        }
        self.config.register_global(**default_global)

    def cog_unload(self):
        try:
            asyncio.create_task(self.session.close())
        except Exception:
            pass

    async def _api_get(self, endpoint: str, params: dict = None, timeout: int = 15):
        """
        Perform a GET against the RetroAchievements API.
        Returns parsed JSON when possible. For non-200 responses returns a dict with
        'error' and 'body' keys so you can see the API's response text for debugging.
        """
        url = BASE_API + endpoint
        headers = {
            "User-Agent": "RedBot/RetroAchievementsCog (+https://your.bot/info)",
            "Accept": "application/json, text/plain, */*",
        }
        try:
            async with self.session.get(url, params=params, headers=headers, timeout=timeout) as resp:
                text = await resp.text()
                # Successful response: try parse JSON, otherwise return raw text
                if resp.status == 200:
                    try:
                        return await resp.json(content_type=None)
                    except Exception:
                        return text
                # Non-200: return status and body so you can see the API message (e.g., 401 details)
                return {"error": f"HTTP {resp.status}", "body": text}
        except asyncio.TimeoutError:
            return {"error": "Request timed out"}
        except aiohttp.ClientError as e:
            return {"error": f"HTTP error: {e}"}
        except Exception as e:
            return {"error": f"Unexpected error: {e}"}

    async def _ensure_api_key(self, ctx):
        cfg = await self.config.all()
        api_key = cfg.get("api_key")
        if not api_key:
            await ctx.send(embed=self._error_embed("API key not configured. Use `retroachievements set <API_KEY> [default_username]` to configure."))
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

    # Simple paginator utility using embeds list
    async def _paginate_embeds(self, ctx, embeds: List[discord.Embed]):
        if not embeds:
            await ctx.send(embed=self._error_embed("Nothing to show."))
            return

        index = 0
        message = await ctx.send(embed=embeds[index])
        # add reactions if more than one page
        if len(embeds) > 1:
            try:
                for e in PAGINATION_EMOJIS:
                    await message.add_reaction(e)
            except Exception:
                # if bot cannot add reactions, just stop
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

    @commands.group(name="retroachievements", aliases=["ra"], invoke_without_command=True)
    @commands.guild_only()
    async def retroachievements(self, ctx):
        """Top-level RetroAchievements command."""
        await ctx.send_help(ctx.command)

    @retroachievements.command(name="set")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_credentials(self, ctx, api_key: Optional[str] = None, username: Optional[str] = None):
        """Set the RetroAchievements API key and optional default username.
        Examples:
        - `retroachievements set MY_API_KEY`
        - `retroachievements set MY_API_KEY myusername`
        - pass `-` for a value to clear it: `retroachievements set - -`
        """
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
        """Get a RetroAchievements user profile summary.
        Uses configured username if none is provided.
        """
        api_key = await self._ensure_api_key(ctx)
        if not api_key:
            return

        cfg_api, cfg_username = await self._get_auth(username)
        if not cfg_username:
            await ctx.send(embed=self._error_embed("No username configured and none provided. Provide a username or set a default with `retroachievements set <API_KEY> <username>`." ))
            return

        params = {"u": cfg_username, "y": api_key}
        data = await self._api_get("API_GetUserSummary.php", params=params)
        if isinstance(data, dict) and "error" in data:
            await ctx.send(embed=self._error_embed(f"API error: {data['error']}"))
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
            embed.set_thumbnail(url=avatar)

        if not embed.fields:
            await ctx.send(box(str(data)))
            return

        embed.set_footer(text="Data from RetroAchievements.org")
        await ctx.send(embed=embed)

    @retroachievements.command(name="game")
    async def game(self, ctx, game_id: int):
        """Get game info by RetroAchievements game ID."""
        api_key = await self._ensure_api_key(ctx)
        if not api_key:
            return

        params = {"i": str(game_id), "y": api_key}
        data = await self._api_get("API_GetGame.php", params=params)
        if isinstance(data, dict) and "error" in data:
            await ctx.send(embed=self._error_embed(f"API error: {data['error']}"))
            return

        if not isinstance(data, dict):
            await ctx.send(embed=self._error_embed("Unexpected API response format for game info."))
            return

        title = data.get("Title") or f"Game {game_id}"
        embed = discord.Embed(title=title, color=COLOR_NEUTRAL)
        embed.add_field(name="System", value=data.get("ConsoleName", "Unknown"), inline=True)
        embed.add_field(name="Publisher", value=data.get("Publisher", "Unknown"), inline=True)
        embed.add_field(name="Developer", value=data.get("Developer", "Unknown"), inline=True)
        embed.add_field(name="Achievements", value=str(data.get("AchievementCount", "Unknown")), inline=True)
        embed.add_field(name="Possible Points", value=str(data.get("PossiblePoints", "Unknown")), inline=True)

        desc = data.get("Description")
        if desc:
            embed.description = (desc[:2040] + "...") if len(desc) > 2048 else desc

        boxart = data.get("BoxArt")
        if boxart:
            embed.set_thumbnail(url=boxart)

        embed.set_footer(text="Data from RetroAchievements.org")
        await ctx.send(embed=embed)

    @retroachievements.command(name="recent")
    async def recent_global(self, ctx, limit: int = 5):
        """Show recent achievements unlocked globally.
        Limit defaults to 5 (max recommended 25).
        """
        api_key = await self._ensure_api_key(ctx)
        if not api_key:
            return

        limit = max(1, min(50, limit))
        params = {"c": str(limit), "y": api_key}
        data = await self._api_get("API_GetRecentAchievements.php", params=params)
        if isinstance(data, dict) and "error" in data:
            await ctx.send(embed=self._error_embed(f"API error: {data['error']}"))
            return

        if not isinstance(data, list) or not data:
            await ctx.send(embed=self._error_embed("No recent achievements found or unexpected response format."))
            return

        # Build pages of description (max ~12 lines per page for neatness)
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
            emb = discord.Embed(title="Recent RetroAchievements Unlocks", description="\n".join(lines[i:i+chunk_size]), color=COLOR_INFO)
            emb.set_footer(text=f"Showing {i+1}-{min(i+chunk_size, len(lines))} of {len(lines)}")
            pages.append(emb)

        await self._paginate_embeds(ctx, pages)

    @retroachievements.command(name="leaderboard", aliases=["top"])
    async def leaderboard(self, ctx, game_id: Optional[int] = None, top: int = 10):
        """Get global or per-game leaderboard.
        If game_id is provided, returns leaderboard for that game; otherwise global leaderboard.
        """
        api_key = await self._ensure_api_key(ctx)
        if not api_key:
            return

        top = max(1, min(50, top))
        if game_id:
            endpoint = "API_GetLeaderboard.php"
            params = {"i": str(game_id), "y": api_key}
        else:
            endpoint = "API_GetGlobalLeaderboard.php"
            params = {"c": str(top), "y": api_key}

        data = await self._api_get(endpoint, params=params)
        if isinstance(data, dict) and "error" in data:
            await ctx.send(embed=self._error_embed(f"API error: {data['error']}"))
            return

        if not isinstance(data, list) or not data:
            await ctx.send(embed=self._error_embed("No leaderboard data found or unexpected response format."))
            return

        lines = []
        for idx, e in enumerate(data[:top], start=1):
            name = e.get("UserName") or e.get("User") or e.get("Username") or "Unknown"
            pts = e.get("Points") or e.get("Score") or e.get("TotalPoints") or "0"
            lines.append(f"{idx}. **{name}** — {pts} pts")

        # Paginate lines
        pages = []
        chunk = 12
        for i in range(0, len(lines), chunk):
            emb = discord.Embed(title=(f"Leaderboard for game {game_id}" if game_id else "Global Leaderboard"), description="\n".join(lines[i:i+chunk]), color=COLOR_INFO)
            emb.set_footer(text=f"Showing {i+1}-{min(i+chunk, len(lines))} of {len(lines)}")
            pages.append(emb)

        await self._paginate_embeds(ctx, pages)

    @retroachievements.group(name="achievements", invoke_without_command=True)
    async def achievements_group(self, ctx):
        """Achievements related commands."""
        await ctx.send_help(ctx.command)

    @achievements_group.command(name="list")
    async def achievements_list(self, ctx, game_id: int, details: bool = False):
        """List achievements for a game.
        Use `details` True to show more info per achievement (may be long).
        """
        api_key = await self._ensure_api_key(ctx)
        if not api_key:
            return

        params = {"i": str(game_id), "y": api_key}
        data = await self._api_get("API_GetGame.php", params=params)
        if isinstance(data, dict) and "error" in data:
            await ctx.send(embed=self._error_embed(f"API error: {data['error']}"))
            return

        # Try to find achievements list in response
        achs = None
        for key in ("Achievements", "achievements", "AchievementList", "AchievementsList"):
            if isinstance(data, dict) and key in data:
                achs = data[key]
                break

        # Some API variants include an "achievements" top-level list
        if achs is None and isinstance(data, dict) and "AchievementCount" in data:
            # API didn't return the detailed list
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
            title = a.get("Title") or a.get("Name") or a.get("AchievementTitle") or "Unnamed"
            points = a.get("Points") or a.get("PointValue") or ""
            if details:
                desc = a.get("Description") or a.get("Detail") or ""
                lines.append(f"**{title}** — {points} pts — {desc}")
            else:
                lines.append(f"**{title}** — {points} pts")

        # Build paged embed list
        pages = []
        chunk = 10
        for i in range(0, len(lines), chunk):
            emb = discord.Embed(title=f"Achievements for Game {game_id}", description="\n".join(lines[i:i+chunk]), color=COLOR_NEUTRAL)
            emb.set_footer(text=f"Showing {i+1}-{min(i+chunk, len(lines))} of {len(lines)}")
            pages.append(emb)

        await self._paginate_embeds(ctx, pages)

    @retroachievements.command(name="recentgames")
    async def recent_games(self, ctx, username: Optional[str] = None, limit: int = 5):
        """Show recent games a user has played (based on recent achievements).
        Uses configured username if none provided.
        """
        api_key = await self._ensure_api_key(ctx)
        if not api_key:
            return

        cfg_api, cfg_username = await self._get_auth(username)
        if not cfg_username:
            await ctx.send(embed=self._error_embed("No username configured and none provided. Provide a username or set a default with `retroachievements set <API_KEY> <username>`." ))
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
            emb = discord.Embed(title=f"Recent games for {cfg_username}", description="\n".join(lines[i:i+chunk]), color=COLOR_INFO)
            emb.set_footer(text=f"Showing {i+1}-{min(i+chunk, len(lines))} of {len(lines)}")
            pages.append(emb)

        await self._paginate_embeds(ctx, pages)

    @retroachievements.command(name="progress")
    async def progress(self, ctx, username: Optional[str] = None, game_id: Optional[int] = None):
        """Show achievements progress.
        - If username and game_id provided: progress for that user in that game.
        - If username provided without game_id: summary progress for that user.
        - Uses configured username if none provided.
        """
        api_key = await self._ensure_api_key(ctx)
        if not api_key:
            return

        cfg_api, cfg_username = await self._get_auth(username)
        if not cfg_username:
            await ctx.send(embed=self._error_embed("No username configured and none provided. Provide a username or set a default with `retroachievements set <API_KEY> <username>`." ))
            return

        if game_id:
            params = {"u": cfg_username, "i": str(game_id), "y": api_key}
            data = await self._api_get("API_GetUnachieved.php", params=params)
            if isinstance(data, dict) and "error" in data:
                await ctx.send(embed=self._error_embed(f"API error: {data['error']}"))
                return

            if not isinstance(data, list):
                await ctx.send(embed=self._error_embed("Unexpected response format for per-game progress."))
                return

            total = len(data)
            if total == 0:
                await ctx.send(embed=self._info_embed("All achievements unlocked", f"{cfg_username} has unlocked all achievements for game {game_id}."))
                return

            lines = []
            for item in data:
                title = item.get("Title") or item.get("Name") or "Unnamed"
                points = item.get("Points") or ""
                lines.append(f"**{title}** — {points} pts")

            # Paginate unachieved list
            pages = []
            chunk = 10
            for i in range(0, len(lines), chunk):
                emb = discord.Embed(title=f"{cfg_username}'s unachieved on game {game_id}", description="\n".join(lines[i:i+chunk]), color=COLOR_WARN)
                emb.set_footer(text=f"{i+1}-{min(i+chunk, total)} of {total} unachieved")
                pages.append(emb)

            await self._paginate_embeds(ctx, pages)
            return

        # User summary
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
        """Owner-only: raw API request for debugging.
        endpoint should be the API endpoint file name, e.g., API_GetUserSummary.php
        params should be URL query string style: key1=val1&key2=val2
        """
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
            await ctx.send(box(str(data)[:1900]))
