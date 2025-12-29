# battleroyale.py
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
    # "https://files.catbox.moe/zgo9st.png",
    # "https://files.catbox.moe/tlmusq.png",
]
DEFAULT_EVENT_URLS = [
    # "https://files.catbox.moe/9p8hc6.png",
    # "https://files.catbox.moe/2vqj0b.png",
]
DEFAULT_BG_URLS = [
    # "https://files.catbox.moe/5vn581.png",
    # "https://files.catbox.moe/xes0gm.png",
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
            async with self.session.get(url, timeout=timeout) as resp:
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
    ) -> Image.Image:
        """
        Try in order:
          1. image_url (entity-specific)
          2. random default URL from default_url_list
          3. generated placeholder
        Returns a PIL Image resized to `size`.
        """
        img_bytes = None

        # 1) try entity URL
        if image_url:
            img_bytes = await self._fetch_image_bytes(image_url)

        # 2) try a random default URL from the list
        if not img_bytes and default_url_list:
            candidates = default_url_list[:]
            random.shuffle(candidates)
            for candidate in candidates:
                if not candidate:
                    continue
                img_bytes = await self._fetch_image_bytes(candidate)
                if img_bytes:
                    break

        img = None
        if img_bytes:
            try:
                img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
            except Exception:
                img = None

        # 3) fallback placeholder
        if img is None:
            img = self._open_fallback_image(size=size)

        # fit to requested size
        try:
            img = ImageOps.fit(img, size, Image.LANCZOS)
        except Exception:
            img = img.resize(size)

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

        # Flavor text pools
        event_narrations = [
            "The world trembles as fate picks its targets.",
            "A sudden twist of fortune rattles the arena.",
            "Nature itself seems to take a breath before the chaos.",
            "A strange hush falls over the battleground, then all hell breaks loose.",
            "The skies open and destiny writes its name in fire."
        ]
        pvp_attack_texts = [
            "{attacker} lunges at {defender} with a desperate cry.",
            "{attacker} charges, blades flashing toward {defender}.",
            "{attacker} feints left and strikes at {defender}.",
            "{attacker} ambushes {defender} from the shadows.",
            "{attacker} and {defender} collide in a furious exchange."
        ]
        pvp_survive_texts = [
            "{defender} narrowly escapes, breathing hard and shaken.",
            "{defender} parries and slips away, wounds shallow but spirit unbroken.",
            "{defender} ducks under the blow and staggers to safety.",
            "{defender} finds cover and survives the onslaught.",
            "{defender} grits their teeth and manages to survive the encounter."
        ]
        pvp_kill_texts = [
            "{defender} falls, life snuffed out in a heartbeat.",
            "{defender} is struck down, collapsing to the ground.",
            "{defender} didn't stand a chance and is gone.",
            "{defender} is cut down amid the chaos.",
            "{defender} breathes their last as the crowd gasps."
        ]
        round_flavor_victory = [
            "A hush, then cheers — a champion emerges.",
            "Silence gives way to the roar of victory.",
            "One stands tall while the rest are dust and memory.",
            "The arena remembers this name for a long time.",
            "A final gasp, a final bow — the winner claims the day."
        ]
        # Probability split: 35% event, 65% PvP
        EVENT_PROB = 0.35
        PVP_DEATH_CHANCE = 0.70  # 70% chance defender dies in PvP; 30% survive

        round_num = 0
        while len(alive) > 1:
            round_num += 1
            await asyncio.sleep(2)

            # Decide round type: event or PvP
            is_event_round = False
            chosen_event = None
            if self.events and random.random() < EVENT_PROB:
                is_event_round = True
                chosen_event = random.choices(self.events, weights=[e.get("chance", 10) for e in self.events], k=1)[0]

            embed_color = self._random_color()

            # participants selection
            participants = random.sample(list(alive), k=min(len(alive), random.randint(1, min(4, len(alive)))))

            casualties: List[int] = []
            narration_lines: List[str] = []

            if is_event_round and chosen_event:
                # Event round: use event severity for death chance per participant
                severity_pct = float(chosen_event.get("severity", 20.0))
                narration_lines.append(random.choice(event_narrations))
                narration_lines.append(chosen_event.get("description", "An event unfolds."))

                for pid in participants:
                    roll = random.uniform(0, 100)
                    if roll < severity_pct:
                        casualties.append(pid)
                    else:
                        # survived the event; add a small flavor line
                        if isinstance(pid, int) and pid < 0:
                            name = self.npc_instances.get(pid, {}).get("name", f"NPC {pid}")
                        else:
                            member = guild.get_member(pid) if guild else None
                            name = member.display_name if member else f"User {pid}"
                        narration_lines.append(f"{name} weathers the event and survives.")
            else:
                # PvP round: perform a number of duels
                narration_lines.append("Player skirmishes erupt across the field.")
                # Determine number of duels: up to min(3, floor(len(alive)/2))
                max_duels = max(1, min(3, len(alive) // 2))
                duels = random.randint(1, max_duels)
                used_in_duel: Set[int] = set()
                for _ in range(duels):
                    # pick attacker and defender not already used in this round if possible
                    available = [p for p in alive if p not in used_in_duel]
                    if len(available) < 2:
                        available = [p for p in alive]
                    if len(available) < 2:
                        break
                    attacker = random.choice(available)
                    used_in_duel.add(attacker)
                    # pick defender
                    possible_defenders = [p for p in alive if p != attacker and p not in used_in_duel]
                    if not possible_defenders:
                        possible_defenders = [p for p in alive if p != attacker]
                    if not possible_defenders:
                        continue
                    defender = random.choice(possible_defenders)
                    used_in_duel.add(defender)

                    # resolve duel
                    attacker_name = (
                        self.npc_instances.get(attacker, {}).get("name")
                        if isinstance(attacker, int) and attacker < 0
                        else (guild.get_member(attacker).display_name if guild and guild.get_member(attacker) else f"User {attacker}")
                    )
                    defender_name = (
                        self.npc_instances.get(defender, {}).get("name")
                        if isinstance(defender, int) and defender < 0
                        else (guild.get_member(defender).display_name if guild and guild.get_member(defender) else f"User {defender}")
                    )

                    narration_lines.append(random.choice(pvp_attack_texts).format(attacker=attacker_name, defender=defender_name))
                    if random.random() < PVP_DEATH_CHANCE:
                        casualties.append(defender)
                        narration_lines.append(random.choice(pvp_kill_texts).format(defender=defender_name))
                    else:
                        narration_lines.append(random.choice(pvp_survive_texts).format(defender=defender_name))

            # apply casualties
            for c in casualties:
                if c in alive:
                    alive.remove(c)
                    eliminated.append(c)

            # compose and send an image summarizing the round (if possible)
            try:
                composite = await self.compose_event_image(game, participants, casualties, narration_lines)
                if composite:
                    # composite is a BytesIO
                    composite.seek(0)
                    file = discord.File(fp=composite, filename="round.png")
                    await channel.send(file=file)
                else:
                    # fallback to text
                    await channel.send("\n".join(narration_lines[:10]))
            except Exception:
                # if image composition fails, send text
                await channel.send("\n".join(narration_lines[:10]))

        # announce winner
        winner = next(iter(alive)) if alive else None
        if winner is not None:
            if isinstance(winner, int) and winner < 0:
                winner_name = self.npc_instances.get(winner, {}).get("name", f"NPC {winner}")
            else:
                member = guild.get_member(winner) if guild else None
                winner_name = member.display_name if member else f"User {winner}"
            await channel.send(random.choice(round_flavor_victory) + f" Winner: **{winner_name}**.")
        else:
            await channel.send("No one survived the Battle Royale.")

    # -----------------------
    # Image composition for rounds/events
    # -----------------------
    async def compose_event_image(self, game: Dict, participants: List[int], casualties: List[int], narration_lines: List[str]) -> Optional[io.BytesIO]:
        """
        Create a composite image summarizing the round.
        - game: the game dict (for defaults)
        - participants: list of participant ids in this round
        - casualties: list of ids who died this round
        - narration_lines: flavor text lines to include
        Returns BytesIO with PNG data or None on failure.
        """
        try:
            # create base
            bg_bytes = None
            # try configured default backgrounds from config, then DEFAULT_BG_URLS
            try:
                cfg_bg = await self.config.default_bg_urls()
                if cfg_bg:
                    bg_candidates = cfg_bg
                else:
                    bg_candidates = DEFAULT_BG_URLS
            except Exception:
                bg_candidates = DEFAULT_BG_URLS

            bg_img = None
            # try to fetch a background
            if bg_candidates:
                for url in bg_candidates:
                    bg_bytes = await self._fetch_image_bytes(url)
                    if bg_bytes:
                        try:
                            bg_img = Image.open(io.BytesIO(bg_bytes)).convert("RGBA")
                            break
                        except Exception:
                            bg_img = None
            if bg_img is None:
                bg_img = Image.new("RGBA", COMPOSITE_SIZE, (30, 30, 30, 255))

            # prepare canvas
            canvas = Image.new("RGBA", COMPOSITE_SIZE)
            # fit background to canvas
            try:
                bg_fit = ImageOps.fit(bg_img, COMPOSITE_SIZE, Image.LANCZOS)
            except Exception:
                bg_fit = bg_img.resize(COMPOSITE_SIZE)
            canvas.paste(bg_fit, (0, 0))

            draw = ImageDraw.Draw(canvas)

            # load a font
            try:
                font_path = os.path.join(BASE_DIR, "fonts", "DejaVuSans.ttf")
                if os.path.exists(font_path):
                    font = ImageFont.truetype(font_path, 16)
                    name_font = ImageFont.truetype(font_path, 18)
                else:
                    font = ImageFont.load_default()
                    name_font = ImageFont.load_default()
            except Exception:
                font = ImageFont.load_default()
                name_font = ImageFont.load_default()

            # layout avatars horizontally
            margin = 10
            spacing = 8
            max_avatars = min(5, len(participants))
            avatar_total_width = max_avatars * AVATAR_SIZE + (max_avatars - 1) * spacing
            start_x = (COMPOSITE_SIZE[0] - avatar_total_width) // 2
            y = 20

            # draw avatars and names
            for idx, pid in enumerate(participants[:max_avatars]):
                x = start_x + idx * (AVATAR_SIZE + spacing)
                if isinstance(pid, int) and pid < 0:
                    inst = self.npc_instances.get(pid, {})
                    name = inst.get("name", f"NPC {pid}")
                    image_url = inst.get("image_url")
                    avatar = await self._load_image_for_entity(image_url, DEFAULT_NPC_URLS, size=(AVATAR_SIZE, AVATAR_SIZE))
                else:
                    member = None
                    try:
                        guild = self.bot.get_guild(game["guild_id"])
                        member = guild.get_member(pid) if guild else None
                    except Exception:
                        member = None
                    name = member.display_name if member else f"User {pid}"
                    # fetch avatar bytes from Discord CDN
                    image_url = None
                    try:
                        if member and member.avatar:
                            image_url = member.avatar.url
                        elif member and member.display_avatar:
                            image_url = member.display_avatar.url
                    except Exception:
                        image_url = None
                    avatar = await self._load_image_for_entity(image_url, [], size=(AVATAR_SIZE, AVATAR_SIZE))

                # draw circular mask
                mask = Image.new("L", (AVATAR_SIZE, AVATAR_SIZE), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse((0, 0, AVATAR_SIZE, AVATAR_SIZE), fill=255)
                canvas.paste(avatar, (x, y), mask)

                # draw name below avatar
                name_text = name
                text_w, text_h = self._get_text_size(draw, name_text, name_font)
                text_x = x + (AVATAR_SIZE - text_w) // 2
                text_y = y + AVATAR_SIZE + 6
                # shadow
                draw.text((text_x + 1, text_y + 1), name_text, font=name_font, fill=(0, 0, 0, 200))
                draw.text((text_x, text_y), name_text, font=name_font, fill=(255, 255, 255, 230))

                # mark casualty overlay if died
                if pid in casualties:
                    overlay = Image.new("RGBA", (AVATAR_SIZE, AVATAR_SIZE), (0, 0, 0, 140))
                    ov_draw = ImageDraw.Draw(overlay)
                    # draw an X
                    ov_draw.line((10, 10, AVATAR_SIZE - 10, AVATAR_SIZE - 10), fill=(255, 0, 0, 200), width=6)
                    ov_draw.line((AVATAR_SIZE - 10, 10, 10, AVATAR_SIZE - 10), fill=(255, 0, 0, 200), width=6)
                    canvas.paste(overlay, (x, y), overlay)

            # draw narration text on the right side or bottom
            narration_area_x = 12
            narration_area_y = COMPOSITE_SIZE[1] - 90
            narration_area_w = COMPOSITE_SIZE[0] - 24
            narration_area_h = 80

            # prepare a short block of narration (limit lines)
            lines = []
            for line in narration_lines:
                # naive wrap: split if too long
                if len(line) > 80:
                    # split into chunks of ~80 chars
                    for i in range(0, len(line), 80):
                        lines.append(line[i : i + 80])
                else:
                    lines.append(line)
                if len(lines) >= 4:
                    break

            # draw a semi-transparent box
            box = Image.new("RGBA", (narration_area_w, narration_area_h), (0, 0, 0, 120))
            canvas.paste(box, (narration_area_x, narration_area_y), box)
            text_x = narration_area_x + 8
            text_y = narration_area_y + 8
            for ln in lines:
                draw.text((text_x + 1, text_y + 1), ln, font=font, fill=(0, 0, 0, 200))
                draw.text((text_x, text_y), ln, font=font, fill=(255, 255, 255, 230))
                tw, th = self._get_text_size(draw, ln, font)
                text_y += th + 4

            # final touches: round corners
            try:
                radius = 12
                rounded = Image.new("RGBA", COMPOSITE_SIZE, (0, 0, 0, 0))
                mask = Image.new("L", COMPOSITE_SIZE, 0)
                mdraw = ImageDraw.Draw(mask)
                mdraw.rounded_rectangle((0, 0, COMPOSITE_SIZE[0], COMPOSITE_SIZE[1]), radius=radius, fill=255)
                rounded.paste(canvas, (0, 0), mask)
                final = rounded
            except Exception:
                final = canvas

            # save to BytesIO
            bio = io.BytesIO()
            final.save(bio, format="PNG")
            bio.seek(0)
            return bio
        except Exception:
            return None
