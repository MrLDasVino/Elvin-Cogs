import aiohttp
import asyncio
import logging
import math
import random
import time
from typing import Optional, Dict, List, Any

from redbot.core import commands
import discord
import logging

logger = logging.getLogger(__name__)

def _safe_field_name(name: str, max_len: int = 256) -> str:
    if not name:
        return " "
    name = str(name)
    if len(name) <= max_len:
        return name
    return name[: max_len - 1].rstrip() + "…"

def _safe_field_value(value: str, max_len: int = 1024) -> str:
    if value is None:
        return ""
    value = str(value)
    if len(value) <= max_len:
        return value
    return value[: max_len - 1].rstrip() + "…"


class RadioBrowser(commands.Cog):
    """
    Radio Browser search with dropdowns and paged results.
    Commands:
      • [p]radio search [name|country|tag|language] <query>
      • [p]radio random
    """

    DEFAULT_SERVERS = [
        "https://all.api.radio-browser.info/json",
        "https://de2.api.radio-browser.info/json",
        "https://fi1.api.radio-browser.info/json",
    ]

    PAGE_SIZE = 10  # items per page
    SELECT_LIMIT = 25  # Discord select max options

    def __init__(self, bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        self._search_cache: Dict[int, List[dict]] = {}
        self.server_list = list(self.DEFAULT_SERVERS)

    async def cog_load(self):
        headers = {"User-Agent": "RedbotRadioCog/1.0 (+https://github.com/YourRepo)"}
        timeout = aiohttp.ClientTimeout(total=15)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout)

    async def cog_unload(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def _api_get(self, endpoint: str, params: Optional[Dict[str, Any]] = None):
        # Failure tracker: counts per (server, endpoint)
        assert self.session, "HTTP session not initialized"
        params = params or {}
        safe_params: Dict[str, str] = {}
        for k, v in params.items():
            if v is None:
                continue
            if isinstance(v, bool):
                safe_params[k] = "true" if v else "false"
            else:
                safe_params[k] = str(v)

        # initialize failure tracker store on the instance if not present
        if not hasattr(self, "_server_failures"):
            self._server_failures: Dict[tuple, int] = {}

        last_err: Optional[str] = None
        for base in list(self.server_list):
            key = (base, endpoint)
            # Skip mirrors that repeatedly failed for this endpoint
            if self._server_failures.get(key, 0) >= 3:
                logger.info("Skipping %s for %s due to repeated failures", base, endpoint)
                continue

            url = f"{base.rstrip('/')}/{endpoint.lstrip('/')}"
            for attempt in range(1, 3):
                try:
                    async with self.session.get(url, params=safe_params) as resp:
                        text = await resp.text()
                        if resp.status == 200:
                            # reset failure counter on success
                            self._server_failures.pop(key, None)
                            try:
                                return await resp.json(), None
                            except Exception as e:
                                last_err = f"Invalid JSON from {url}: {e}"
                                logger.exception(last_err)
                                break

                        if resp.status == 502:
                            last_err = f"502 from {url}"
                            logger.warning("Server %s attempt %s returned 502", base, attempt)
                            self._server_failures[key] = self._server_failures.get(key, 0) + 1
                        elif resp.status == 404:
                            last_err = f"404 from {url}"
                            logger.info("Server %s returned 404 for %s", base, endpoint)
                            self._server_failures[key] = self._server_failures.get(key, 0) + 1
                        else:
                            logger.debug("HTTP %s from %s: %s", resp.status, url, text[:200])
                            return None, f"HTTP {resp.status} from Radio Browser"

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    last_err = f"Network error contacting {url}: {e}"
                    logger.warning("Attempt %s to %s failed: %s", attempt, url, e)
                    self._server_failures[key] = self._server_failures.get(key, 0) + 1

                if attempt < 2:
                    await asyncio.sleep(0.5)

            # rotate server order so next call tries other mirrors first
            try:
                self.server_list.append(self.server_list.pop(0))
            except Exception:
                pass

        return None, last_err or "Unknown error fetching from Radio Browser"

    @commands.group(name="radio", invoke_without_command=True)
    async def radio(self, ctx: commands.Context):
        """Group command for Radio Browser integration."""
        await ctx.send_help()

    # ----------------------------
    # Interactive UI components
    # ----------------------------
    class _RadioSelect(discord.ui.Select):
        def __init__(self, parent_view: "RadioBrowser._ResultView", options: List[discord.SelectOption]):
            super().__init__(placeholder="Select a station...", min_values=1, max_values=1, options=options)
            self.parent_view = parent_view

        async def callback(self, interaction: discord.Interaction):
            # Reject if view already finished (timed out or already picked)
            if self.parent_view.is_finished():
                await interaction.response.send_message("This selection has expired.", ephemeral=True)
                return

            if interaction.user.id != self.parent_view.user_id:
                await interaction.response.send_message("Only the command author can pick a station.", ephemeral=True)
                return

            try:
                idx = int(self.values[0])
            except Exception:
                await interaction.response.send_message("Invalid selection.", ephemeral=True)
                return

            station = self.parent_view.all_results[idx]
            # store in cog cache
            self.parent_view.cog._search_cache[self.parent_view.user_id] = self.parent_view.all_results

            title = station.get("name", "Unknown station")
            stream = station.get("url_resolved") or station.get("url") or "No URL available"
            country = station.get("country") or station.get("countrycode") or "Unknown"
            language = station.get("language", "Unknown")

            embed = discord.Embed(title=_safe_field_name(title), color=discord.Color.random())
            embed.add_field(name=_safe_field_name("🔗 Stream URL"), value=_safe_field_value(stream), inline=False)
            embed.add_field(name=_safe_field_name("🌍 Country"), value=_safe_field_value(country), inline=True)
            embed.add_field(name=_safe_field_name("🗣️ Language"), value=_safe_field_value(language), inline=True)

            # Respond with chosen station, plus a Play button if we have a real URL
            if stream and stream != "No URL available":
                play_view = RadioBrowser._PlayButton(self.parent_view.cog, stream, self.parent_view.user_id)
                await interaction.response.send_message(embed=embed, view=play_view)
                play_view.message = await interaction.original_response()
            else:
                await interaction.response.send_message(embed=embed)
            # After a successful selection, disable everything and edit the original message to show it's closed
            self.parent_view._on_success_disable()
            try:
                await self.parent_view.message.edit(embed=self.parent_view._build_embed(disabled=True), view=self.parent_view)
            except Exception:
                pass
            self.parent_view.stop()

    class _PlayButton(discord.ui.View):
        """
        Small view with a single button that hands the station's stream URL
        off to another cog's play command (e.g. Red's core Audio cog).

        NOTE: This assumes there is a command registered on the bot called
        "play" that accepts the stream URL as a keyword argument named
        "query" (this matches Red's built-in Audio cog signature:
        `command_play(self, ctx, *, query: str)`). If your audio/music cog
        uses a different command name or parameter name, adjust
        PLAY_COMMAND_NAME / the ctx.invoke call below accordingly.
        """

        PLAY_COMMAND_NAME = "play"

        def __init__(self, cog: "RadioBrowser", stream_url: str, user_id: int, timeout: int = 300):
            super().__init__(timeout=timeout)
            self.cog = cog
            self.stream_url = stream_url
            self.user_id = user_id
            self.message: Optional[discord.Message] = None

        async def on_timeout(self):
            for child in list(self.children):
                try:
                    child.disabled = True
                except Exception:
                    pass
            if self.message:
                try:
                    await self.message.edit(view=self)
                except Exception:
                    pass

        @discord.ui.button(label="▶️ Play", style=discord.ButtonStyle.success)
        async def play_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message(
                    "Only the person who picked this station can play it.", ephemeral=True
                )
                return

            play_command = self.cog.bot.get_command(self.PLAY_COMMAND_NAME)
            if play_command is None:
                await interaction.response.send_message(
                    f"❌ No `{self.PLAY_COMMAND_NAME}` command is loaded on this bot "
                    "(is your audio cog loaded?).",
                    ephemeral=True,
                )
                return

            await interaction.response.defer(ephemeral=True)

            # Build a Context from the message the button lives on, then swap
            # the author for the person who actually clicked the button so
            # things like "join the clicker's voice channel" behave correctly.
            try:
                ctx = await self.cog.bot.get_context(interaction.message)
                ctx.author = interaction.user
            except Exception as e:
                logger.exception("Failed to build context for play button")
                await interaction.followup.send(f"❌ Couldn't prepare playback: {e}", ephemeral=True)
                return

            try:
                # NOTE: ctx.invoke() calls the command's callback directly and
                # skips its checks/cooldowns — fine for handing off a query,
                # but be aware if your play command relies on decorator-level
                # checks (e.g. @commands.guild_only()) rather than internal logic.
                await ctx.invoke(play_command, query=self.stream_url)
            except TypeError:
                # Fallback for cogs whose play command takes a positional arg
                # instead of a keyword-only "query".
                try:
                    await ctx.invoke(play_command, self.stream_url)
                except Exception as e:
                    logger.exception("Failed to invoke play command (positional fallback)")
                    await interaction.followup.send(f"❌ Couldn't start playback: {e}", ephemeral=True)
                    return
            except Exception as e:
                logger.exception("Failed to invoke play command")
                await interaction.followup.send(f"❌ Couldn't start playback: {e}", ephemeral=True)
                return

            button.disabled = True
            button.label = "▶️ Playing…"
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

            await interaction.followup.send("▶️ Sent to the player.", ephemeral=True)

    class _ResultView(discord.ui.View):
        def __init__(self, cog: "RadioBrowser", user_id: int, all_results: List[dict], page: int = 0, timeout: int = 120):
            super().__init__(timeout=timeout)
            self.cog = cog
            self.user_id = user_id
            self.all_results = all_results
            self.page = page
            self.page_size = RadioBrowser.PAGE_SIZE
            self.message: Optional[discord.Message] = None
            self.max_page = max(0, math.ceil(len(all_results) / self.page_size) - 1)
            self._disabled_flag = False
            self._refresh_children()

        def _page_slice(self):
            start = self.page * self.page_size
            end = start + self.page_size
            return start, min(end, len(self.all_results))

        def _build_select_options(self) -> List[discord.SelectOption]:
            start, end = self._page_slice()
            options: List[discord.SelectOption] = []
            for idx in range(start, end):
                station = self.all_results[idx]
                label = station.get("name") or f"Station {idx+1}"
                description = station.get("country") or station.get("language") or ""
                options.append(discord.SelectOption(label=label[:100], description=(description[:100] if description else None), value=str(idx)))
                if len(options) >= RadioBrowser.SELECT_LIMIT:
                    break
            return options

        def _refresh_children(self):
            # clear existing interactive children
            for item in list(self.children):
                self.remove_item(item)

            options = self._build_select_options()
            if options:
                select = RadioBrowser._RadioSelect(self, options)
                select.disabled = self._disabled_flag
                self.add_item(select)

            if self.max_page > 0:
                prev_btn = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary, disabled=self._disabled_flag)
                next_btn = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, disabled=self._disabled_flag)

                async def prev_callback(interaction: discord.Interaction):
                    if self.is_finished():
                        await interaction.response.send_message("This view has expired.", ephemeral=True)
                        return
                    if interaction.user.id != self.user_id:
                        await interaction.response.send_message("Only the command author can navigate pages.", ephemeral=True)
                        return
                    self.page = max(0, self.page - 1)
                    self._refresh_children()
                    embed = self._build_embed()
                    await interaction.response.edit_message(embed=embed, view=self)

                async def next_callback(interaction: discord.Interaction):
                    if self.is_finished():
                        await interaction.response.send_message("This view has expired.", ephemeral=True)
                        return
                    if interaction.user.id != self.user_id:
                        await interaction.response.send_message("Only the command author can navigate pages.", ephemeral=True)
                        return
                    self.page = min(self.max_page, self.page + 1)
                    self._refresh_children()
                    embed = self._build_embed()
                    await interaction.response.edit_message(embed=embed, view=self)

                prev_btn.callback = prev_callback
                next_btn.callback = next_callback
                self.add_item(prev_btn)
                self.add_item(next_btn)

        def _build_embed(self, disabled: bool = False) -> discord.Embed:
            start, end = self._page_slice()
            title = f"Search results — page {self.page+1}/{self.max_page+1}"
            if disabled:
                title = f"{title} (expired)"
            embed = discord.Embed(title=_safe_field_name(title), color=discord.Color.random())
            for i in range(start, end):
                station = self.all_results[i]
                name = station.get("name", "Unknown")
                country = station.get("country") or station.get("countrycode") or "Unknown"
                language = station.get("language", "Unknown")
                embed.add_field(
                    name=_safe_field_name(f"{i+1}. {name}"),
                    value=_safe_field_value(f"Country: {country} | Language: {language}"),
                    inline=False,
                )
            footer = "Use the dropdown to pick a station; only you can interact."
            if disabled:
                footer = "This view has expired. Re-run the search to get fresh results."
            embed.set_footer(text=footer)
            return embed

        def _on_success_disable(self):
            # Mark disabled, so future refreshes create disabled components
            self._disabled_flag = True
            for child in list(self.children):
                try:
                    child.disabled = True
                except Exception:
                    pass

        async def on_timeout(self):
            # mark disabled state and edit the original message to show it's expired
            self._disabled_flag = True
            for child in list(self.children):
                try:
                    child.disabled = True
                except Exception:
                    pass

            if self.message:
                try:
                    await self.message.edit(embed=self._build_embed(disabled=True), view=self)
                except Exception:
                    pass
            self.stop()

    # ----------------------------
    # Search command (with dropdowns)
    # ----------------------------
    @radio.command(name="search")
    async def radio_search(self, ctx: commands.Context, *args):
        if not args:
            return await ctx.send("Please provide something to search for.")

        key = args[0].lower()
        if key in ("name", "country", "tag", "language") and len(args) > 1:
            field, query = key, " ".join(args[1:])
        else:
            field, query = "name", " ".join(args)

        # request more items so user can page through them; keep reasonable upper bound
        limit = 50
        params = {field: query, "limit": limit, "hidebroken": True, "rand": int(time.time() * 1000)}
        data, error = await self._api_get("stations/search", params)

        if error:
            return await ctx.send(f"❌ {error}. Try again later.")
        if not data:
            return await ctx.send(f"No stations found for **{field}: {query}**.")

        # cache full results for the user
        self._search_cache[ctx.author.id] = data

        # build and send paged embed + interactive view
        view = RadioBrowser._ResultView(self, ctx.author.id, data, page=0, timeout=120)
        embed = view._build_embed()
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    # ----------------------------
    # Random command left intact
    # ----------------------------
    @radio.command(name="random")
    async def radio_random(self, ctx: commands.Context):
        """
        Fetch a random station and post the raw stream URL.
        """
        # 1) Try the dedicated random endpoint first; quick fallback to search if random isn't supported
        data, error = await self._api_get("stations/random", {"limit": 1, "rand": int(time.time() * 1000)})
        if error or not data:
            data, error = await self._api_get("stations/search", {"limit": 50, "order": "random", "hidebroken": True, "rand": random.randint(1, 1_000_000)})

        # 2) Final fallback: fetch a batch and pick locally if needed
        station = None
        if data and isinstance(data, list) and len(data) > 0:
            station = data[0] if len(data) == 1 else random.choice(data)
        else:
            batch, batch_err = await self._api_get("stations", {"limit": 100, "hidebroken": True, "rand": random.randint(1, 1_000_000)})
            if batch and isinstance(batch, list) and batch:
                station = random.choice(batch)
            else:
                return await ctx.send(f"❌ {error or batch_err or 'No station returned'}. Try again later.")

        title = station.get("name", "Random station")
        stream = station.get("url_resolved") or station.get("url") or "No URL available"
        country = station.get("country") or station.get("countrycode") or "Unknown"
        language = station.get("language", "Unknown")

        embed = discord.Embed(title=_safe_field_name("🎲 Random Radio Station"), color=discord.Color.random())
        embed.add_field(name=_safe_field_name(title), value=_safe_field_value(stream), inline=False)
        embed.add_field(name=_safe_field_name("🌍 Country"), value=_safe_field_value(country), inline=True)
        embed.add_field(name=_safe_field_name("🗣️ Language"), value=_safe_field_value(language), inline=True)

        if stream and stream != "No URL available":
            play_view = RadioBrowser._PlayButton(self, stream, ctx.author.id)
            play_view.message = await ctx.send(embed=embed, view=play_view)
        else:
            await ctx.send(embed=embed)
