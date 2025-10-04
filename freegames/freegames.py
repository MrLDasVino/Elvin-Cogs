from typing import List, Optional
import asyncio
import aiohttp
import logging
import discord
from datetime import datetime

from redbot.core import commands, Config, checks
from redbot.core.bot import Red

log = logging.getLogger("red.freegames.embed")

API_BASE = "https://www.gamerpower.com/api/giveaways"
DEFAULT_INTERVAL = 300  # seconds (5 minutes)
MAX_EMBEDS_PER_POLL = 5


class freegames(commands.Cog):
    """Notify a role when new GamerPower giveaways appear using rich embeds."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xBEEFCAFE)
        default_guild = {
            "channel_id": None,
            "role_id": None,
            "platforms": [],
            "types": [],
            "interval": DEFAULT_INTERVAL,
            "seen_ids": [],
            "running": False,
        }
        self.config.register_guild(**default_guild)
        self._tasks = {}  # guild_id -> asyncio.Task
        self._session: Optional[aiohttp.ClientSession] = None

    def cog_unload(self):
        for task in self._tasks.values():
            task.cancel()

    async def _get_session(self):
        if self._session is None or self._session.closed:
            try:
                self._session = self.bot.http._HTTPClient__session  # type: ignore
            except Exception:
                self._session = aiohttp.ClientSession()
        return self._session

    async def _fetch_giveaways(self, params: dict) -> List[dict]:
        session = await self._get_session()
        async with session.get(API_BASE, params=params, timeout=20) as r:
            if r.status != 200:
                text = await r.text()
                log.warning("GamerPower API returned %s: %s", r.status, text)
                return []
            return await r.json()

    def _make_embed_for_item(self, item: dict) -> discord.Embed:
        title = item.get("title", "Unknown title")
        description = item.get("description") or ""
        url = item.get("open_giveaway_url") or item.get("url") or item.get("image") or ""
        platforms = item.get("platforms") or item.get("platform") or "Unknown"
        gtype = item.get("type") or "Unknown"
        worth = item.get("worth") or "N/A"
        image = item.get("image") or None
        end_date_raw = item.get("end_date") or item.get("end_time") or None

        embed = discord.Embed(title=title, url=url, description=description[:300] or "No description", color=0x2ECC71)
        embed.add_field(name="Platforms", value=str(platforms), inline=True)
        embed.add_field(name="Type", value=str(gtype), inline=True)
        embed.add_field(name="Worth", value=str(worth), inline=True)

        if end_date_raw:
            try:
                dt = datetime.fromisoformat(end_date_raw.replace("Z", "+00:00"))
                embed.add_field(name="Ends At (UTC)", value=dt.strftime("%Y-%m-%d %H:%M UTC"), inline=False)
            except Exception:
                embed.add_field(name="Ends At", value=str(end_date_raw), inline=False)

        if image:
            embed.set_thumbnail(url=image)

        embed.set_footer(text="Provided by GamerPower")
        return embed

    async def _poll_loop(self, guild):
        gid = guild.id
        while True:
            cfg = await self.config.guild(guild).all()
            channel_id = cfg["channel_id"]
            role_id = cfg["role_id"]
            platforms = cfg["platforms"]
            types = cfg["types"]
            interval = cfg["interval"]
            seen_ids = set(cfg["seen_ids"] or [])

            if not channel_id or not role_id:
                await asyncio.sleep(interval)
                continue

            params = {}
            if platforms:
                params["platform"] = ".".join(platforms)
            if types:
                params["type"] = ".".join(types)

            try:
                giveaways = await self._fetch_giveaways(params)
            except Exception as e:
                log.exception("Error fetching giveaways for guild %s: %s", gid, e)
                giveaways = []

            new_items = []
            for item in giveaways:
                gid_str = str(item.get("id") or item.get("giveaway_id") or item.get("title"))
                if gid_str not in seen_ids:
                    new_items.append(item)
                    seen_ids.add(gid_str)

            if new_items:
                channel = guild.get_channel(channel_id) or self.bot.get_channel(channel_id)
                if channel:
                    mention = f"<@&{role_id}>"
                    try:
                        await channel.send(mention + " New giveaways posted:")
                    except Exception:
                        log.exception("Failed to send role mention message in guild %s", gid)

                    for item in new_items[:MAX_EMBEDS_PER_POLL]:
                        embed = self._make_embed_for_item(item)
                        try:
                            await channel.send(embed=embed)
                        except Exception:
                            log.exception("Failed to send embed in guild %s for item %s", gid, item.get("title"))

                await self.config.guild(guild).seen_ids.set(list(seen_ids))

            await asyncio.sleep(max(10, interval))

    # Configuration commands

    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    @commands.group(name="freegames", invoke_without_command=True)
    async def freegames(self, ctx):
        """FreeGames notifier configuration commands."""

    @freegames.command(name="setchannel")
    async def fg_setchannel(self, ctx, channel: Optional[commands.TextChannelConverter]):
        """Set the channel where notifications will be posted."""
        cid = channel.id if channel else None
        await self.config.guild(ctx.guild).channel_id.set(cid)
        await ctx.send(f"Channel set to {channel.mention if channel else 'None'}.")

    @freegames.command(name="setrole")
    async def fg_setrole(self, ctx, role: Optional[commands.RoleConverter]):
        """Set the role to ping for new giveaways."""
        rid = role.id if role else None
        await self.config.guild(ctx.guild).role_id.set(rid)
        await ctx.send(f"Role set to {role.mention if role else 'None'}.")

    @freegames.command(name="setplatforms")
    async def fg_setplatforms(self, ctx, *, platforms: Optional[str] = None):
        """Set platforms separated by spaces or leave empty to clear. Examples: pc steam epic-games-store"""
        vals = platforms.split() if platforms else []
        await self.config.guild(ctx.guild).platforms.set(vals)
        await ctx.send(f"Platforms set to: {', '.join(vals) if vals else 'None'}.")

    @freegames.command(name="settypes")
    async def fg_settypes(self, ctx, *, types: Optional[str] = None):
        """Set giveaway types separated by spaces or leave empty to clear. Examples: game loot beta"""
        vals = types.split() if types else []
        await self.config.guild(ctx.guild).types.set(vals)
        await ctx.send(f"Types set to: {', '.join(vals) if vals else 'None'}.")

    @freegames.command(name="setinterval")
    async def fg_setinterval(self, ctx, seconds: int):
        """Set poll interval in seconds."""
        if seconds < 30:
            await ctx.send("Interval too low; set at least 30 seconds.")
            return
        await self.config.guild(ctx.guild).interval.set(seconds)
        await ctx.send(f"Polling interval set to {seconds} seconds.")

    @freegames.command(name="status")
    async def fg_status(self, ctx):
        """Show current configuration."""
        cfg = await self.config.guild(ctx.guild).all()
        channel = (
            ctx.guild.get_channel(cfg["channel_id"]) or self.bot.get_channel(cfg["channel_id"])
        )
        role = ctx.guild.get_role(cfg["role_id"]) if cfg["role_id"] else None
        embed_text = (
            f"Channel: {channel.mention if channel else 'None'}\n"
            f"Role: {role.mention if role else 'None'}\n"
            f"Platforms: {', '.join(cfg['platforms']) if cfg['platforms'] else 'All'}\n"
            f"Types: {', '.join(cfg['types']) if cfg['types'] else 'All'}\n"
            f"Interval: {cfg['interval']}s\n"
            f"Running: {cfg['running']}\n"
            f"Known giveaways saved: {len(cfg['seen_ids'] or [])}"
        )
        await ctx.send(embed=None, content=embed_text)

    @freegames.command(name="start")
    async def fg_start(self, ctx):
        """Start the polling task for this guild."""
        cfg = await self.config.guild(ctx.guild).all()
        if cfg["running"]:
            await ctx.send("Already running.")
            return
        task = self.bot.loop.create_task(self._poll_loop(ctx.guild))
        self._tasks[ctx.guild.id] = task
        await self.config.guild(ctx.guild).running.set(True)
        await ctx.send("Started polling for giveaways.")

    @freegames.command(name="stop")
    async def fg_stop(self, ctx):
        """Stop the polling task for this guild."""
        cfg = await self.config.guild(ctx.guild).all()
        if not cfg["running"]:
            await ctx.send("Not running.")
            return
        task = self._tasks.pop(ctx.guild.id, None)
        if task:
            task.cancel()
        await self.config.guild(ctx.guild).running.set(False)
        await ctx.send("Stopped polling for giveaways.")

    @freegames.command(name="test")
    @checks.admin_or_permissions(manage_guild=True)
    async def fg_test(self, ctx, commit: Optional[bool] = False):
        """Fetch current giveaways and post any new ones into this channel.

        Usage:
        [p]freegames test            - posts current unseen giveaways here (does NOT update seen_ids)
        [p]freegames test true       - posts and marks those giveaways as seen (updates seen_ids)
        """
        guild = ctx.guild
        cfg = await self.config.guild(guild).all()
        platforms = cfg["platforms"]
        types = cfg["types"]
        seen_ids = set(cfg["seen_ids"] or [])

        params = {}
        if platforms:
            params["platform"] = ".".join(platforms)
        if types:
            params["type"] = ".".join(types)

        try:
            giveaways = await self._fetch_giveaways(params)
        except Exception as e:
            log.exception("Error fetching giveaways for test in guild %s: %s", guild.id, e)
            await ctx.send("Failed to fetch giveaways from GamerPower.")
            return

        new_items = []
        for item in giveaways:
            gid_str = str(item.get("id") or item.get("giveaway_id") or item.get("title"))
            if gid_str not in seen_ids:
                new_items.append((gid_str, item))

        if not new_items:
            await ctx.send("No new giveaways found with your current filters.")
            return

        mention = f"<@&{cfg['role_id']}>" if cfg.get("role_id") else ""
        try:
            # Send single mention message in the command channel to ensure ping (if role configured)
            if mention:
                await ctx.send(mention + " New giveaways (test):")
            else:
                await ctx.send("New giveaways (test):")
        except Exception:
            log.exception("Failed to send mention message during test in guild %s", guild.id)

        posted_ids = []
        for gid_str, item in new_items[:MAX_EMBEDS_PER_POLL]:
            embed = self._make_embed_for_item(item)
            try:
                await ctx.send(embed=embed)
                posted_ids.append(gid_str)
            except Exception:
                log.exception("Failed to send test embed in guild %s for item %s", guild.id, item.get("title"))

        if commit and posted_ids:
            # merge posted ids into seen_ids and persist
            seen_ids.update(posted_ids)
            await self.config.guild(guild).seen_ids.set(list(seen_ids))
            await ctx.send(f"Marked {len(posted_ids)} giveaways as seen.")
        else:
            await ctx.send(f"Posted {len(posted_ids)} giveaways (not marked as seen).")

