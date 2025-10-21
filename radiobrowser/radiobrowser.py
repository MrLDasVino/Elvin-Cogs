import aiohttp
import asyncio
import logging
import random
import time
from typing import Optional, Tuple, List, Dict, Any

from redbot.core import commands
import discord

logger = logging.getLogger(__name__)


class RadioBrowser(commands.Cog):
    """
    Search and fetch radio stations from Radio Browser.
    Commands:
      • [p]radio search [name|country|tag|language] <query>
      • [p]radio pick <number>
      • [p]radio random
    """

    # Primary host plus fallback public servers. Using multiple servers improves reliability.
    DEFAULT_SERVERS = [
        "https://all.api.radio-browser.info/json",
        "https://de2.api.radio-browser.info/json",
        "https://fi1.api.radio-browser.info/json",
    ]

    def __init__(self, bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        self._search_cache: Dict[int, List[dict]] = {}
        self.server_list = list(self.DEFAULT_SERVERS)

    async def cog_load(self):
        """Initialize HTTP session when the cog loads."""
        headers = {"User-Agent": "RedbotRadioCog/1.0 (+https://github.com/YourRepo)"}
        timeout = aiohttp.ClientTimeout(total=15)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout)

    async def cog_unload(self):
        """Close HTTP session when the cog unloads."""
        if self.session and not self.session.closed:
            await self.session.close()

    async def _api_get(self, endpoint: str, params: Optional[Dict[str, Any]] = None
                      ) -> Tuple[Optional[Any], Optional[str]]:
        """
        Try to GET JSON from endpoint on available servers with retries and failover.
        Returns (data, error_message).
        """
        assert self.session, "HTTP session not initialized"

        params = params or {}
        # Convert Python booleans to lowercase strings, and None->omit
        safe_params: Dict[str, str] = {}
        for k, v in params.items():
            if v is None:
                continue
            if isinstance(v, bool):
                safe_params[k] = "true" if v else "false"
            else:
                safe_params[k] = str(v)

        last_err: Optional[str] = None

        # Try each server in order, with up to 2 attempts per server
        for base in self.server_list:
            url = f"{base.rstrip('/')}/{endpoint.lstrip('/')}"
            for attempt in range(1, 3):
                try:
                    async with self.session.get(url, params=safe_params) as resp:
                        text = await resp.text()
                        if resp.status == 200:
                            try:
                                return await resp.json(), None
                            except Exception as e:
                                last_err = f"Invalid JSON from {url}: {e}"
                                logger.exception(last_err)
                                break
                        if resp.status == 502:
                            last_err = f"502 from {url}"
                            logger.warning("Server %s attempt %s returned 502", base, attempt)
                        else:
                            logger.error("HTTP %s from %s: %s", resp.status, url, text[:200])
                            return None, f"HTTP {resp.status} from Radio Browser"
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    last_err = f"Network error contacting {url}: {e}"
                    logger.warning("Attempt %s to %s failed: %s", attempt, url, e)

                # small backoff between attempts for same server
                if attempt < 2:
                    await asyncio.sleep(1)

            # rotate server list: move this server to the back so next time we try others first
            try:
                self.server_list.append(self.server_list.pop(0))
            except Exception:
                pass

        return None, last_err or "Unknown error fetching from Radio Browser"

    @commands.group(name="radio", invoke_without_command=True)
    async def radio(self, ctx: commands.Context):
        """Group command for Radio Browser integration."""
        await ctx.send_help()

    @radio.command(name="search")
    async def radio_search(self, ctx: commands.Context, *args):
        """
        Search stations by name (default), country, tag or language.
        Examples:
          • [p]radio search Beatles
          • [p]radio search country Germany
          • [p]radio search tag rock
        """
        if not args:
            return await ctx.send("Please provide something to search for.")

        key = args[0].lower()
        if key in ("name", "country", "tag", "language") and len(args) > 1:
            field, query = key, " ".join(args[1:])
        else:
            field, query = "name", " ".join(args)

        params = {field: query, "limit": 10, "hidebroken": True}
        data, error = await self._api_get("stations/search", params)

        if error:
            return await ctx.send(f"❌ {error}. Try again later.")
        if not data:
            return await ctx.send(f"No stations found for **{field}: {query}**.")

        self._search_cache[ctx.author.id] = data
        embed = discord.Embed(
            title=f"Results — {field.title()}: {query}",
            color=discord.Color.random(),
        )
        for idx, station in enumerate(data, start=1):
            name = station.get("name", "Unknown")
            # prefer countrycode; older fields may be inconsistent across servers
            country = station.get("country") or station.get("countrycode") or "Unknown"
            language = station.get("language", "Unknown")
            embed.add_field(
                name=f"{idx}. {name}",
                value=f"Country: {country} | Language: {language}",
                inline=False,
            )
        embed.set_footer(text="Type [p]radio pick <number> to get the stream URL")
        await ctx.send(embed=embed)

    @radio.command(name="pick")
    async def radio_pick(self, ctx: commands.Context, number: int):
        """
        Pick one station from your last search results by its index.
        """
        cache = self._search_cache.get(ctx.author.id)
        if not cache:
            return await ctx.send("You have no recent search. Use `[p]radio search <query>` first.")
        if not (1 <= number <= len(cache)):
            return await ctx.send(f"Pick a number between 1 and {len(cache)}.")

        station = cache[number - 1]
        stream = station.get("url_resolved") or station.get("url") or "No URL available"
        embed = discord.Embed(
            title=station.get("name", "Unknown station"),
            color=discord.Color.random(),
        )
        embed.add_field(name="🔗 Stream URL", value=stream, inline=False)
        embed.add_field(name="🌍 Country", value=station.get("country") or station.get("countrycode") or "Unknown", inline=True)
        embed.add_field(name="🗣️ Language", value=station.get("language", "Unknown"), inline=True)
        await ctx.send(embed=embed)

    @radio.command(name="random")
    async def radio_random(self, ctx: commands.Context):
        """
        Fetch a random station with robust fallbacks and cache-busting to avoid identical results.
        """
        # 1) Try the dedicated random endpoint first
        data, error = await self._api_get("stations/random", {"limit": 1, "rand": int(time.time() * 1000)})
        # 2) If that fails or returns 404, try search with random ordering and a larger limit
        if error:
            data, error = await self._api_get("stations/search", {"limit": 50, "order": "random", "hidebroken": True, "rand": random.randint(1, 1_000_000)})
        # 3) Final fallback: fetch a small batch and pick locally
        station = None
        if not error and data:
            station = data[0]
        else:
            batch, batch_err = await self._api_get("stations", {"limit": 100, "hidebroken": True, "rand": random.randint(1, 1_000_000)})
            if batch and isinstance(batch, list):
                station = random.choice(batch)
            else:
                return await ctx.send(f"❌ {error or batch_err or 'No station returned'}. Try again later.")

        title = station.get("name", "Random station")
        stream = station.get("url_resolved") or station.get("url") or "No URL available"
        country = station.get("country") or station.get("countrycode") or "Unknown"
        language = station.get("language", "Unknown")

        embed = discord.Embed(
            title="🎲 Random Radio Station",
            color=discord.Color.random(),
        )
        embed.add_field(name=title, value=f"[Listen here]({stream})", inline=False)
        embed.add_field(name="🌍 Country", value=country, inline=True)
        embed.add_field(name="🗣️ Language", value=language, inline=True)
        await ctx.send(embed=embed)
