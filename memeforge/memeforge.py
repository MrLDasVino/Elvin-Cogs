from __future__ import annotations

import logging
from typing import List, Optional

import aiohttp
import discord
from redbot.core import commands
from redbot.core.bot import Red

from .utils import build_image_url
from .views import TemplateBrowseView

log = logging.getLogger("red.memeforge")


class MemeForge(commands.Cog):
    """
    Create memes from a huge library of templates.
    """

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        self.templates: List[dict] = []
        self.api_base = "https://api.memegen.link"

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession()
        await self.refresh_templates()

    async def cog_unload(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def refresh_templates(self) -> bool:
        if self.session is None:
            return False
        try:
            async with self.session.get(f"{self.api_base}/templates/") as resp:
                if resp.status != 200:
                    log.warning("memegen.link returned status %s while fetching templates", resp.status)
                    return False
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, ValueError, TimeoutError) as error:
            log.warning("Failed to fetch meme templates: %s", error)
            return False
        if not isinstance(data, list):
            log.warning("Unexpected template payload shape from memegen.link: %r", type(data))
            return False
        data.sort(key=lambda t: t.get("name", t.get("id", "")).lower())
        self.templates = data
        return True

    def get_template(self, template_id: str) -> Optional[dict]:
        needle = template_id.lower()
        return next((t for t in self.templates if (t.get("id") or "").lower() == needle), None)

    async def finalize_meme(self, interaction: discord.Interaction, template: dict, collected: dict) -> None:
        template_id = template.get("id") or template.get("name") or "unknown"
        try:
            total_lines = max(0, int(template.get("lines", 0) or 0))
        except (TypeError, ValueError):
            total_lines = 0
        examples = (template.get("example") or {}).get("text") or []
        lines = []
        for i in range(total_lines):
            value = collected.get(i, "")
            if not value or not value.strip():
                value = examples[i] if i < len(examples) else ""
            lines.append(value)
        url = build_image_url(self.api_base, template_id, lines)
        embed = discord.Embed(
            title=template.get("name") or template_id,
            color=discord.Color.blurple(),
        )
        embed.set_image(url=url)
        embed.set_footer(
            text=f"Created by {interaction.user}",
            icon_url=interaction.user.display_avatar.url,
        )
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

    @commands.group(name="memeforge", invoke_without_command=True)
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.bot_has_permissions(embed_links=True)
    async def memeforge(self, ctx: commands.Context) -> None:
        """
        Browse meme templates and create your own meme.
        """
        if not self.templates:
            await self.refresh_templates()
        if not self.templates:
            await ctx.send(
                "Couldn't fetch meme templates right now. Please try again in a moment, "
                f"or ask the bot owner to run `{ctx.prefix}memeforge refresh`."
            )
            return
        view = TemplateBrowseView(self, ctx.author, self.templates)
        embed = view.build_embed()
        view.message = await ctx.send(embed=embed, view=view)

    @memeforge.command(name="search")
    @commands.bot_has_permissions(embed_links=True)
    async def memeforge_search(self, ctx: commands.Context, *, query: str) -> None:
        """
        Search meme templates by name and browse the results.
        """
        if not self.templates:
            await self.refresh_templates()
        filtered = [t for t in self.templates if query.lower() in t.get("name", "").lower()]
        if not filtered:
            await ctx.send(f"No templates found matching `{query}`.")
            return
        view = TemplateBrowseView(self, ctx.author, filtered)
        embed = view.build_embed()
        view.message = await ctx.send(embed=embed, view=view)

    @memeforge.command(name="info")
    @commands.bot_has_permissions(embed_links=True)
    async def memeforge_info(self, ctx: commands.Context, template_id: str) -> None:
        """
        Show details and a blank preview for a specific template ID.
        """
        if not self.templates:
            await self.refresh_templates()
        template = self.get_template(template_id)
        if not template:
            await ctx.send(
                f"No template found with id `{template_id}`. Use `{ctx.prefix}memeforge search` to find one."
            )
            return
        embed = discord.Embed(
            title=template.get("name", template["id"]),
            color=discord.Color.blurple(),
        )
        embed.set_image(url=template.get("blank"))
        embed.add_field(name="ID", value=f"`{template['id']}`", inline=True)
        embed.add_field(name="Text Lines", value=str(template.get("lines", 0)), inline=True)
        source = template.get("source")
        if source:
            embed.add_field(name="Source", value=source, inline=False)
        await ctx.send(embed=embed)

    @memeforge.command(name="refresh")
    @commands.is_owner()
    async def memeforge_refresh(self, ctx: commands.Context) -> None:
        """
        Refresh the cached meme template list from memegen.link. Bot owner only.
        """
        async with ctx.typing():
            success = await self.refresh_templates()
        if success:
            await ctx.send(f"Refreshed template cache. {len(self.templates)} templates loaded.")
        else:
            await ctx.send("Failed to refresh templates. The memegen.link API may be unavailable.")
