import asyncio
import io
import json
import os
import random
from typing import Dict, List, Optional, Set, Tuple

import aiohttp
import discord
from redbot.core import commands, Config
from PIL import Image, ImageDraw, ImageOps, ImageFont

# File paths (stored next to this file)
BASE_DIR = os.path.dirname(__file__)
EVENTS_FILE = os.path.join(BASE_DIR, "events.json")
ENEMIES_FILE = os.path.join(BASE_DIR, "enemies.json")
GAMES_FILE = os.path.join(BASE_DIR, "games.json")
NPCS_FILE = os.path.join(BASE_DIR, "npcs.json")

# Default remote fallback URLs (set to real URLs or leave empty)
DEFAULT_NPC_URLS = [
    "https://files.catbox.moe/zgo9st.png",
    "https://files.catbox.moe/tlmusq.png",
]
DEFAULT_EVENT_URLS = [
    "https://files.catbox.moe/9p8hc6.png",
    "https://files.catbox.moe/2vqj0b.png",
]
DEFAULT_BG_URLS = [
    "https://files.catbox.moe/5vn581.png",
    "https://files.catbox.moe/xes0gm.png",
]
DEFAULT_VICTORY_URLS = [
    "https://files.catbox.moe/wyjekh.png",
    "https://files.catbox.moe/dbc0p2.png",
]

# Image constants
AVATAR_SIZE = 128
COMPOSITE_SIZE = (700, 260)

# Utilities for JSON persistence
def load_json_file(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_file(path: str, data):
    # simple atomic-ish write: write to temp then rename
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    try:
        os.replace(tmp, path)
    except Exception:
        # fallback
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# Persistent loaders
def load_events() -> List[Dict]:
    return load_json_file(EVENTS_FILE, [])


def load_enemy_templates() -> List[Dict]:
    return load_json_file(ENEMIES_FILE, [])


class JoinView(discord.ui.View):
    """Persistent Join button view for signups."""

    def __init__(self, cog: "BattleRoyale", signup_message_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.signup_message_id = signup_message_id

    @discord.ui.button(label="Join", style=discord.ButtonStyle.green, custom_id="battleroyale_join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # NOTE: parameter order is (interaction, button)
        if not interaction.guild:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return

        game = self.cog.active_games.get(self.signup_message_id)
        if not game:
            await interaction.response.send_message("This signup is no longer active.", ephemeral=True)
            return

        # Prevent joining after the game has started
        if game.get("running"):
            await interaction.response.send_message("This signup is closed — the game has already started.", ephemeral=True)
            return

        user = interaction.user
        if user.id in game["players"]:
            await interaction.response.send_message("You're already signed up.", ephemeral=True)
            return

        game["players"].append(user.id)
        await self.cog._save_games()
        await interaction.response.send_message("You joined the Battle Royale!", ephemeral=True)


class SelectView(discord.ui.View):
    """Dropdown for selecting which signup to start."""

    def __init__(self, cog: "BattleRoyale", guild_id: int, author_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.author_id = author_id
        self.selected_game_id: Optional[int] = None

    @discord.ui.select(placeholder="Select a signup to start", min_values=1, max_values=1, options=[])
    async def select_callback(self, select: discord.ui.Select, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("You are not allowed to choose for this prompt.", ephemeral=True)
            return
        try:
            self.selected_game_id = int(select.values[0])
        except Exception:
            self.selected_game_id = None
        await interaction.response.defer(ephemeral=True)
        self.stop()

    async def on_timeout(self):
        # nothing special
        pass


class BattleRoyale(commands.Cog):
    """Battle Royale game cog with persistence, NPCs, events, and image composition."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # load persisted data
        self.events: List[Dict] = load_events()
        self.enemy_templates: List[Dict] = load_enemy_templates()

        # active_games keyed by signup_message_id (int)
        raw_games = load_json_file(GAMES_FILE, {})
        self.active_games: Dict[int, Dict] = {}
        for k, v in raw_games.items():
            try:
                self.active_games[int(k)] = v
            except Exception:
                continue

        # npc_instances persisted: keys are negative ints stored as strings in JSON
        raw_npcs = load_json_file(NPCS_FILE, {"instances": {}, "next_npc_id": -1})
        self.npc_instances: Dict[int, Dict] = {}
        for k, v in raw_npcs.get("instances", {}).items():
            try:
                self.npc_instances[int(k)] = v
            except Exception:
                continue
        self.next_npc_id: int = int(raw_npcs.get("next_npc_id", -1))

        # aiohttp session for fetching avatars and images
        self.session = aiohttp.ClientSession()

        # simple in-memory cache for fetched image bytes keyed by URL
        self._image_cache: Dict[str, bytes] = {}

        # file locks for safe concurrent writes
        self._games_lock = asyncio.Lock()
        self._npcs_lock = asyncio.Lock()
        self._events_lock = asyncio.Lock()
        self._templates_lock = asyncio.Lock()

        # restore persistent views after bot ready
        bot.loop.create_task(self._restore_views())

        # Config (optional) - you can store default URL lists here if you want runtime configuration
        self.config = Config.get_conf(self, identifier=123456789012345678)
        self.config.register_global(
            default_npc_urls=[],
            default_event_urls=[],
            default_bg_urls=[],
        )

    def cog_unload(self):
        # schedule session close
        try:
            asyncio.create_task(self.session.close())
        except Exception:
            pass

    # -----------------------
    # Persistence helpers
    # -----------------------
    async def _save_games(self):
        async with self._games_lock:
            serial = {str(k): v for k, v in self.active_games.items()}
            save_json_file(GAMES_FILE, serial)

    async def _save_npcs(self):
        async with self._npcs_lock:
            serial = {"instances": {str(k): v for k, v in self.npc_instances.items()}, "next_npc_id": self.next_npc_id}
            save_json_file(NPCS_FILE, serial)

    async def _save_events(self):
        async with self._events_lock:
            save_json_file(EVENTS_FILE, self.events)

    async def _save_templates(self):
        async with self._templates_lock:
            save_json_file(ENEMIES_FILE, self.enemy_templates)

    async def _restore_views(self):
        """Re-register JoinView for persisted signups whose messages still exist."""
        await self.bot.wait_until_ready()
        for mid, game in list(self.active_games.items()):
            try:
                guild = self.bot.get_guild(game["guild_id"])
                if not guild:
                    continue
                channel = guild.get_channel(game["channel_id"])
                if not channel:
                    continue
                try:
                    await channel.fetch_message(mid)
                except Exception:
                    # message missing: skip (do not remove automatically)
                    continue
                # Only restore view if the signup is not running
                if game.get("running"):
                    continue
                view = JoinView(self, signup_message_id=mid)
                try:
                    self.bot.add_view(view, message_id=mid)
                except Exception:
                    pass
            except Exception:
                continue
        # ensure persisted files exist
        await self._save_games()
        await self._save_npcs()

    # -----------------------
    # Utilities
    # -----------------------
    def is_mod_or_admin(self, member: discord.Member) -> bool:
        return (
            member.guild_permissions.manage_guild
            or member.guild_permissions.kick_members
            or member.guild_permissions.manage_messages
            or member.guild_permissions.administrator
        )

    def _random_color(self) -> discord.Color:
        r, g, b = random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)
        return discord.Color.from_rgb(r, g, b)

    # -----------------------
    # Pillow text-size compatibility helper
    # -----------------------
    def _get_text_size(self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
        """
        Return (width, height) of rendered text in a Pillow-version-compatible way.
        Prefers draw.textbbox, falls back to draw.textsize or font.getsize.
        """
        try:
            # Pillow >= 8.0: textbbox gives (left, top, right, bottom)
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            pass

        try:
            # Older Pillow: textsize may exist
            return draw.textsize(text, font=font)
        except Exception:
            pass

        try:
            # Fallback to font.getsize (may be deprecated but still present)
            return font.getsize(text)
        except Exception:
            # Last resort
            return (0, 0)

    # -----------------------
    # Image helpers (fetching, fallbacks, caching)
    # -----------------------
    async def _fetch_image_bytes(self, url: Optional[str], timeout: int = 8) -> Optional[bytes]:
        """Fetch image bytes from a URL. Return None on failure. Uses simple in-memory cache."""
        if not url:
            return None
        # return cached bytes if present
        if url in self._image_cache:
            return self._image_cache[url]
        try:
            # simple headers to avoid some servers rejecting requests
            headers = {"User-Agent": "RedBot-BattleRoyale/1.0 (+https://example.invalid/)"}
            async with self.session.get(url, timeout=timeout, headers=headers, allow_redirects=True) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    # cache it
                    self._image_cache[url] = data
                    return data
        except Exception:
            return None
        return None

    def _open_fallback_image(self, size=(AVATAR_SIZE, AVATAR_SIZE)) -> Image.Image:
        """Create a simple placeholder image (used when no URL is available or fetch fails)."""
        img = Image.new("RGBA", size, (90, 90, 90, 255))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default()
            text = "No Image"
            tw, th = self._get_text_size(draw, text, font)
            draw.text(((size[0] - tw) // 2, (size[1] - th) // 2), text, fill=(255, 255, 255, 230), font=font)
        except Exception:
            pass
        return img

    async def _load_image_for_entity(
        self,
        image_url: Optional[str],
        default_url_list: Optional[List[str]],
        size=(AVATAR_SIZE, AVATAR_SIZE),
        default_type: Optional[str] = None,  # "npc", "event", "bg", "pvp" for config lookup
        npc_instance: Optional[Dict] = None,  # pass npc instance dict when available
    ) -> Image.Image:
        """
        Try in order:
          1. image_url (entity-specific)
          2. random default URL from default_url_list (if provided)
          3. configured defaults from self.config (based on default_type)
          4. module DEFAULT_* lists
          5. for NPCs: try enemy_templates that have image_url
          6. generated placeholder
        Returns a PIL Image resized to `size`.
        """
        img_bytes = None

        # 1) try explicit entity URL
        if image_url:
            img_bytes = await self._fetch_image_bytes(image_url)

        # 2) try provided default_url_list
        if not img_bytes and default_url_list:
            candidates = [u for u in default_url_list if u]
            random.shuffle(candidates)
            for candidate in candidates:
                img_bytes = await self._fetch_image_bytes(candidate)
                if img_bytes:
                    break

        # 3) try configured defaults from self.config if default_type provided
        if not img_bytes and default_type:
            try:
                if default_type == "npc":
                    cfg_list = await self.config.default_npc_urls()
                elif default_type == "event":
                    cfg_list = await self.config.default_event_urls()
                elif default_type in ("bg", "pvp"):
                    # pvp intentionally uses the same config as bg
                    cfg_list = await self.config.default_bg_urls()
                else:
                    cfg_list = []
            except Exception:
                cfg_list = []

            if cfg_list:
                candidates = [u for u in cfg_list if u]
                random.shuffle(candidates)
                for candidate in candidates:
                    img_bytes = await self._fetch_image_bytes(candidate)
                    if img_bytes:
                        break

        # 4) try module-level DEFAULT_* lists as a last remote fallback
        if not img_bytes and default_type:
            fallback_list = []
            if default_type == "npc":
                fallback_list = DEFAULT_NPC_URLS
            elif default_type == "event":
                fallback_list = DEFAULT_EVENT_URLS
            elif default_type in ("bg", "pvp"):
                # pvp uses the same module-level fallbacks as bg
                fallback_list = DEFAULT_BG_URLS

            if fallback_list:
                candidates = [u for u in fallback_list if u]
                random.shuffle(candidates)
                for candidate in candidates:
                    img_bytes = await self._fetch_image_bytes(candidate)
                    if img_bytes:
                        break

        # 5) for NPCs, try enemy_templates images if still nothing
        if not img_bytes and default_type == "npc":
            # try the npc_instance's template image first (if provided)
            if npc_instance:
                tpl_url = npc_instance.get("image_url")
                if tpl_url:
                    img_bytes = await self._fetch_image_bytes(tpl_url)
            # otherwise try any enemy template that has an image_url
            if not img_bytes and self.enemy_templates:
                candidates = [t.get("image_url") for t in self.enemy_templates if t.get("image_url")]
                random.shuffle(candidates)
                for candidate in candidates:
                    img_bytes = await self._fetch_image_bytes(candidate)
                    if img_bytes:
                        break

        img = None
        if img_bytes:
            try:
                img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
            except Exception:
                img = None

        # 6) fallback placeholder
        if img is None:
            img = self._open_fallback_image(size=size)

        # fit to requested size
        try:
            img = ImageOps.fit(img, size, Image.LANCZOS)
        except Exception:
            img = img.resize(size)

        return img

    def _apply_dead_overlay(self, img: Image.Image) -> Image.Image:
        """
        Convert avatar to grayscale and overlay a semi-opaque red X.
        Returns an RGBA image the same size as input.
        """
        try:
            # Convert to grayscale then back to RGBA so we keep an alpha channel
            gray = ImageOps.grayscale(img).convert("RGBA")

            w, h = gray.size
            draw = ImageDraw.Draw(gray)

            # Red X parameters
            line_width = max(6, int(min(w, h) * 0.12))  # thick X
            red = (220, 20, 20, 220)  # semi-opaque red

            # Draw two diagonal lines across the avatar
            draw.line((0, 0, w, h), fill=red, width=line_width)
            draw.line((w, 0, 0, h), fill=red, width=line_width)

            return gray
        except Exception:
            # If anything fails, return original image
            return img

    # -----------------------
    # Commands
    # -----------------------
    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    async def battleroyale(self, ctx: commands.Context):
        """Battle Royale commands group."""
        await ctx.send_help(ctx.command)


    @battleroyale.command(name="signup")
    @commands.guild_only()
    async def signup(self, ctx: commands.Context, channel: discord.TextChannel):
        """Create a signup embed in the specified channel (mods/admins only)."""
        if not self.is_mod_or_admin(ctx.author):
            await ctx.send("You need to be a moderator or admin to create a signup.")
            return

        color = self._random_color()
        embed = discord.Embed(
            title="Battle Royale Signup",
            description="Click **Join** to enter the next Battle Royale. Mods can add NPCs with `battleroyale addnpc`.",
            color=color,
        )
        embed.set_footer(text=f"Signup created by {ctx.author.display_name}")
        view = JoinView(self, signup_message_id=0)

        msg = await channel.send(embed=embed, view=view)
        game = {
            "signup_message_id": msg.id,
            "channel_id": channel.id,
            "guild_id": ctx.guild.id,
            "creator_id": ctx.author.id,
            "players": [],  # real user IDs and NPC instance IDs (negative ints)
            "running": False,
        }
        self.active_games[msg.id] = game
        view.signup_message_id = msg.id

        try:
            self.bot.add_view(view, message_id=msg.id)
        except Exception:
            pass

        await self._save_games()
        await ctx.send(f"Signup posted in {channel.mention} (message id {msg.id}).")

    # -----------------------
    # Enemy template management
    # -----------------------
    @battleroyale.group(name="enemy", invoke_without_command=True)
    async def enemy(self, ctx: commands.Context):
        """Manage NPC enemy templates. Use subcommands add/list/remove."""
        await ctx.send_help(ctx.command)

    @enemy.command(name="add")
    @commands.is_owner()
    async def enemy_add(self, ctx: commands.Context, name: str, image_url: Optional[str] = None):
        """Add an enemy template to enemies.json (owner only)."""
        template = {"name": name, "image_url": image_url}
        self.enemy_templates.append(template)
        await self._save_templates()
        await ctx.send(f"Enemy template **{name}** added.")

    @enemy.command(name="remove")
    @commands.is_owner()
    async def enemy_remove(self, ctx: commands.Context, *, name: str):
        """Remove an enemy template by name (owner only)."""
        before = len(self.enemy_templates)
        self.enemy_templates = [t for t in self.enemy_templates if t.get("name", "").lower() != name.lower()]
        await self._save_templates()
        after = len(self.enemy_templates)
        if before == after:
            await ctx.send(f"No enemy template named **{name}** found.")
        else:
            await ctx.send(f"Enemy template **{name}** removed.")

    @enemy.command(name="list")
    async def enemy_list(self, ctx: commands.Context):
        """List saved enemy templates."""
        if not self.enemy_templates:
            await ctx.send("No enemy templates saved.")
            return
        embed = discord.Embed(title="Enemy Templates", color=self._random_color())
        for t in self.enemy_templates:
            name = t.get("name", "Unnamed")
            url = t.get("image_url") or "None"
            embed.add_field(name=name, value=url, inline=False)
        await ctx.send(embed=embed)

    # -----------------------
    # Add / remove NPC instances (persisted)
    # -----------------------
    @battleroyale.command(name="addnpc")
    @commands.guild_only()
    async def addnpc(self, ctx: commands.Context, signup_message_id: int, enemy_name: str, count: int = 1):
        """
        Add NPC instances from a template to a signup.
        Usage:
          battleroyale addnpc <signup_message_id> <template_name|random> [count]
        Examples:
          battleroyale addnpc 123456789012345678 Goblin 3
          battleroyale addnpc 123456789012345678 random 5
        Requires moderator permissions.
        """
        if not self.is_mod_or_admin(ctx.author):
            await ctx.send("You need to be a moderator or admin to add NPCs.")
            return

        game = self.active_games.get(signup_message_id)
        if not game:
            await ctx.send("No signup found with that message id.")
            return

        # clamp count to avoid abuse
        try:
            count = max(1, min(50, int(count)))
        except Exception:
            count = 1

        added_ids = []

        # helper: pick a random template
        def _pick_random_template():
            if not self.enemy_templates:
                return None
            return random.choice(self.enemy_templates)

        if enemy_name.lower() == "random":
            if not self.enemy_templates:
                await ctx.send("No enemy templates available. Add templates with `battleroyale enemy add` first.")
                return
            for _ in range(count):
                template = _pick_random_template()
                nid = self.next_npc_id
                self.next_npc_id -= 1
                self.npc_instances[nid] = {"name": template["name"], "image_url": template.get("image_url")}
                game["players"].append(nid)
                added_ids.append((nid, template["name"]))
        else:
            # find template by name (case-insensitive)
            template = None
            for t in self.enemy_templates:
                if t.get("name", "").lower() == enemy_name.lower():
                    template = t
                    break
            if not template:
                await ctx.send(f"No enemy template named **{enemy_name}** found. Use `battleroyale enemy list`.")
                return
            for _ in range(count):
                nid = self.next_npc_id
                self.next_npc_id -= 1
                self.npc_instances[nid] = {"name": template["name"], "image_url": template.get("image_url")}
                game["players"].append(nid)
                added_ids.append((nid, template["name"]))

        await self._save_npcs()
        await self._save_games()

        if not added_ids:
            await ctx.send("No NPCs were added.")
            return

        names_summary: Dict[str, int] = {}
        for _, name in added_ids:
            names_summary[name] = names_summary.get(name, 0) + 1
        summary_parts = [f"{v}× {k}" for k, v in names_summary.items()]
        await ctx.send(f"Added {len(added_ids)} NPC(s) to signup {signup_message_id}: " + ", ".join(summary_parts) + ".")

    @battleroyale.command(name="removenpc")
    @commands.guild_only()
    async def removenpc(self, ctx: commands.Context, signup_message_id: int, npc_name: str, count: int = 1):
        """
        Remove NPC instances by name from a signup.
        Usage: battleroyale removenpc <signup_message_id> <npc_name> [count]
        """
        if not self.is_mod_or_admin(ctx.author):
            await ctx.send("You need to be a moderator or admin to remove NPCs.")
            return

        game = self.active_games.get(signup_message_id)
        if not game:
            await ctx.send("No signup found with that message id.")
            return

        removed = 0
        new_players = []
        for pid in game["players"]:
            if removed < count and isinstance(pid, int) and pid < 0:
                inst = self.npc_instances.get(pid)
                if inst and inst.get("name", "").lower() == npc_name.lower():
                    self.npc_instances.pop(pid, None)
                    removed += 1
                    continue
            new_players.append(pid)
        game["players"] = new_players

        await self._save_npcs()
        await self._save_games()
        await ctx.send(f"Removed {removed} NPC(s) named **{npc_name}** from signup {signup_message_id}.")

    # -----------------------
    # Start command with dropdown
    # -----------------------
    @battleroyale.command(name="start")
    @commands.guild_only()
    async def start(self, ctx: commands.Context, signup_message_id: Optional[int] = None):
        """Start the Battle Royale. If no id provided, shows a dropdown to pick a signup."""
        if not self.is_mod_or_admin(ctx.author):
            await ctx.send("You need to be a moderator or admin to start a game.")
            return

        if signup_message_id:
            game = self.active_games.get(signup_message_id)
            if not game:
                await ctx.send("No signup found with that message id.")
                return
            await self.start_game(ctx, game)
            return

        guild_games = [g for g in self.active_games.values() if g["guild_id"] == ctx.guild.id and not g.get("running", False)]
        if not guild_games:
            await ctx.send("No active signup found to start.")
            return

        if len(guild_games) == 1:
            await self.start_game(ctx, guild_games[0])
            return

        options = []
        for g in guild_games:
            msg_id = g["signup_message_id"]
            channel_id = g["channel_id"]
            players = len(g["players"])
            label = f"{players} players in #{channel_id}"
            description = f"Message {msg_id}"
            options.append(discord.SelectOption(label=label[:100], value=str(msg_id), description=description[:100]))

        view = SelectView(self, guild_id=ctx.guild.id, author_id=ctx.author.id)
        if view.children and isinstance(view.children[0], discord.ui.Select):
            view.children[0].options = options

        await ctx.send("Select which signup to start (60s):", view=view, ephemeral=True)
        await view.wait()
        if not view.selected_game_id:
            await ctx.send("No selection made; start cancelled.", ephemeral=True)
            return

        selected_game = self.active_games.get(view.selected_game_id)
        if not selected_game:
            await ctx.send("Selected signup no longer exists.", ephemeral=True)
            return

        await self.start_game(ctx, selected_game)

    async def start_game(self, ctx: commands.Context, game: Dict):
        """Start the provided game dict. Runs the game loop and handles cleanup."""
        if game.get("running"):
            await ctx.send("That game is already running.")
            return

        if len(game.get("players", [])) < 2:
            await ctx.send("Need at least 2 players to start.")
            return

        # mark running and persist
        game["running"] = True
        await self._save_games()

        # remove the persistent Join view so no more joins are possible
        try:
            self.bot.remove_view(view=None, message_id=game["signup_message_id"])
        except Exception:
            pass

        try:
            await self._run_game_loop(ctx, game)
        finally:
            # ensure the game is no longer marked running
            game["running"] = False

            # cleanup NPC instances not referenced by any signup
            used_ids: Set[int] = set()
            for g in self.active_games.values():
                for pid in g.get("players", []):
                    if isinstance(pid, int) and pid < 0:
                        used_ids.add(pid)
            for nid in list(self.npc_instances.keys()):
                if nid not in used_ids:
                    self.npc_instances.pop(nid, None)
            await self._save_npcs()

            # remove this signup so it cannot be reused; require a new signup to start again
            try:
                self.active_games.pop(game["signup_message_id"], None)
            except Exception:
                pass

            await self._save_games()

            # ensure the view is removed (defensive)
            try:
                self.bot.remove_view(view=None, message_id=game["signup_message_id"])
            except Exception:
                pass

    # -----------------------
    # Game loop
    # -----------------------
    async def _run_game_loop(self, ctx: commands.Context, game: Dict):
        players = list(game.get("players", []))
        random.shuffle(players)
        alive: Set[int] = set(players)
        eliminated: List[int] = []

        guild = self.bot.get_guild(game["guild_id"])
        channel = guild.get_channel(game["channel_id"]) if guild else None
        if not channel:
            await ctx.send("Could not find the signup channel.")
            return

        await channel.send(f"Battle Royale starting with {len(players)} players (including NPCs)! Good luck.")

        # Flavor text pools (kept simple and safe)
        event_narrations = [
            "The world trembles as fate picks its targets.",
            "A sudden twist of fortune rattles the arena.",
            "Nature itself seems to take a breath before the chaos.",
            "A strange hush falls over the battleground, then all hell breaks loose.",
            "The skies open and destiny writes its name in thunder.",
        ]
        kill_narrations = [
            "{a} ambushes {b} and emerges victorious.",
            "{a} outmaneuvers {b} in a fierce clash.",
            "{b} falls to {a}'s cunning strike.",
            "{a} surprises {b} and claims the advantage.",
        ]

        round_num = 1

        def _display_name(pid):
            if isinstance(pid, int) and pid < 0:
                inst = self.npc_instances.get(pid, {})
                return inst.get("name", f"NPC{pid}")
            else:
                member = guild.get_member(pid) if guild else None
                return member.display_name if member else f"User{pid}"

        # Simple elimination loop: pair random combatants each round until one remains
        while len(alive) > 1:
            # pick two distinct combatants
            combatants = random.sample(list(alive), 2)
            a, b = combatants[0], combatants[1]

            # decide winner randomly (could be weighted later)
            winner = random.choice([a, b])
            loser = b if winner == a else a

            # update sets
            alive.discard(loser)
            eliminated.append(loser)

            # narration
            narration = random.choice(kill_narrations).format(a=_display_name(winner), b=_display_name(loser))
            flavor = random.choice(event_narrations)

            # Build round header and lines (text-only, will go into embed)
            round_header = f"Round {round_num}: {_display_name(winner)} defeats {_display_name(loser)}"
            narration_lines = [flavor, narration]

            # Determine if this round should use an event background (simple random chance)
            event_triggered = random.random() < 0.12
            event = random.choice(self.events) if (event_triggered and self.events) else None

            # Choose background image according to event/pvp/bg rules
            if event_triggered and event:
                bg_img = await self._load_image_for_entity(event.get("image_url"), None, size=COMPOSITE_SIZE, default_type="event")
            else:
                # alternate between pvp and bg for variety
                is_pvp_round = random.random() < 0.5
                if is_pvp_round:
                    bg_img = await self._load_image_for_entity(None, None, size=COMPOSITE_SIZE, default_type="pvp")
                else:
                    bg_img = await self._load_image_for_entity(None, None, size=COMPOSITE_SIZE, default_type="bg")

            # Compose base image (background only, no text)
            composite = Image.new("RGBA", COMPOSITE_SIZE)
            composite.paste(bg_img, (0, 0))

            # Participants text for embed
            participants_text = ", ".join([_display_name(pid) for pid in players if pid in alive or pid in eliminated])

            # Paste up to 4 portraits (use original players order so dead players can be shown with red X)
            avatar_positions = [(10, 60), (150, 60), (290, 60), (430, 60)]
            avatars_to_show = players[:4]  # show first 4 original players (may include eliminated)
            for pos, pid in zip(avatar_positions, avatars_to_show):
                if isinstance(pid, int) and pid < 0:
                    inst = self.npc_instances.get(pid, {})
                    img = await self._load_image_for_entity(inst.get("image_url"), None, size=(AVATAR_SIZE, AVATAR_SIZE), default_type="npc", npc_instance=inst)
                else:
                    member = guild.get_member(pid) if guild else None
                    avatar_url = None
                    if member:
                        # prefer display avatar
                        try:
                            avatar_url = str(member.display_avatar.url)
                        except Exception:
                            try:
                                avatar_url = str(member.avatar.url)
                            except Exception:
                                avatar_url = None
                    img = await self._load_image_for_entity(avatar_url, None, size=(AVATAR_SIZE, AVATAR_SIZE), default_type="npc")

                # If this player has been eliminated at any point, apply dead overlay
                if pid in eliminated:
                    try:
                        img = self._apply_dead_overlay(img)
                    except Exception:
                        pass

                try:
                    composite.paste(img, pos, img)
                except Exception:
                    composite.paste(img, pos)

            # Save composite to bytes and send as an attachment, with all text inside an embed
            with io.BytesIO() as buf:
                try:
                    composite.save(buf, format="PNG")
                    buf.seek(0)
                    file = discord.File(buf, filename=f"battleroyale_round_{round_num}.png")

                    # Build embed: all text goes into the embed (title, description, fields)
                    embed = discord.Embed(title=round_header, description="\n".join(narration_lines), color=self._random_color())
                    embed.add_field(name="Participants", value=participants_text or "None", inline=False)
                    embed.set_footer(text=f"Round {round_num}")

                    await channel.send(embed=embed, file=file)
                except Exception:
                    # Fallback: send embed without image
                    embed = discord.Embed(title=round_header, description="\n".join(narration_lines), color=self._random_color())
                    embed.add_field(name="Participants", value=participants_text or "None", inline=False)
                    embed.set_footer(text=f"Round {round_num}")
                    await channel.send(embed=embed)

            round_num += 1
            # small delay to avoid spamming too fast
            await asyncio.sleep(1.0)

        # Game finished, determine winner
        remaining = list(alive)
        if not remaining:
            await channel.send("No winner could be determined.")
            return

        winner_pid = remaining[0]

        # Build winner embed with portrait and victory background
        # Load winner avatar
        if isinstance(winner_pid, int) and winner_pid < 0:
            inst = self.npc_instances.get(winner_pid, {})
            winner_name = inst.get("name", f"NPC{winner_pid}")
            avatar_img = await self._load_image_for_entity(inst.get("image_url"), None, size=(AVATAR_SIZE * 2, AVATAR_SIZE * 2), default_type="npc", npc_instance=inst)
        else:
            member = guild.get_member(winner_pid) if guild else None
            winner_name = member.display_name if member else f"User{winner_pid}"
            avatar_url = None
            if member:
                try:
                    avatar_url = str(member.display_avatar.url)
                except Exception:
                    try:
                        avatar_url = str(member.avatar.url)
                    except Exception:
                        avatar_url = None
            avatar_img = await self._load_image_for_entity(avatar_url, None, size=(AVATAR_SIZE * 2, AVATAR_SIZE * 2), default_type="npc")

        # Load victory background: choose from DEFAULT_VICTORY_URLS if available, otherwise fall back to bg logic
        victory_bg_url = None
        if DEFAULT_VICTORY_URLS:
            victory_bg_url = random.choice(DEFAULT_VICTORY_URLS)
        victory_bg = await self._load_image_for_entity(victory_bg_url, None, size=COMPOSITE_SIZE, default_type="bg")

        # Compose winner image: background + centered portrait (no text)
        winner_composite = Image.new("RGBA", COMPOSITE_SIZE)
        winner_composite.paste(victory_bg, (0, 0))

        # center avatar
        aw, ah = avatar_img.size
        cx = (COMPOSITE_SIZE[0] - aw) // 2
        cy = (COMPOSITE_SIZE[1] - ah) // 2
        try:
            winner_composite.paste(avatar_img, (cx, cy), avatar_img)
        except Exception:
            winner_composite.paste(avatar_img, (cx, cy))

        # Save winner composite and send embed
        with io.BytesIO() as buf:
            try:
                winner_composite.save(buf, format="PNG")
                buf.seek(0)
                file = discord.File(buf, filename=f"battleroyale_winner_{winner_pid}.png")

                winner_embed = discord.Embed(
                    title=f"{winner_name} is the Champion!",
                    description=f"Congratulations to **{winner_name}** — the last one standing!",
                    color=self._random_color(),
                )
                winner_embed.set_image(url=f"attachment://battleroyale_winner_{winner_pid}.png")
                winner_embed.set_footer(text="Victory!")

                await channel.send(embed=winner_embed, file=file)
            except Exception:
                # fallback: send embed without image
                winner_embed = discord.Embed(
                    title=f"{winner_name} is the Champion!",
                    description=f"Congratulations to **{winner_name}** — the last one standing!",
                    color=self._random_color(),
                )
                winner_embed.set_footer(text="Victory!")
                await channel.send(embed=winner_embed)

        # final cleanup handled by caller (start_game finally block)
