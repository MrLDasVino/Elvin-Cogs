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
    "default_purity": "100",      # SFW
    "max_search_results": 24,
    "nsfw_enabled": False,
}

CATEGORIES_MAP = {
    "general": "100",
    "anime": "010",
    "people": "001",
    "all": "111",
}

PURITY_SFW = "100"


def _make_embed(wall: Dict[str, Any], title_prefix: str = "Wallhaven"):
    title = f"{title_prefix} {wall.get('id', '')}"
    page_url = wall.get("url") or f"https://wallhaven.cc/w/{wall.get('id')}"
    image = wall.get("path") or wall.get("file") or (wall.get("thumbs") or {}).get("original")
    resolution = wall.get("resolution") or f"{wall.get('dimension_x', '?')}x{wall.get('dimension_y', '?')}"
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


class SearchModal(ui.Modal, title="Wallhaven Search"):
    query = ui.TextInput(label="Search query", style=discord.TextStyle.short, placeholder="mountains sunset", required=True, max_length=200)

    def __init__(self, cog, ctx):
        super().__init__()
        self.cog = cog
        self.ctx = ctx

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            cfg = await self.cog.config.guild(self.ctx.guild).all()
            categories = cfg.get("default_categories")
            purity = cfg.get("default_purity", PURITY_SFW)
            per_page = cfg.get("max_search_results", 24)
            results = await self.cog._search_api(self.ctx, self.query.value, categories, purity, per_page=per_page)
            if not results:
                await interaction.followup.send("No results found.", ephemeral=True)
                return
            filtered = []
            for r in results:
                if self.cog._is_nsfw_wall(r) and not await self.cog._can_post_nsfw(self.ctx):
                    continue
                filtered.append(r)
            if not filtered:
                await interaction.followup.send("Search returned only NSFW results which cannot be shown here.", ephemeral=True)
                return
            view = ImageNavView(self.cog, self.ctx, filtered)
            embed = _make_embed(filtered[0], title_prefix=f"Search: {self.query.value}")
            await interaction.followup.send(embed=embed, view=view)
        except commands.CommandError as e:
            await interaction.followup.send(f"API error: {e}", ephemeral=True)


class CategoryModal(ui.Modal, title="Wallhaven Category Search"):
    category = ui.TextInput(label="Category (general anime people all)", style=discord.TextStyle.short, required=True, max_length=20)

    def __init__(self, cog, ctx):
        super().__init__()
        self.cog = cog
        self.ctx = ctx

    async def on_submit(self, interaction: discord.Interaction):
        cat = self.category.value.strip().lower()
        if cat not in CATEGORIES_MAP:
            await interaction.response.send_message("Invalid category. Valid: general anime people all.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.cog.random(self.ctx, category=cat)


class EmptyModal(ui.Modal, title="Confirm"):
    # generic modal for confirmations/notes; one optional text field
    note = ui.TextInput(label="Note (optional)", style=discord.TextStyle.paragraph, required=False, max_length=300)

    def __init__(self, callback=None):
        super().__init__()
        self._callback = callback

    async def on_submit(self, interaction: discord.Interaction):
        if self._callback:
            await self._callback(interaction, self.note.value)
        else:
            await interaction.response.send_message("Confirmed.", ephemeral=True)


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
            label = label if len(label) <= 100 else label[:97] + "..."
            options.append(discord.SelectOption(label=label, value=str(i)))
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
    """Wallhaven wallpaper fetcher with combined interactive commands."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210123456)
        self.config.register_guild(**DEFAULTS)
        self._http: Optional[aiohttp.ClientSession] = None
        # simple per-guild short cache to avoid hammering the API on repeated clicks
        self._cache: Dict[int, Dict[str, Any]] = {}  # guild_id -> {"results": [...], "ts": float}

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
            logger.debug("Wallhaven API request %s params=%s status=%s", resp.url, params, resp.status)
            if resp.status != 200:
                short = text if len(text) < 400 else text[:400] + " ...[truncated]"
                logger.warning("Wallhaven API error %s params=%s status=%s body=%s", resp.url, params, resp.status, short)
                raise commands.CommandError(f"API returned {resp.status}: {text}")
            return await resp.json()

    async def _get_wallpaper_by_id(self, ctx: commands.Context, wall_id: str) -> Optional[Dict[str, Any]]:
        params = {}
        guild_conf = await self.config.guild(ctx.guild).all()
        apikey = guild_conf.get("api_key")
        if apikey:
            params["apikey"] = apikey
        try:
            data = await self._call_api(f"w/{wall_id}", params)
            return data.get("data")
        except commands.CommandError:
            try:
                params2 = params.copy()
                params2.update({"q": wall_id, "per_page": 1})
                search = await self._call_api("search", params2)
                results = search.get("data", [])
                return results[0] if results else None
            except commands.CommandError:
                return None

    async def _random_api(self, ctx: commands.Context, categories: str, purity: str) -> List[Dict[str, Any]]:
        guild_conf = await self.config.guild(ctx.guild).all()
        apikey = guild_conf.get("api_key")
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
        data = await self._call_api("search", search_params)
        results = data.get("data", [])
        return results if isinstance(results, list) else ([results] if results else [])

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

    # Combined interactive wallhaven command
    @commands.group(name="wallhaven", invoke_without_command=True)
    async def wallhaven(self, ctx: commands.Context):
        """Open the Wallhaven interactive panel (Random, Search, Category, NSFW)."""
        view = WallhavenMainView(self, ctx)
        await ctx.send("Wallhaven: choose an action", view=view)

    # Combined owner settings command
    @commands.group(name="wallhavenset", invoke_without_command=True)
    @checks.is_owner()
    async def wallhavenset(self, ctx: commands.Context):
        """Open the Wallhaven settings panel (apikey, categories, maxresults, purity)."""
        view = WallhavenSetView(self, ctx)
        await ctx.send("Wallhaven settings", view=view)

    # Backwards compatibility commands (call-through)
    @wallhaven.command(name="random", invoke_without_command=True)
    async def random(self, ctx: commands.Context, category: Optional[str] = None):
        cfg = await self.config.guild(ctx.guild).all()
        categories = CATEGORIES_MAP.get((category or "").lower(), cfg.get("default_categories"))
        purity = cfg.get("default_purity", PURITY_SFW)
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
            await ctx.send("Random results were NSFW and cannot be shown here.")
            return
        view = ImageNavView(self, ctx, allowed)
        embed = _make_embed(allowed[0], title_prefix="Random")
        await ctx.send(embed=embed, view=view)

    @wallhaven.command(name="search")
    async def legacy_search(self, ctx: commands.Context, *, query: str):
        cfg = await self.config.guild(ctx.guild).all()
        categories = cfg.get("default_categories")
        purity = cfg.get("default_purity", PURITY_SFW)
        per_page = cfg.get("max_search_results", 24)
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
            await ctx.send("Search returned only NSFW results which cannot be shown here.")
            return
        view = ImageNavView(self, ctx, filtered)
        embed = _make_embed(filtered[0], title_prefix=f"Search: {query}")
        await ctx.send(embed=embed, view=view)

    # owner-only settings helper methods used by modals/buttons
    async def _set_apikey(self, ctx: commands.Context, key: Optional[str]):
        await self.config.guild(ctx.guild).api_key.set(key)
        await ctx.send("API key updated for this guild.")

    async def _set_default_categories(self, ctx: commands.Context, choice: str):
        if choice.lower() not in CATEGORIES_MAP:
            await ctx.send("Invalid categories. Valid: general anime people all.")
            return
        await self.config.guild(ctx.guild).default_categories.set(CATEGORIES_MAP[choice.lower()])
        await ctx.send(f"Default categories set to {choice.lower()}.")

    async def _set_max_results(self, ctx: commands.Context, amount: int):
        if amount < 1 or amount > 48:
            await ctx.send("Provide a number between 1 and 48.")
            return
        await self.config.guild(ctx.guild).max_search_results.set(amount)
        await ctx.send(f"Max search results set to {amount}.")

    async def _set_purity(self, ctx: commands.Context, purity: str):
        p = purity.strip().lower()
        if p == "sfw":
            await self.config.guild(ctx.guild).default_purity.set("100")
            await ctx.send("Purity set to SFW.")
            return
        await ctx.send("Unknown purity option. Use 'sfw' to restrict to SFW.")


# Main view shown when user runs `wallhaven`
class WallhavenMainView(ui.View):
    def __init__(self, cog: WallhavenCog, ctx: commands.Context, *, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.ctx = ctx

    @ui.button(label="Random", style=discord.ButtonStyle.primary)
    async def random_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Only the command invoker can use these controls.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.cog.random(self.ctx)

    @ui.button(label="Search", style=discord.ButtonStyle.secondary)
    async def search_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Only the command invoker can use these controls.", ephemeral=True)
            return
        modal = SearchModal(self.cog, self.ctx)
        await interaction.response.send_modal(modal)

    @ui.button(label="Category", style=discord.ButtonStyle.secondary)
    async def category_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Only the command invoker can use these controls.", ephemeral=True)
            return
        modal = CategoryModal(self.cog, self.ctx)
        await interaction.response.send_modal(modal)

    @ui.button(label="NSFW Toggle", style=discord.ButtonStyle.danger)
    async def nsfw_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Only the command invoker can use these controls.", ephemeral=True)
            return
        # only allow guild admins to change guild NSFW toggle
        if not interaction.user.guild_permissions.manage_guild and not await self.cog.bot.is_owner(interaction.user):
            await interaction.response.send_message("You need Manage Server permission to toggle NSFW here.", ephemeral=True)
            return
        current = await self.cog.config.guild(self.ctx.guild).nsfw_enabled()
        await self.cog.config.guild(self.ctx.guild).nsfw_enabled.set(not current)
        await interaction.response.send_message(f"NSFW posting set to {'enabled' if not current else 'disabled'} for this guild.", ephemeral=True)


# Settings view shown when owner runs `wallhavenset`
class WallhavenSetView(ui.View):
    def __init__(self, cog: WallhavenCog, ctx: commands.Context, *, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.ctx = ctx

    @ui.button(label="Apikey", style=discord.ButtonStyle.secondary)
    async def apikey_button(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_owner(interaction):
            return
        # open a modal to set api key (empty to clear)
        class APIKeyModal(ui.Modal, title="Set Wallhaven API Key"):
            key = ui.TextInput(label="API Key (leave empty to clear)", required=False, style=discord.TextStyle.short, max_length=200)

            async def on_submit(mod_inter: discord.Interaction):
                await interaction.response.defer()
                keyval = self.key.value.strip() or None
                await self.view.cog._set_apikey(self.view.ctx, keyval)
                await mod_inter.followup.send("API key updated.", ephemeral=True)

        modal = APIKeyModal()
        modal.view = self  # provide backref used in on_submit
        await interaction.response.send_modal(modal)

    @ui.button(label="Categories", style=discord.ButtonStyle.secondary)
    async def categories_button(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_owner(interaction):
            return

        class CategoriesModal(ui.Modal, title="Set Default Categories"):
            choice = ui.TextInput(label="Choice (general anime people all)", required=True, style=discord.TextStyle.short, max_length=20)

            async def on_submit(mod_inter: discord.Interaction):
                await interaction.response.defer()
                await self.view.cog._set_default_categories(self.view.ctx, self.choice.value.strip())
                await mod_inter.followup.send("Default categories updated.", ephemeral=True)

        modal = CategoriesModal()
        modal.view = self
        await interaction.response.send_modal(modal)

    @ui.button(label="MaxResults", style=discord.ButtonStyle.secondary)
    async def maxresults_button(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_owner(interaction):
            return

        class MaxResultsModal(ui.Modal, title="Set Max Search Results"):
            amount = ui.TextInput(label="Amount (1-48)", required=True, style=discord.TextStyle.short, max_length=3)

            async def on_submit(mod_inter: discord.Interaction):
                await interaction.response.defer()
                try:
                    val = int(self.amount.value.strip())
                except ValueError:
                    await mod_inter.followup.send("Please provide a valid integer.", ephemeral=True)
                    return
                await self.view.cog._set_max_results(self.view.ctx, val)
                await mod_inter.followup.send("Max results updated.", ephemeral=True)

        modal = MaxResultsModal()
        modal.view = self
        await interaction.response.send_modal(modal)

    @ui.button(label="Purity", style=discord.ButtonStyle.secondary)
    async def purity_button(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_owner(interaction):
            return

        class PurityModal(ui.Modal, title="Set Purity"):
            choice = ui.TextInput(label="Choice (sfw)", required=True, style=discord.TextStyle.short, max_length=10)

            async def on_submit(mod_inter: discord.Interaction):
                await interaction.response.defer()
                await self.view.cog._set_purity(self.view.ctx, self.choice.value.strip())
                await mod_inter.followup.send("Purity updated.", ephemeral=True)

        modal = PurityModal()
        modal.view = self
        await interaction.response.send_modal(modal)

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if not await self.cog.bot.is_owner(interaction.user):
            await interaction.response.send_message("Only the bot owner can change these settings.", ephemeral=True)
            return False
        return True


def setup(bot):
    bot.add_cog(WallhavenCog(bot))
