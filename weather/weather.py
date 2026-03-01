from redbot.core import commands, Config
import aiohttp
import discord
import random
import datetime
from typing import Optional, Tuple

DEFAULTS = {
    "units": "metric",  # "metric" -> Celsius, "imperial" -> Fahrenheit
    "default_location": None,  # optional per-guild default location string
}


WEATHERCODE_MAP = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _deg_to_compass(deg: Optional[float]) -> str:
    if deg is None:
        return "N/A"
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    ix = int((deg + 11.25) / 22.5) % 16
    return dirs[ix]


class Weather(commands.Cog):
    """Get current weather for any location using Open‑Meteo (no API key)."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xA1B2C3D4E5F60708)
        self.config.register_guild(**DEFAULTS)

    async def red_delete_data_for_user(self, **kwargs):
        """Nothing to delete."""
        return

    @commands.group()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def weatherset(self, ctx: commands.Context):
        """Guild configuration for the Weather cog (admin only)."""
        pass

    @weatherset.command(name="units")
    async def set_units(self, ctx: commands.Context, units: str):
        """Set default units for this guild: metric or imperial."""
        units = units.lower()
        if units not in ("metric", "imperial"):
            await ctx.send("Units must be `metric` or `imperial`.")
            return
        await self.config.guild(ctx.guild).units.set(units)
        await ctx.send(f"Default units set to **{units}**.")

    @weatherset.command(name="default")
    async def set_default_location(self, ctx: commands.Context, *, location: Optional[str] = None):
        """Set or clear a guild default location. Use no args to clear."""
        if not location:
            await self.config.guild(ctx.guild).default_location.set(None)
            await ctx.send("Cleared guild default location.")
            return
        await self.config.guild(ctx.guild).default_location.set(location.strip())
        await ctx.send(f"Guild default location set to **{location.strip()}**.")

    @commands.command(name="weather")
    async def weather_cmd(self, ctx: commands.Context, *, location: Optional[str] = None):
        """Show current weather for a location. Example: `[p]weather hamburg`"""
        guild_conf = await self.config.guild(ctx.guild).all()
        units = guild_conf.get("units", "metric")
        if not location:
            location = guild_conf.get("default_location")
            if not location:
                await ctx.send("No location provided and no guild default set. Example: `[p]weather Hamburg`.")
                return

        # Geocode location -> (name, lat, lon, country)
        geocode = await self._geocode(location)
        if geocode is None:
            await ctx.send(f"Could not find location: **{location}**")
            return
        name, lat, lon, country = geocode

        # Fetch weather from Open-Meteo
        weather = await self._fetch_open_meteo(lat, lon, units)
        if weather is None:
            await ctx.send("Failed to fetch weather data. Try again later.")
            return

        embed = self._build_embed(name, country, lat, lon, weather, units)
        await ctx.send(embed=embed)

    async def _geocode(self, query: str) -> Optional[Tuple[str, float, float, str]]:
        """Use Nominatim (OpenStreetMap) to geocode a place name to lat/lon."""
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": query, "format": "json", "limit": 1, "addressdetails": 1}
        headers = {"User-Agent": "Redbot-Weather-Cog/1.0 (contact: none)"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers, timeout=10) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    if not data:
                        return None
                    item = data[0]
                    display_name = item.get("display_name", query).split(",")[0]
                    lat = float(item["lat"])
                    lon = float(item["lon"])
                    address = item.get("address", {})
                    country = address.get("country", "")
                    return display_name, lat, lon, country
        except Exception:
            return None

    async def _fetch_open_meteo(self, lat: float, lon: float, units: str) -> Optional[dict]:
        """Fetch current weather from Open-Meteo. Returns JSON or None."""
        base = "https://api.open-meteo.com/v1/forecast"
        temp_unit = "celsius" if units == "metric" else "fahrenheit"
        params = {
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "timezone": "auto",
            "temperature_unit": temp_unit,
            "windspeed_unit": "kmh" if units == "metric" else "mph",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(base, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
        except Exception:
            return None

    def _build_embed(self, name: str, country: str, lat: float, lon: float, data: dict, units: str) -> discord.Embed:
        cw = data.get("current_weather", {})
        temp = cw.get("temperature")
        windspeed = cw.get("windspeed")
        winddir = cw.get("winddirection")
        weathercode = cw.get("weathercode")
        time_str = cw.get("time")
        elevation = data.get("elevation")

        desc = WEATHERCODE_MAP.get(weathercode, "Unknown")
        unit_symbol = "°C" if units == "metric" else "°F"
        wind_unit = "km/h" if units == "metric" else "mph"

        color = random.randint(0, 0xFFFFFF)
        title = f"Weather — {name}" + (f", {country}" if country else "")
        embed = discord.Embed(title=title, description=desc, color=color)
        embed.add_field(name="Temperature", value=f"{temp}{unit_symbol}", inline=True)
        embed.add_field(name="Wind", value=f"{windspeed} {wind_unit} ({_deg_to_compass(winddir)})", inline=True)
        embed.add_field(name="Wind direction", value=f"{winddir}°", inline=True)
        embed.add_field(name="Condition code", value=str(weathercode), inline=True)
        embed.add_field(name="Local time", value=time_str or "N/A", inline=True)
        embed.add_field(name="Elevation", value=f"{elevation} m" if elevation is not None else "N/A", inline=True)

        # Small footer and location coordinates
        embed.set_footer(text="Data provided by Open‑Meteo • Geocoding by Nominatim (OSM)")
        embed.timestamp = datetime.datetime.utcnow()
        embed.set_thumbnail(url=self._weathercode_to_thumbnail(weathercode))
        embed.add_field(name="Coordinates", value=f"{lat:.4f}, {lon:.4f}", inline=False)
        return embed

    def _weathercode_to_thumbnail(self, code: Optional[int]) -> Optional[str]:
        """Return a small icon URL for some weather codes (uses simple emoji-to-image mapping via twemoji CDN).
        This is optional; Open‑Meteo doesn't provide icons. Returns None for unknown."""
        if code is None:
            return None
        # Map broad categories to emoji
        if code == 0:
            emoji = "☀️"
        elif code in (1, 2):
            emoji = "🌤️"
        elif code == 3:
            emoji = "☁️"
        elif code in (45, 48):
            emoji = "🌫️"
        elif 51 <= code <= 57 or 61 <= code <= 67 or 80 <= code <= 82:
            emoji = "🌧️"
        elif 71 <= code <= 77 or 85 <= code <= 86:
            emoji = "❄️"
        elif 95 <= code <= 99:
            emoji = "⛈️"
        else:
            emoji = "🌈"
        # Convert emoji to twemoji PNG (simple approach)
        # Use the first codepoint of the emoji
        try:
            codepoint = "-".join(f"{ord(ch):x}" for ch in emoji)
            return f"https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{codepoint}.png"
        except Exception:
            return None
