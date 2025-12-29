# battleroyale.py
import asyncio
import io
import json
import os
import random
from typing import Dict, List, Optional, Set

import aiohttp
import discord
from redbot.core import commands, bank, checks, Config
from PIL import Image, ImageDraw, ImageOps

# File paths (stored next to this file)
BASE_DIR = os.path.dirname(__file__)
EVENTS_FILE = os.path.join(BASE_DIR, "events.json")
ENEMIES_FILE = os.path.join(BASE_DIR, "enemies.json")
GAMES_FILE = os.path.join(BASE_DIR, "games.json")
NPCS_FILE = os.path.join(BASE_DIR, "npcs.json")

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
    async def join_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return

        game = self.cog.active_games.get(self.signup_message_id)
        if not game:
            await interaction.response.send_message("This signup is no longer active.", ephemeral=True)
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

        # file locks for safe concurrent writes
        self._games_lock = asyncio.Lock()
        self._npcs_lock = asyncio.Lock()
        self._events_lock = asyncio.Lock()
        self._templates_lock = asyncio.Lock()

        # restore persistent views after bot ready
        bot.loop.create_task(self._restore_views())

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
    # Commands
    # -----------------------
    @commands.group()
    @commands.guild_only()
    async def battleroyale(self, ctx: commands.Context):
        """Battle Royale commands group."""
        if ctx.invoked_subcommand is None:
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

        game["running"] = True
        await self._save_games()
        try:
            await self._run_game_loop(ctx, game)
        finally:
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
            await self._save_games()
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

        round_num = 0
        while len(alive) > 1:
            round_num += 1
            await asyncio.sleep(2)

            event = random.choices(self.events, weights=[e.get("chance", 10) for e in self.events], k=1)[0] if self.events else None

            embed_color = self._random_color()

            participants = random.sample(list(alive), k=min(len(alive), random.randint(1, min(4, len(alive)))))

            casualties: List[int] = []

            severity_pct = float(event.get("severity", 20.0)) if event else 20.0

            for pid in participants:
                roll = random.uniform(0, 100)
                if roll < severity_pct:
                    casualties.append(pid)

            # PvP duels (NPCs and players both eligible)
            pvp_duels = max(0, min(3, len(alive) // 2))
            for _ in range(pvp_duels):
                if len(alive) < 2:
                    break
                attacker, defender = random.sample(list(alive), 2)
                base_pvp_chance = 30.0
                event_pvp_mod = float(event.get("pvp_modifier", 0.0)) if event else 0.0
                kill_chance = max(0.0, min(100.0, base_pvp_chance + event_pvp_mod))
                roll = random.uniform(0, 100)
                if roll < kill_chance:
                    if defender not in casualties:
                        casualties.append(defender)

            for c in casualties:
                if c in alive:
                    alive.remove(c)
                    eliminated.append(c)

            embed = discord.Embed(title=f"Round {round_num}", color=embed_color)
            if event:
                embed.title = f"Round {round_num} — {event.get('name', 'Event')}"
                embed.description = event.get("description", "An event occurred.")
            else:
                embed.description = "A random event occurred."

            composite = await self.compose_event_image(participants, eliminated, event_image_url=event.get("image_url") if event else None)
            file = discord.File(composite, filename="event.png")
            embed.set_image(url="attachment://event.png")

            # participants names
            names = []
            for pid in participants:
                if isinstance(pid, int) and pid < 0:
                    inst = self.npc_instances.get(pid)
                    names.append(inst["name"] if inst else f"NPC {pid}")
                else:
                    member = guild.get_member(pid) if guild else None
                    names.append(member.display_name if member else f"User {pid}")
            embed.add_field(name="Participants", value=", ".join(names)[:1024], inline=False)

            if casualties:
                c_names = []
                for pid in casualties:
                    if isinstance(pid, int) and pid < 0:
                        inst = self.npc_instances.get(pid)
                        c_names.append(inst["name"] if inst else f"NPC {pid}")
                    else:
                        member = guild.get_member(pid) if guild else None
                        c_names.append(member.display_name if member else f"User {pid}")
                embed.add_field(name="Casualties", value=", ".join(c_names)[:1024], inline=False)
            else:
                embed.add_field(name="Casualties", value="None", inline=False)

            await channel.send(file=file, embed=embed)
            await asyncio.sleep(1)

            # persist progress (players list updated to current alive + eliminated)
            game["players"] = list(alive) + eliminated
            await self._save_games()

        # announce winner
        winner_id = next(iter(alive)) if alive else None
        if winner_id:
            if isinstance(winner_id, int) and winner_id < 0:
                winner_name = self.npc_instances.get(winner_id, {}).get("name", f"NPC {winner_id}")
                await channel.send(f"🏆 **{winner_name}** (NPC) is the winner!")
            else:
                winner = guild.get_member(winner_id) if guild else None
                await channel.send(f"🏆 **{winner.display_name if winner else 'Unknown'}** is the winner!")
        else:
            await channel.send("No winners this time.")

    # -----------------------
    # Status and event management
    # -----------------------
    @battleroyale.command(name="status")
    async def status(self, ctx: commands.Context, signup_message_id: Optional[int] = None):
        """Show status of a signup/game."""
        if signup_message_id:
            game = self.active_games.get(signup_message_id)
        else:
            game = None
            for g in self.active_games.values():
                if g["guild_id"] == ctx.guild.id:
                    game = g
                    break
        if not game:
            await ctx.send("No active signup found.")
            return
        players = []
        for pid in game.get("players", []):
            if isinstance(pid, int) and pid < 0:
                inst = self.npc_instances.get(pid)
                players.append(f"{inst['name']} (NPC)" if inst else f"NPC {pid}")
            else:
                member = ctx.guild.get_member(pid)
                players.append(member.display_name if member else str(pid))
        embed = discord.Embed(title="Battle Royale Status", color=self._random_color())
        embed.add_field(name="Signup Message ID", value=str(game["signup_message_id"]), inline=False)
        embed.add_field(name="Channel", value=f"<#{game['channel_id']}>", inline=False)
        embed.add_field(name="Players", value=", ".join(players) or "None", inline=False)
        embed.add_field(name="Running", value=str(game.get("running", False)), inline=False)
        await ctx.send(embed=embed)

    @battleroyale.command(name="addevent")
    @commands.is_owner()
    async def addevent(self, ctx: commands.Context, name: str, severity_pct: float, *, description_and_url: str):
        """
        Add an event to events.json.
        Usage: battleroyale addevent "Name" 25 description | image_url(optional)
        severity_pct is 0-100 (percent chance for participants to die in the event)
        """
        parts = description_and_url.split("|")
        description = parts[0].strip()
        image_url = parts[1].strip() if len(parts) > 1 else None
        new_event = {
            "name": name,
            "description": description,
            "image_url": image_url,
            "severity": float(max(0.0, min(100.0, severity_pct))),
            "chance": 10,
            "pvp_modifier": 0.0,
        }
        self.events.append(new_event)
        await self._save_events()
        await ctx.send(f"Event '{name}' added with severity {new_event['severity']}%.")

    # -----------------------
    # Image helpers
    # -----------------------
    async def fetch_image_from_url(self, url: str, size: int) -> Optional[Image.Image]:
        try:
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                img = Image.open(io.BytesIO(data)).convert("RGBA")
                img = img.resize((size, size))
                return img
        except Exception:
            return None

    async def fetch_avatar_image(self, pid: int, guild: Optional[discord.Guild]) -> Optional[Image.Image]:
        """
        pid may be:
        - positive int: Discord user id -> fetch avatar
        - negative int: NPC instance id -> fetch image_url from npc_instances
        """
        if isinstance(pid, int) and pid < 0:
            inst = self.npc_instances.get(pid)
            if not inst:
                return None
            url = inst.get("image_url")
            if not url:
                return None
            return await self.fetch_image_from_url(url, AVATAR_SIZE)

        member = None
        if guild:
            member = guild.get_member(pid)
        if not member:
            for g in self.bot.guilds:
                member = g.get_member(pid)
                if member:
                    break
        if not member:
            return None
        url = member.display_avatar.replace(size=AVATAR_SIZE).url
        try:
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                img = Image.open(io.BytesIO(data)).convert("RGBA")
                img = img.resize((AVATAR_SIZE, AVATAR_SIZE))
                return img
        except Exception:
            return None

    async def compose_event_image(self, participant_ids: List[int], eliminated_ids: List[int], event_image_url: Optional[str] = None) -> io.BytesIO:
        """Compose a composite image for the event round. Handles NPC images via image_url."""
        base = Image.new("RGBA", COMPOSITE_SIZE, (30, 30, 30, 255))

        if event_image_url:
            try:
                async with self.session.get(event_image_url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        bg = Image.open(io.BytesIO(data)).convert("RGBA")
                        bg = bg.resize(COMPOSITE_SIZE)
                        base.paste(bg, (0, 0))
                    else:
                        event_image_url = None
            except Exception:
                event_image_url = None

        if not event_image_url:
            rr, rg, rb = random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)
            ra = random.randint(200, 255)
            random_bg = Image.new("RGBA", COMPOSITE_SIZE, (rr, rg, rb, ra))
            base = Image.alpha_composite(random_bg, base)

        spacing = 12
        total = len(participant_ids)
        if total == 0:
            bio = io.BytesIO()
            base.save(bio, "PNG")
            bio.seek(0)
            return bio

        max_width = COMPOSITE_SIZE[0] - (spacing * (total + 1))
        avatar_w = min(AVATAR_SIZE, max(48, max_width // total))
        x = spacing
        y = (COMPOSITE_SIZE[1] - avatar_w) // 2

        # attempt to get guild context for avatar fetches
        guild = None
        for g in self.bot.guilds:
            for pid in participant_ids:
                if isinstance(pid, int) and pid > 0 and g.get_member(pid):
                    guild = g
                    break
            if guild:
                break

        for pid in participant_ids:
            avatar = None
            if isinstance(pid, int) and pid < 0:
                inst = self.npc_instances.get(pid)
                if inst and inst.get("image_url"):
                    avatar = await self.fetch_image_from_url(inst["image_url"], avatar_w)
            else:
                avatar = await self.fetch_avatar_image(pid, guild)

            if avatar:
                avatar = avatar.resize((avatar_w, avatar_w))
            else:
                avatar = Image.new("RGBA", (avatar_w, avatar_w), (100, 100, 100, 255))

            if pid in eliminated_ids:
                avatar = ImageOps.grayscale(avatar).convert("RGBA")
                cr, cg, cb = random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)
                cross = Image.new("RGBA", avatar.size, (0, 0, 0, 0))
                cd = ImageDraw.Draw(cross)
                w, h = avatar.size
                thickness = max(4, w // 10)
                cd.line((0, 0, w, h), fill=(cr, cg, cb, 220), width=thickness)
                cd.line((0, h, w, 0), fill=(cr, cg, cb, 220), width=thickness)
                avatar = Image.alpha_composite(avatar, cross)

            base.paste(avatar, (x, y), avatar)
            x += avatar_w + spacing

        bio = io.BytesIO()
        base.save(bio, "PNG")
        bio.seek(0)
        return bio


# Expose the cog for Red to load. Red's async setup should call this class from __init__.py.
def setup(bot):
    # Backwards compatibility: synchronous setup for older loaders
    bot.add_cog(BattleRoyale(bot))
