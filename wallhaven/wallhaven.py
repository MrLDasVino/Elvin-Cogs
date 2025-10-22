import asyncio
import logging
import random
from typing import Optional, List, Dict, Any

import aiohttp
import discord
from discord import ui, Embed
from redbot.core import commands, Config, checks

logger = logging.getLogger(__name__)

BASE_API = "https://wallhaven.cc/api/v1"

DEFAULTS = {
    "api_key": None,
    "default_categories": "111",  # all
    "default_purity": "100",      # SFW by default
    "max_search_results": 24,
    "nsfw_enabled": False
}

CATEGORIES_MAP = {
    "general": "100",
    "anime": "010",
    "people": "001",
    "all": "111"
}

PURITY_SFW = "100"


def _make_embed(wall: Dict[str, Any], title_prefix: str = "Wallhaven"):
    title = f"{title_prefix} {wall.get('id', '')}"
    page_url = wall.get("url") or f"https://wallhaven.cc/w/{wall.get('id')}"
    image = wall.get("path") or wall.get("file") or (wall.get("thumbs") or {}).get("original")
    resolution = wall.get("resolution") or f"{wall.get('width', '?')}x{wall.get('height', '?')}"
    purity = wall.get("purity", "unknown")
    uploader = None
    uploader_data = wall.get("uploader")
    if isinstance(uploader_data, dict):
        uploader = uploader_data.get("username")
    embed = Embed(title=title, url=page_url, colour=0x2F3136)
    if image:
        embed.set_image(url=image)
    embed.add_field(name="Resolution", value=resolution, inline=True)
    embed.add_field(name="Purity", value=purity, inline=True)
    if uploader:
        embed.add_field(name="Uploader", value=uploader, inline=True)
    embed.set_footer(text="Source: wallhaven.cc")
    return embed


class ImageNavView(ui.View):
    def __init__(self, cog, ctx, results: List[Dict[str, Any]], *, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.ctx = ctx
        self.results = results
        self.index = 0
        options = []
        for i, r in enumerate(results[:25]):
            label = f"#{i+1} {r.get('id')}"
            options.append(discord.SelectOption(label=(label if len(label) <= 100 else label[:97] + "..."), value=str(i)))
        self.select = ui.Select(placeholder="Choose image", options=options, min_values=1, max_values=1)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.ctx.author.id

    async def on_select(self, interaction: discord.Interaction):
        try:
            idx = int(self.select.values[0])
            self.index = idx
            wall = self.results[self.index]
            if self.cog._is_nsfw_wall(wall) and not await self.cog._can_post_nsfw(self.ctx):
                await interaction.response.send_message("NSFW image blocked in this context", ephemeral=True)
                return
            embed = _make_embed(wall)
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            await interaction.response.send_message("Failed to show that image", ephemeral=True)

    @ui.button(label="Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: ui.Button):
        self.index = (self.index - 1) % len(self.results)
        wall = self.results[self.index]
        if self.cog._is_nsfw_wall(wall) and not await self.cog._can_post_nsfw(self.ctx):
            await interaction.response.send_message("NSFW image blocked in this context", ephemeral=True)
            return
        embed = _make_embed(wall)
        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        self.index = (self.index + 1) % len(self.results)
        wall = self.results[self.index]
        if self.cog._is_nsfw_wall(wall) and not await self.cog._can_post_nsfw(self.ctx):
            await interaction.response.send_message("NSFW image blocked in this context", ephemeral=True)
            return
        embed = _make_embed(wall)
        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="Random", style=discord.ButtonStyle.success)
    async def random_button(self, interaction: discord.Interaction, button: ui.Button):
        self.index = random.randrange(len(self.results))
        wall = self.results[self.index]
        if self.cog._is_nsfw_wall(wall) and not await self.cog._can_post_nsfw(self.ctx):
            await interaction.response.send_message("NSFW image blocked in this context", ephemeral=True)
            return
        embed = _make_embed(wall)
        await interaction.response.edit_message(embed=embed, view=self)




class WallhavenCog(commands.Cog):
    """Wallhaven wallpaper fetcher with interactive navigation."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210123456)
        self.config.register_guild(**DEFAULTS)
        self._http: Optional[aiohttp.ClientSession] = None

    def cog_unload(self):
        if self._http and not self._http.closed:
            asyncio.create_task(self._http.close())

    async def _session(self) -> aiohttp.ClientSession:
        if not self._http or self._http.closed:
            self._http = aiohttp.ClientSession()
        return self._http

    async def _call_api(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        sess = await self._session()
        url = f"{BASE_API}/{endpoint}"
        async with sess.get(url, params=params, timeout=30) as resp:
            text = await resp.text()
            # use module logger for diagnostics
            logger.warning("Wallhaven API request %s params=%s status=%s body=%s", resp.url, params, resp.status, text)
            if resp.status != 200:
                raise commands.CommandError(f"API returned {resp.status}: {text}")
            return await resp.json()

    async def _get_wallpaper_by_id(self, ctx: commands.Context, wall_id: str) -> Optional[Dict[str, Any]]:
        params = {}
        guild_conf = await self.config.guild(ctx.guild).all()
        apikey = guild_conf.get("api_key")
        if apikey:
            params["apikey"] = apikey
        # try /w/{id}
        try:
            data = await self._call_api(f"w/{wall_id}", params)
            return data.get("data")
        except commands.CommandError:
            # fallback to search?q=id
            try:
                params2 = params.copy()
                params2.update({"q": wall_id, "per_page": 1})
                search = await self._call_api("search", params2)
                results = search.get("data", [])
                return results[0] if results else None
            except commands.CommandError:
                return None

    async def _random_api(self, ctx: commands.Context, categories: str, purity: str) -> List[Dict[str, Any]]:
        """
        Return a list of wallpapers (one or more). Prefer /random, but fallback to search?sorting=random
        """
        params = {"purity": purity, "categories": categories}
        guild_conf = await self.config.guild(ctx.guild).all()
        apikey = guild_conf.get("api_key")
        if apikey:
            params["apikey"] = apikey
    
        # Try the /random API endpoint first
        try:
            data = await self._call_api("random", params)
            d = data.get("data")
            if not d:
                return []
            return d if isinstance(d, list) else [d]
        except commands.CommandError as exc:
            logger.warning("Wallhaven /random failed (%s), falling back to search?sorting=random", exc)
    
        # Fallback: use the search endpoint with sorting=random
        # Use per_page from config (limit to 24 or configured max)
        per_page = min(int(guild_conf.get("max_search_results", 24) or 24), 48)
        search_params = {
            "purity": purity,
            "categories": categories,
            "sorting": "random",
            "per_page": per_page,
            "page": 1,
        }
        if apikey:
            search_params["apikey"] = apikey
    
        try:
            data = await self._call_api("search", search_params)
            results = data.get("data", [])
            return results if isinstance(results, list) else (results and [results]) or []
        except commands.CommandError as exc:
            logger.warning("Wallhaven search?sorting=random fallback failed: %s", exc)
            # As a last resort try site redirect method (existing fallback)
            sess = await self._session()
            async with sess.get("https://wallhaven.cc/random", allow_redirects=False) as r:
                loc = r.headers.get("Location")
                if not loc:
                    return []
                wall_id = loc.rstrip("/").split("/")[-1]
                w = await self._get_wallpaper_by_id(ctx, wall_id)
                return [w] if w else []


    async def _search_api(self, ctx: commands.Context, q: Optional[str], categories: str, purity: str, per_page: int = 24, page: int = 1) -> List[Dict[str, Any]]:
        params = {"purity": purity, "categories": categories, "per_page": per_page, "page": page}
        if q:
            params["q"] = q
        guild_conf = await self.config.guild(ctx.guild).all()
        apikey = guild_conf.get("api_key")
        if apikey:
            params["apikey"] = apikey
        data = await self._call_api("search", params)
        return data.get("data", [])

    def _is_nsfw_wall(self, wall: Dict[str, Any]) -> bool:
        purity = str(wall.get("purity", "100"))
        if len(purity) >= 3:
            return purity[1] == "1" or purity[2] == "1"
        return False

    async def _can_post_nsfw(self, ctx: commands.Context) -> bool:
        if ctx.channel.is_nsfw():
            return True
        current = await self.config.guild(ctx.guild).nsfw_enabled()
        return bool(current)

    @commands.group(name="wallhaven", invoke_without_command=True)
    async def wallhaven(self, ctx: commands.Context, *, query: Optional[str] = None):
        """Wallhaven commands. Use subcommands random, search, category, nsfw."""
        if query:
            await ctx.invoke(self.search, query=query)
        else:
            await ctx.send_help(ctx.command)

    @wallhaven.command(name="random")
    async def random(self, ctx: commands.Context, category: Optional[str] = None):
        """Fetch random wallpapers. Optional category: general anime people all."""
        cfg = await self.config.guild(ctx.guild).all()
        categories = CATEGORIES_MAP.get((category or "").lower(), cfg.get("default_categories"))
        purity = cfg.get("default_purity", PURITY_SFW)
        async with ctx.typing():
            try:
                results = await self._random_api(ctx, categories, purity)
            except commands.CommandError as e:
                await ctx.send(f"API error: {e}")
                return
            if not results:
                await ctx.send("No random wallpapers returned.")
                return
            allowed = []
            for r in results:
                if self._is_nsfw_wall(r) and not await self._can_post_nsfw(ctx):
                    continue
                allowed.append(r)
            if not allowed:
                await ctx.send("Random results were NSFW and cannot be shown here. Enable NSFW for this guild or use an NSFW channel.")
                return
            view = ImageNavView(self, ctx, allowed)
            embed = _make_embed(allowed[0], title_prefix="Random")
            await ctx.send(embed=embed, view=view)

    @wallhaven.command(name="search")
    async def search(self, ctx: commands.Context, *, query: str):
        """Search Wallhaven and present interactive navigation for results."""
        cfg = await self.config.guild(ctx.guild).all()
        categories = cfg.get("default_categories")
        purity = cfg.get("default_purity", PURITY_SFW)
        per_page = cfg.get("max_search_results", 24)
        async with ctx.typing():
            try:
                results = await self._search_api(ctx, query, categories, purity, per_page=per_page)
            except commands.CommandError as e:
                await ctx.send(f"API error: {e}")
                return
            if not results:
                await ctx.send("No results found.")
                return
            filtered = []
            for r in results:
                if self._is_nsfw_wall(r) and not await self._can_post_nsfw(ctx):
                    continue
                filtered.append(r)
            if not filtered:
                await ctx.send("Search returned only NSFW results which cannot be shown here. Enable NSFW for this guild or use an NSFW channel.")
                return
            view = ImageNavView(self, ctx, filtered)
            embed = _make_embed(filtered[0], title_prefix=f"Search: {query}")
            await ctx.send(embed=embed, view=view)

    @wallhaven.command(name="category")
    async def category(self, ctx: commands.Context, category: str):
        """Quick search by category. Valid: general anime people all."""
        if category.lower() not in CATEGORIES_MAP:
            await ctx.send("Invalid category. Valid options: general anime people all.")
            return
        await ctx.invoke(self.random, category=category)

    @wallhaven.group(name="nsfw", invoke_without_command=True)
    @checks.admin_or_permissions(manage_guild=True)
    async def nsfw(self, ctx: commands.Context):
        """NSFW toggle group. Use nsfw toggle to enable or disable posting NSFW results."""
        await ctx.send_help(ctx.command)

    @nsfw.command(name="toggle")
    @checks.admin_or_permissions(manage_guild=True)
    async def nsfw_toggle(self, ctx: commands.Context):
        """Toggle NSFW for this guild."""
        current = await self.config.guild(ctx.guild).nsfw_enabled()
        await self.config.guild(ctx.guild).nsfw_enabled.set(not current)
        await ctx.send(f"NSFW posting set to {'enabled' if not current else 'disabled'} for this guild.")

    @commands.group(name="wallhavenset", invoke_without_command=True)
    @checks.is_owner()
    async def wallhavenset(self, ctx: commands.Context):
        """Owner-only configuration group."""
        await ctx.send_help(ctx.command)

    @wallhavenset.command(name="apikey")
    @checks.is_owner()
    async def set_apikey(self, ctx: commands.Context, key: Optional[str] = None):
        """Set or clear the Wallhaven API key for this guild."""
        if not key:
            await self.config.guild(ctx.guild).api_key.set(None)
            await ctx.send("API key cleared for this guild.")
            return
        await self.config.guild(ctx.guild).api_key.set(key)
        await ctx.send("API key saved for this guild.")

    @wallhavenset.command(name="purity")
    @checks.is_owner()
    async def set_purity(self, ctx: commands.Context, choice: str):
        """Set default purity for the guild. Use 'sfw' to restrict to SFW."""
        c = choice.strip().lower()
        if c == "sfw":
            await self.config.guild(ctx.guild).default_purity.set("100")
            await ctx.send("Purity set to SFW.")
            return
        await ctx.send("Unknown purity option. Use 'sfw' to restrict to SFW.")

    @wallhavenset.command(name="categories")
    @checks.is_owner()
    async def set_categories(self, ctx: commands.Context, choice: str):
        """Set default categories for the guild."""
        if choice.lower() not in CATEGORIES_MAP:
            await ctx.send("Invalid categories. Valid: general anime people all.")
            return
        await self.config.guild(ctx.guild).default_categories.set(CATEGORIES_MAP[choice.lower()])
        await ctx.send(f"Default categories set to {choice.lower()}.")

    @wallhavenset.command(name="maxresults")
    @checks.is_owner()
    async def set_maxresults(self, ctx: commands.Context, amount: int):
        """Set max results per search (1-48)."""
        if amount < 1 or amount > 48:
            await ctx.send("Provide a number between 1 and 48.")
            return
        await self.config.guild(ctx.guild).max_search_results.set(amount)
        await ctx.send(f"Max search results set to {amount}.")
