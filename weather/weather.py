from redbot.core import commands, Config
import aiohttp
import discord
import random
import datetime
from typing import Optional, Tuple

# --- Place your banner/thumbnail URLs here (fill the strings) ---
BANNER_URLS = {
    "clear": "https://files.catbox.moe/m6c3m7.png",
    "rain": "https://files.catbox.moe/2h3ra6.png",
    "thunder": "https://files.catbox.moe/72mmym.png",
    "snow": "https://files.catbox.moe/fao60b.png",
    "clouds": "https://files.catbox.moe/5hjndp.png",
    "fog": "https://files.catbox.moe/c1iwe3.png",
    "default": "https://files.catbox.moe/m6c3m7.png",
}

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
        # If the user runs the command with no args, show the help for this command
        if not location:
            try:
                await ctx.send_help(self.weather_cmd)
            except Exception:
                await ctx.send("Usage: `[p]weather <location>` — Example: `[p]weather Hamburg`")
            return

        guild_conf = await self.config.guild(ctx.guild).all()
        units = guild_conf.get("units", "metric")

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
        """Fetch current weather plus a simple daily forecast from Open-Meteo."""
        base = "https://api.open-meteo.com/v1/forecast"
        temp_unit = "celsius" if units == "metric" else "fahrenheit"
        params = {
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "timezone": "auto",
            "temperature_unit": temp_unit,
            "windspeed_unit": "kmh" if units == "metric" else "mph",
            # daily fields for a simple day forecast (several days)
            "daily": "temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(base, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
        except Exception:
            return None

    def _format_local_time(self, time_str: Optional[str], tz_name: Optional[str]) -> str:
        """Turn an ISO time string into a readable local time with optional timezone label."""
        if not time_str:
            return "N/A"
        try:
            # Open-Meteo typically returns a naive ISO string like "2026-03-02T01:00"
            dt = datetime.datetime.fromisoformat(time_str)
            # Format: Mon 02 Mar 2026 01:00
            pretty = dt.strftime("%a %d %b %Y %H:%M")
            if tz_name:
                return f"{pretty} ({tz_name})"
            return pretty
        except Exception:
            return time_str

    def _build_embed(self, name: str, country: str, lat: float, lon: float, data: dict, units: str) -> discord.Embed:
        cw = data.get("current_weather", {})
        temp = cw.get("temperature")
        windspeed = cw.get("windspeed")
        winddir = cw.get("winddirection")
        weathercode = cw.get("weathercode")
        time_str = cw.get("time")
        elevation = data.get("elevation")
        timezone_name = data.get("timezone")

        desc = WEATHERCODE_MAP.get(weathercode, "Unknown")
        unit_symbol = "°C" if units == "metric" else "°F"
        wind_unit = "km/h" if units == "metric" else "mph"

        # Choose a color and banner based on weather category
        category = self._weathercode_to_category(weathercode)
        color_map = {
            "clear": 0xFFD166,
            "clouds": 0xAAB2BD,
            "rain": 0x4A90E2,
            "thunder": 0x6B5B95,
            "snow": 0xBEE3F8,
            "fog": 0x9AA0A6,
            "default": random.randint(0, 0xFFFFFF),
        }
        color = color_map.get(category, random.randint(0, 0xFFFFFF))

        title = f"Weather — {name}" + (f", {country}" if country else "")
        embed = discord.Embed(title=title, description=desc, color=color)

        # Main fields (removed Feels like placeholder)
        embed.add_field(name="Temperature", value=f"{temp}{unit_symbol}" if temp is not None else "N/A", inline=True)
        embed.add_field(name="Wind", value=f"{windspeed} {wind_unit} ({_deg_to_compass(winddir)})" if windspeed is not None else "N/A", inline=True)
        embed.add_field(name="Wind direction", value=f"{winddir}°" if winddir is not None else "N/A", inline=True)
        embed.add_field(name="Condition code", value=str(weathercode) if weathercode is not None else "N/A", inline=True)

        # Format local time nicely
        pretty_time = self._format_local_time(time_str, timezone_name)
        embed.add_field(name="Local time", value=pretty_time, inline=True)

        embed.add_field(name="Elevation", value=f"{elevation} m" if elevation is not None else "N/A", inline=True)

        # Add "Today" and "Tomorrow" forecasts using daily data if available
        daily = data.get("daily", {})
        try:
            dates = daily.get("time", [])
            temps_max = daily.get("temperature_2m_max", [])
            temps_min = daily.get("temperature_2m_min", [])
            weathercodes = daily.get("weathercode", [])
            precip = daily.get("precipitation_sum", [])

            # find today's index by matching date portion of current time (fallback to index 0)
            today_idx = 0
            if time_str and dates:
                try:
                    current_date = datetime.datetime.fromisoformat(time_str).date().isoformat()
                    if current_date in dates:
                        today_idx = dates.index(current_date)
                except Exception:
                    today_idx = 0

            # Prepare today's forecast
            if dates and today_idx < len(dates):
                high = temps_max[today_idx] if today_idx < len(temps_max) else None
                low = temps_min[today_idx] if today_idx < len(temps_min) else None
                wc = weathercodes[today_idx] if today_idx < len(weathercodes) else None
                pr = precip[today_idx] if today_idx < len(precip) else None

                forecast_desc = WEATHERCODE_MAP.get(wc, "N/A")
                forecast_value = f"High {high}{unit_symbol} / Low {low}{unit_symbol}" if high is not None and low is not None else "N/A"
                precip_value = f"{pr} mm" if pr is not None else "N/A"

                # Add Today field (inline so it can appear next to Tomorrow)
                embed.add_field(name="Today", value=f"{forecast_desc}\n{forecast_value}\nPrecipitation: {precip_value}", inline=True)

            # Prepare tomorrow's forecast (today_idx + 1)
            tomorrow_idx = today_idx + 1
            if dates and tomorrow_idx < len(dates):
                thigh = temps_max[tomorrow_idx] if tomorrow_idx < len(temps_max) else None
                tlow = temps_min[tomorrow_idx] if tomorrow_idx < len(temps_min) else None
                twc = weathercodes[tomorrow_idx] if tomorrow_idx < len(weathercodes) else None
                tpr = precip[tomorrow_idx] if tomorrow_idx < len(precip) else None

                tforecast_desc = WEATHERCODE_MAP.get(twc, "N/A")
                tforecast_value = f"High {thigh}{unit_symbol} / Low {tlow}{unit_symbol}" if thigh is not None and tlow is not None else "N/A"
                tprecip_value = f"{tpr} mm" if tpr is not None else "N/A"

                # Add Tomorrow field inline next to Today
                embed.add_field(name="Tomorrow", value=f"{tforecast_desc}\n{tforecast_value}\nPrecipitation: {tprecip_value}", inline=True)
        except Exception:
            # silently ignore forecast parsing errors; don't break the embed
            pass

        # Coordinates and timestamp
        embed.add_field(name="Coordinates", value=f"{lat:.4f}, {lon:.4f}", inline=False)
        embed.timestamp = datetime.datetime.utcnow()

        # Set banner image (large) if provided, otherwise set a small thumbnail
        banner_url = BANNER_URLS.get(category) or BANNER_URLS.get("default")
        if banner_url:
            embed.set_image(url=banner_url)
        else:
            thumb = self._weathercode_to_thumbnail(weathercode)
            if thumb:
                embed.set_thumbnail(url=thumb)

        return embed

    def _weathercode_to_category(self, code: Optional[int]) -> str:
        """Map weather code to a broad category used for banners/colors."""
        if code is None:
            return "default"
        if code == 0:
            return "clear"
        if code in (1, 2, 3):
            return "clouds"
        if code in (45, 48):
            return "fog"
        if 51 <= code <= 57 or 61 <= code <= 67 or 80 <= code <= 82:
            return "rain"
        if 71 <= code <= 77 or 85 <= code <= 86:
            return "snow"
        if 95 <= code <= 99:
            return "thunder"
        return "default"

    def _weathercode_to_thumbnail(self, code: Optional[int]) -> Optional[str]:
        """Return a small icon URL for some weather codes (uses simple emoji-to-image mapping via twemoji CDN).
        This is optional; Open‑Meteo doesn't provide icons. Returns None for unknown."""
        # If a banner URL exists for the category, prefer that (handled in _build_embed).
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
        try:
            codepoint = "-".join(f"{ord(ch):x}" for ch in emoji)
            return f"https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{codepoint}.png"
        except Exception:
            return None
