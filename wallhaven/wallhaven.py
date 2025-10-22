import asyncio
import logging
import random
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse
import os

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
            msg = await interaction.followup.send(embed=embed, view=view)
            view.message = msg
        except commands.CommandError as e:
            await interaction.followup.send(f"API error: {e}", ephemeral=True)


class CategoryModal(ui.Modal, title="Wallhaven Category"):
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


class ImageNavView(ui.View):
    def __init__(self, cog, ctx, results: List[Dict[str, Any]], *, timeout: int = 60):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.ctx = ctx
        self.results = results
        self.index = 0

        options = []
        for i, r in enumerate(results[:25]):
            label = self._build_label(r, i)
            options.append(discord.SelectOption(label=label, value=str(i)))

        self.select = ui.Select(placeholder="Choose image", options=options, min_values=1, max_values=1)
        self.select.callback = self.on_select
        self.add_item(self.select)

    def _build_label(self, wall: Dict[str, Any], index: int) -> str:
        """
        Label priority:
        1. uploader — up to 3 tags (if uploader present)
        2. up to 3 tags
        3. cleaned filename (strip 'wallhaven-' and extension)
        4. fallback: 'wallhaven-<id> — <resolution> <purity>'
        Always prefix with '#{index+1} ' and limit length to Discord's safe range.
        """
        parts: List[str] = []

        # uploader username
        uploader = wall.get("uploader")
        uname = None
        if isinstance(uploader, dict):
            uname = uploader.get("username")
        if uname:
            parts.append(str(uname))

        # tags (try to extract up to 3 tag names)
        tag_names: List[str] = []
        tags = wall.get("tags")
        if isinstance(tags, list) and tags:
            for t in tags[:3]:
                if isinstance(t, dict):
                    tn = t.get("name")
                    if tn:
                        tag_names.append(tn)
                elif isinstance(t, str):
                    tag_names.append(t)
        if tag_names:
            tag_str = ", ".join(tag_names)
            if uname:
                parts.append("—")
                parts.append(tag_str)
            else:
                parts.append(tag_str)

        # cleaned filename fallback
        if not parts:
            path_url = wall.get("path") or wall.get("file") or (wall.get("thumbs") or {}).get("original")
            if path_url:
                try:
                    filename = os.path.basename(urlparse(path_url).path)
                    if filename:
                        name = filename
                        if name.lower().startswith("wallhaven-"):
                            name = name[len("wallhaven-"):]
                        name = os.path.splitext(name)[0]
                        if name:
                            parts.append(name)
                except Exception:
                    pass

        # final fallback: id + resolution + purity if available
        if not parts:
            wid = wall.get("id") or ""
            resolution = wall.get("resolution") or f"{wall.get('dimension_x','?')}x{wall.get('dimension_y','?')}"
            purity = wall.get("purity") or ""
            fallback = f"wallhaven-{wid}"
            extra = []
            if resolution:
                extra.append(str(resolution))
            if purity:
                extra.append(str(purity))
            if extra:
                fallback = f"{fallback} — {' '.join(extra)}"
            parts.append(fallback)

        # assemble, sanitize and trim
        label = " ".join(str(p) for p in parts if p)
        label = " ".join(label.split())
        label = f"#{index+1} {label}"
        if len(label) > 95:
            label = label[:92] + "..."
        return label

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

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, "message") and self.message:
                await self.message.edit(view=self)
        except Exception:
            logger.debug("Failed to edit message on ImageNavView timeout", exc_info=True)


class WallhavenMainView(ui.View):
    def __init__(self, cog: "WallhavenCog", ctx: commands.Context, *, timeout: int = 60):
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

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, "message") and self.message:
                await self.message.edit(content="Controls expired", view=self)
        except Exception:
            logger.debug("Failed to edit message on WallhavenMainView timeout", exc_info=True)


class WallhavenSetView(ui.View):
    def __init__(self, cog: "WallhavenCog", ctx: commands.Context, *, timeout: int = 60):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.ctx = ctx

    @ui.button(label="Apikey", style=discord.ButtonStyle.secondary)
    async def apikey_button(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._check_owner(interaction):
            return

        class APIKeyModal(ui.Modal, title="Set Wallhaven API Key"):
            key = ui.TextInput(label="API Key (leave empty to clear)", required=False, style=discord.TextStyle.short, max_length=200)

            async def on_submit(mod_inter: discord.Interaction):
                await interaction.response.defer()
                keyval = self.key.value.strip() or None
                await self.view.cog._set_apikey(self.view.ctx, keyval)
                await mod_inter.followup.send("API key updated.", ephemeral=True)

        modal = APIKeyModal()
        modal.view = self
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
            choice = ui.TextInput(
                label="Purity (sfw/sketchy/nsfw or 100/110/111)",
                required=True,
                style=discord.TextStyle.short,
                max_length=10,
                placeholder="e.g. sfw or 110"
            )

            async def on_submit(mod_inter: discord.Interaction):
                await interaction.response.defer()
                await self.view.cog._set_purity(self.view.ctx, self.choice.value.strip())
                await mod_inter.followup.send("Purity updated.", ephemeral=True)

        modal = PurityModal()
        modal.view = self
        await interaction.response.send_modal(modal)

    @ui.button(label="NSFW Toggle", style=discord.ButtonStyle.danger)
    async def nsfw_button(self, interaction: discord.Interaction, button: ui.Button):
        # allow bot owner or guild manage_guild permission
        if not await self._check_owner_or_guild_manage(interaction):
            return

        # require a configured API key before allowing NSFW toggling
        guild_conf = await self.cog.config.guild(self.ctx.guild).all()
        apikey = guild_conf.get("api_key")
        if not apikey:
            await interaction.response.send_message(
                "You must set a Wallhaven API key first via Apikey in this settings panel before toggling NSFW.",
                ephemeral=True
            )
            return

        current = await self.cog.config.guild(self.ctx.guild).nsfw_enabled()
        await self.cog.config.guild(self.ctx.guild).nsfw_enabled.set(not current)
        await interaction.response.send_message(
            f"NSFW posting set to {'enabled' if not current else 'disabled'} for this guild.",
            ephemeral=True
        )

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if not await self.cog.bot.is_owner(interaction.user):
            await interaction.response.send_message("Only the bot owner can change these settings.", ephemeral=True)
            return False
        return True

    async def _check_owner_or_guild_manage(self, interaction: discord.Interaction) -> bool:
        if await self.cog.bot.is_owner(interaction.user):
            return True
        if interaction.user.guild_permissions.manage_guild:
            return True
        await interaction.response.send_message("You must be the bot owner or have Manage Server permission to perform this action.", ephemeral=True)
        return False

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, "message") and self.message:
                await self.message.edit(content="Settings controls expired", view=self)
        except Exception:
            logger.debug("Failed to edit message on WallhavenSetView timeout", exc_info=True)


class WallhavenCog(commands.Cog):
    """Wallhaven wallpaper fetcher with combined interactive commands and 60s timeouts."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210123456)
        self.config.register_guild(**DEFAULTS)
        self._http: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[int, Dict[str, Any]] = {}

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

    @commands.group(name="wallhaven", invoke_without_command=True)
    async def wallhaven(self, ctx: commands.Context):
        """Open the Wallhaven interactive panel (Random, Search, Category)."""
        view = WallhavenMainView(self, ctx)
        msg = await ctx.send("Wallhaven: choose an action", view=view)
        view.message = msg

    @commands.group(name="wallhavenset", invoke_without_command=True)
    @checks.is_owner()
    async def wallhavenset(self, ctx: commands.Context):
        """Open the Wallhaven settings panel (apikey, categories, maxresults, purity, nsfw)."""
        view = WallhavenSetView(self, ctx)
        msg = await ctx.send("Wallhaven settings", view=view)
        view.message = msg

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
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

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
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

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
        """
        Accepts friendly names or 3-digit bitmasks:
        - sfw -> 100
        - sketchy -> 110
        - nsfw -> 111
        Or directly accept '100', '110', '111'.
        """
        p = purity.strip().lower()
        if p in ("sfw", "100"):
            await self.config.guild(ctx.guild).default_purity.set("100")
            await ctx.send("Purity set to SFW (100).")
            return
        if p in ("sketchy", "sketch", "110"):
            await self.config.guild(ctx.guild).default_purity.set("110")
            await ctx.send("Purity set to Sketchy allowed (110).")
            return
        if p in ("nsfw", "all", "111"):
            await self.config.guild(ctx.guild).default_purity.set("111")
            await ctx.send("Purity set to All (includes NSFW) (111).")
            return
        await ctx.send("Unknown purity option. Use one of: sfw, sketchy, nsfw, or a bitmask like 100, 110, 111.")


def setup(bot):
    bot.add_cog(WallhavenCog(bot))
