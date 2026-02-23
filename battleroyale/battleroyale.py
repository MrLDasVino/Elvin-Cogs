import asyncio
import io
import json
import os
import random
from typing import Dict, List, Optional, Set, Tuple

import aiohttp
import discord
from discord import File
from redbot.core import commands, Config
from PIL import Image, ImageDraw, ImageOps, ImageFont

# File paths (stored next to this file)
BASE_DIR = os.path.dirname(__file__)
EVENTS_FILE = os.path.join(BASE_DIR, "events.json")
ENEMIES_FILE = os.path.join(BASE_DIR, "enemies.json")
GAMES_FILE = os.path.join(BASE_DIR, "games.json")
NPCS_FILE = os.path.join(BASE_DIR, "npcs.json")
LEADERBOARD_FILE = os.path.join(BASE_DIR, "leaderboard.json")

# Default remote fallback URLs (set to real URLs or leave empty)
DEFAULT_NPC_URLS = [
    "https://files.catbox.moe/zgo9st.png",
    "https://files.catbox.moe/tlmusq.png",
    "https://files.catbox.moe/xx1qb7.png",
    "https://files.catbox.moe/28ydov.png",
    "https://files.catbox.moe/gjknbf.png",
    "https://files.catbox.moe/p5nn9y.png",
    "https://files.catbox.moe/h7y3ec.png",
    "https://files.catbox.moe/l57yxd.png",
]
DEFAULT_EVENT_URLS = [
    "https://files.catbox.moe/9p8hc6.png",
    "https://files.catbox.moe/2vqj0b.png",
    "https://files.catbox.moe/fpttbp.png",
    "https://files.catbox.moe/5a5ua5.png",
    "https://files.catbox.moe/b8u2sf.png",
    "https://files.catbox.moe/o5n7wp.png",
    "https://files.catbox.moe/u7e2j1.png",
    "https://files.catbox.moe/54mima.png",
    "https://files.catbox.moe/9llrtm.png",
    "https://files.catbox.moe/w5a8pl.png",
]
DEFAULT_BG_URLS = [
    "https://files.catbox.moe/5vn581.png",
    "https://files.catbox.moe/xes0gm.png",
    "https://files.catbox.moe/jv6u4x.png",
    "https://files.catbox.moe/6gpte7.png",
    "https://files.catbox.moe/i86jh6.png",
    "https://files.catbox.moe/e986ub.png",
    "https://files.catbox.moe/ifgqui.png",
]
DEFAULT_VICTORY_URLS = [
    "https://files.catbox.moe/wyjekh.png",
    "https://files.catbox.moe/dbc0p2.png",
    "https://files.catbox.moe/qgvayb.png",
    "https://files.catbox.moe/ipqv9c.png",
    "https://files.catbox.moe/mmg5sb.png",
]
DEFAULT_SIGNUP_THUMB_URLS = [
    "https://files.catbox.moe/gxmxyl.png",
    "https://files.catbox.moe/x4uuz9.png",
]
DEFAULT_NO_SURVIVORS_URLS = [
    "https://files.catbox.moe/u1rmqc.png",
    "https://files.catbox.moe/gvkpsu.png",
    "https://files.catbox.moe/eqhrjv.png",
    "https://files.catbox.moe/6xt2zm.png",
]
DEFAULT_LEADERBOARD_THUMB_URL = [
    "https://files.catbox.moe/no66t1.png",
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

        # Refresh the signup embed to show updated counts
        try:
            await self.cog._refresh_signup_embed(self.signup_message_id)
        except Exception:
            pass

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
        raw_leaderboard = load_json_file(LEADERBOARD_FILE, {})
        self.leaderboard: Dict[str, int] = {k: int(v) for k, v in raw_leaderboard.items()}
        self._leaderboard_lock = asyncio.Lock()

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
            default_signup_thumb_urls=[],  
            default_no_survivors_urls=[],  
            leaderboard_thumbnail_url=[],
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
            
    async def _save_leaderboard(self):
        async with self._leaderboard_lock:
            save_json_file(LEADERBOARD_FILE, {k: int(v) for k, v in self.leaderboard.items()})

    def _id_to_key(self, pid: int) -> str:
        """
        Convert participant id to stable storage key.
        Positive ints -> 'user:<id>'; negative ints -> 'npc:<id>'.
        """
        return f"npc:{pid}" if isinstance(pid, int) and pid < 0 else f"user:{pid}"

    async def _record_winner(self, winner_id: int):
        """
        Increment persistent win count for winner_id.
        Only record wins for positive user IDs; ignore NPC victories.
        """
        # Ignore NPC wins (negative ids)
        try:
            if isinstance(winner_id, int) and winner_id < 0:
                return
    
            key = self._id_to_key(winner_id)
            # Ensure we only create user keys (defensive)
            if not key.startswith("user:"):
                return
    
            self.leaderboard[key] = self.leaderboard.get(key, 0) + 1
            await self._save_leaderboard()
        except Exception:
            # keep behavior robust on unexpected input
            return
          
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
    # New helpers for game logic and image composition
    # -----------------------
    def _choose_action_type(self) -> str:
        """
        Return 'pvp' or 'event' according to configured probabilities:
          - PvP: 70%
          - Event: 30%
        """
        return "pvp" if random.random() < 0.7 else "event"

    def _pick_event(self) -> Optional[Dict]:
        """Pick an event using the 'chance' weight from self.events; fallback to uniform."""
        if not self.events:
            return None
        weights = []
        for e in self.events:
            try:
                w = float(e.get("chance", 1))
            except Exception:
                w = 1.0
            weights.append(max(0.0, w))
        total = sum(weights)
        if total <= 0:
            return random.choice(self.events)
        r = random.random() * total
        upto = 0.0
        for e, w in zip(self.events, weights):
            upto += w
            if r <= upto:
                return e
        return self.events[-1]

    def _select_combatants(self, game: Dict) -> Tuple[str, List[int], Optional[Dict]]:
        """
        Returns (action_type, participants_list, event_dict_or_None)
        - For 'pvp': returns two distinct participant ids (attacker, defender)
        - For 'event': returns 1..N participant ids (random subset), and the chosen event dict
        """
        players = [p for p in game.get("players", [])]
        if not players:
            return ("none", [], None)

        action = self._choose_action_type()

        # If not enough players for PvP, force event
        if action == "pvp" and len(players) < 2:
            action = "event"

        if action == "pvp":
            a, b = random.sample(players, 2)
            return ("pvp", [a, b], None)

        # event path: pick an event and choose participants
        event = self._pick_event()
        max_affect = min(4, len(players))

        # Determine number of participants:
        # - If event specifies a positive 'participants' value, use it (clamped).
        # - Otherwise choose a random number between 1 and max_affect so events can affect multiple players.
        if event:
            try:
                specified = int(event.get("participants", 0))
            except Exception:
                specified = 0

            if specified > 0:
                num = max(1, min(max_affect, specified))
            else:
                # no explicit participants field or non-positive: pick random 1..max_affect
                num = random.randint(1, max_affect)
        else:
            # no event available: default to affecting a single participant
            num = 1

        # ensure we don't request more participants than exist
        num = max(1, min(num, len(players)))
        participants = random.sample(players, num)
        return ("event", participants, event)

    def _format_participant_name(self, pid: int, mention: bool = False) -> str:
        """
        Return a display name for a participant id.
        Positive ints are Discord user IDs; negative ints are NPC instance ids.
        """
        try:
            if isinstance(pid, int) and pid < 0:
                inst = self.npc_instances.get(pid)
                if inst:
                    return f"**{inst.get('name','NPC')}**"
                return f"**NPC({pid})**"
            else:
                user = self.bot.get_user(pid)
                if user:
                    return f"**{user.display_name}**" if not mention else user.mention
                return f"**User({pid})**"
        except Exception:
            return f"**{pid}**"

    def _resolve_attack_single(self, attacker_id: Optional[int], target_id: int, attacker_label: Optional[str] = None) -> Tuple[bool, str]:
        """
        Resolve an attack from attacker_id (or attacker_label) to target_id.
        Returns (target_survived: bool, result_text: str).
    
        Survival probabilities:
          - 30% survive
          - 70% die
    
        When attacker_label is provided (used for Events), the phrasing will use
        "the <Event Name>" and verbs tailored for event-style messages:
          - "<Target> was killed by the <Event Name>."
          - "<Target> survived the <Event Name>."
        """
        survived = random.random() < 0.30  # 30% survive
    
        # Determine attacker display name
        if attacker_label:
            # For events we want "the <Event Name>" phrasing
            attacker_name = f"the {attacker_label}"
        else:
            attacker_name = "the environment" if attacker_id is None else self._format_participant_name(attacker_id)
    
        target_name = self._format_participant_name(target_id)
    
        if survived:
            # Event-style: "survived the <Event Name>"
            return True, f"{target_name} survived {attacker_name}."
        else:
            # Event-style: "was killed by the <Event Name>"
            return False, f"{target_name} was killed by {attacker_name}."

    def _pvp_flavor_text(self, attacker_id: int, defender_id: int, survived: bool) -> str:
        """
        Generate varied flavor text for PvP rounds.
        Uses templates for both survival and death outcomes and includes attacker/defender names.
        """
        attacker = self._format_participant_name(attacker_id)
        defender = self._format_participant_name(defender_id)

        survive_templates = [
            f"{defender} narrowly dodged {attacker}'s strike and lived to fight another round.",
            f"{attacker} misjudged the blow; {defender} stands bloodied but unbowed.",
            f"A lucky parry from {defender} turned the tide; {attacker} is left stunned.",
            f"{defender} found an opening and escaped {attacker}'s wrath.",
            f"{attacker} landed a hit but {defender} refused to fall.",
            f"{defender} slipped through the chaos and vanished from {attacker}'s sight.",
            f"{attacker}'s blade grazed {defender}, who staggered but stayed standing.",
            f"{defender} ducked under the swing and answered with a counter that missed by inches.",
            f"{attacker} thought it was over, but {defender} still breathes and plots revenge.",
            f"{defender} clung to life, bleeding but determined to return the favor.",
            f"{attacker} overcommitted; {defender} used the moment to crawl to safety.",
            f"{defender} rolled away from the blast and crawled back into the fight.",
            f"{attacker} struck true but not true enough; {defender} survives another heartbeat.",
            f"{defender} parried at the last second and the crowd gasped as they stayed upright.",
            f"{attacker} left an opening; {defender} exploited it and escaped with a wound.",
            f"{defender} tasted blood but not defeat, slipping into cover as {attacker} searched.",
            f"{attacker} thought the match was decided until {defender} rose again.",
            f"{defender} staggered, then steadied—refusing to be counted out by {attacker}.",
            f"{attacker} struck hard, but {defender}'s will proved harder.",
            f"{defender} used a feint to avoid death and now nurses a narrow victory.",
            f"{attacker} nearly finished {defender}, who instead found a second wind.",
            f"{defender} ducked a fatal blow and crawled toward a chance at redemption.",
            f"{attacker} celebrated too soon as {defender} slipped from the jaws of defeat.",
            f"{defender} absorbed the hit and limped away, breathing curses at {attacker}.",
            f"{attacker} left {defender} for dead; {defender} proved otherwise.",
            f"{defender} turned a desperate block into a lifeline and escaped the onslaught.",
            f"{attacker} aimed for the heart but only clipped {defender}'s sleeve; survival follows.",
            f"{defender} found a narrow crevice and squeezed through while {attacker} raged.",
            f"{attacker} thought the end had come; {defender} proved him wrong and lived on."
        ]
        death_templates = [
            f"{attacker} found a fatal opening; {defender} fell in a spray of sparks.",
            f"A decisive strike from {attacker} ended {defender}'s run.",
            f"{defender} couldn't withstand {attacker}'s assault and was cut down.",
            f"{attacker} delivered a killing blow; {defender} collapsed to the ground.",
            f"{defender} fought bravely but {attacker} proved the stronger.",
            f"{attacker} struck with cold precision and {defender} never rose again.",
            f"{defender} gasped once as {attacker} finished the job and silence followed.",
            f"{attacker} pierced through defenses; {defender} crumpled where they stood.",
            f"{defender} met {attacker}'s blade and the world went dark.",
            f"{attacker} ended the struggle in a single, brutal motion; {defender} was no more.",
            f"{defender} fell under a rain of blows from {attacker}, life ebbing fast.",
            f"{attacker} found the seam in armor and exploited it; {defender} paid the price.",
            f"{defender} fought to the last breath before {attacker} claimed the field.",
            f"{attacker} struck true and the crowd watched as {defender} fell silent.",
            f"{defender} tried to crawl away but {attacker} closed the distance and finished them.",
            f"{attacker} showed no mercy; {defender} was cut down in an instant.",
            f"{defender} made a final, futile lunge as {attacker} ended their story.",
            f"{attacker} capitalized on a mistake and {defender} paid with their life.",
            f"{defender} crumpled beneath {attacker}'s onslaught, the fight over in a heartbeat.",
            f"{attacker} struck like a viper; {defender} never had a chance.",
            f"{defender} fell amid the wreckage, {attacker} standing over the ruin.",
            f"{attacker} found the weak point and {defender} collapsed without a sound.",
            f"{defender} breathed their last as {attacker} claimed the grim reward.",
            f"{attacker} ended the duel with a single, merciless blow to {defender}.",
            f"{defender} fought until the end, but {attacker} sealed their fate.",
            f"{attacker} carved a path through defenses and {defender} could not follow.",
            f"{defender} was struck down where they stood, {attacker} unflinching.",
            f"{attacker} closed the chapter with a killing strike; {defender} lay still.",
            f"{defender} fell in a flash of steel as {attacker} executed the final move."
        ]

        # small chance for a dramatic special line
        special = [
            f"The crowd roars as {attacker} and {defender} clash in a moment of legend.",
            f"A sudden twist of fate between {attacker} and {defender} leaves everyone breathless.",
            f"Time seems to stop as {attacker} and {defender} collide in a single, unforgettable instant.",
            f"Silence falls before the storm as {attacker} and {defender} trade blows that will be retold.",
            f"The arena holds its breath while {attacker} and {defender} write a new chapter in blood.",
            f"Lightning cracks the sky as {attacker} and {defender} meet in a clash that defies fate.",
            f"All eyes fix on {attacker} and {defender} as they dance on the edge of legend.",
            f"A heartbeat stretches into an eternity when {attacker} and {defender} lock eyes and strike.",
            f"The world narrows to two figures: {attacker} and {defender}, locked in destiny's grip.",
            f"Roars and whispers mingle as {attacker} and {defender} create a scene worthy of song.",
            f"Steel sings and hearts stop as {attacker} and {defender} trade a blow that echoes forever.",
            f"Under the watchful sky, {attacker} and {defender} carve a moment that will not fade.",
            f"The crowd forgets to breathe as {attacker} and {defender} unleash everything they have.",
            f"A flash of brilliance between {attacker} and {defender} turns the fight into folklore.",
            f"{attacker} and {defender} collide with such force the ground remembers their names."
        ]

        if random.random() < 0.03:
            return random.choice(special)

        return random.choice(survive_templates if survived else death_templates)

    def _victory_flavor_text(self, winner_id: int) -> str:
        """
        Generate varied flavor text for the victory screen.
        """
        winner = self._format_participant_name(winner_id)
        templates = [
            f"{winner} stands alone amid the silence, the echoes of battle fading.",
            f"Cheers erupt as {winner} claims the spoils and the title of champion.",
            f"{winner} raises their arms in triumph; legends will speak of this day.",
            f"Bloodied but unbroken, {winner} walks away as the last survivor.",
            f"The battlefield falls quiet while {winner} basks in hard-won glory.",
            f"{winner} stands amid the wreckage, breathing victory into the cold air.",
            f"Silence settles as {winner} gathers the fallen and claims the spoils.",
            f"{winner} wipes the blood from their hands and nods to the empty field.",
            f"The crowd fades; {winner} remains, a quiet monument to survival.",
            f"{winner} walks through the smoke, every step a testament to endurance.",
            f"Under the dying light, {winner} lifts the prize and lets out a weary laugh.",
            f"{winner} surveys the ruin, the last heartbeat of the battle echoing behind them.",
            f"With steady hands, {winner} secures the spoils and turns away from the carnage.",
            f"{winner} breathes in the stillness, the cost of victory heavy but theirs.",
            f"A lone silhouette moves away from the chaos; it is {winner} who survived."
        ]
        # small chance for an epic line
        epic = [
            f"{winner}'s name will be carved into history after this brutal contest.",
            f"A single figure remains: {winner}. Songs will be sung of this victory.",
            f"{winner}'s name will be carved into history after this brutal contest.",
            f"A single figure remains: {winner}. Songs will be sung of this victory.",
            f"The stars themselves dim in respect as {winner} claims destiny's favor.",
            f"Legends will whisper of {winner}'s wrath until the end of days.",
            f"{winner} stands where gods once fought; mortals will remember this hour.",
            f"History bends to the will of {winner}, whose name will outlast empires.",
            f"From ash and ruin, {winner} rises, a beacon for future generations.",
            f"{winner} shattered fate's design and rewrote the story of this world.",
            f"When bards sing, they will begin with {winner} and end with awe.",
            f"{winner} turned the tide of fate with a single, unforgettable act.",
            f"The earth remembers the footfall of {winner}; time will mark this victory.",
            f"{winner} carved a path through legend and returned with the crown."
        ]
        if random.random() < 0.05:
            return random.choice(epic)
        return random.choice(templates)

    async def _compose_and_attach_image(self, ctx_or_channel, title: str, participants: List[int], dead_ids: Set[int], avatar_size: int = AVATAR_SIZE, center: bool = False, event: Optional[Dict] = None, victory: bool = False, layout: str = "auto") -> Tuple[discord.Embed, File]:
        """
        Create a composite image for the round and return (embed, discord.File).
        - layout controls avatar placement:
            - "auto": original behavior (avatars placed left-to-right)
            - "center": center participants horizontally
            - "separate": for exactly two participants, place one at far left and one at far right
        - event: optional event dict to prefer its image as background
        - victory: if True, prefer victory background fallbacks
        """
        width, height = COMPOSITE_SIZE

        # 1) Try to load a background image:
        bg_img = None
        # prefer event image if provided
        if event:
            ev_url = event.get("image_url")
            bg_img = await self._load_image_for_entity(ev_url, DEFAULT_EVENT_URLS, size=COMPOSITE_SIZE, default_type="event")
        # if no event bg or not provided, try configured bg defaults and module fallbacks
        if bg_img is None:
            # if victory, prefer victory fallbacks
            if victory:
                bg_img = await self._load_image_for_entity(None, DEFAULT_VICTORY_URLS, size=COMPOSITE_SIZE, default_type="bg")
            if bg_img is None:
                bg_img = await self._load_image_for_entity(None, DEFAULT_BG_URLS, size=COMPOSITE_SIZE, default_type="bg")

        # If still None (shouldn't happen), create a neutral canvas
        if bg_img is None:
            canvas = Image.new("RGBA", COMPOSITE_SIZE, (30, 30, 30, 255))
        else:
            canvas = bg_img.copy()

        draw = ImageDraw.Draw(canvas)

        # layout avatars on top of background
        n = max(1, len(participants))
        padding = 12
        avail_w = width - padding * 2

        # compute slot width and avatar dimensions
        # For 'separate' layout with two participants, give them more space and place at extremes
        if layout == "separate" and n == 2:
            avatar_w = min(avatar_size, max(32, int(avail_w * 0.28)))
            left_x = padding
            right_x = width - padding - avatar_w
            y = (height - avatar_w) // 2

            # left participant
            pid_left = participants[0]
            if isinstance(pid_left, int) and pid_left < 0:
                inst = self.npc_instances.get(pid_left, {})
                url = inst.get("image_url")
                img_left = await self._load_image_for_entity(url, DEFAULT_NPC_URLS, size=(avatar_w, avatar_w), default_type="npc", npc_instance=inst)
            else:
                user = self.bot.get_user(pid_left)
                url = None
                if user:
                    try:
                        url = str(user.display_avatar.replace(size=avatar_w).url)
                    except Exception:
                        url = None
                img_left = await self._load_image_for_entity(url, DEFAULT_NPC_URLS, size=(avatar_w, avatar_w), default_type="npc")

            if pid_left in dead_ids:
                img_left = self._apply_dead_overlay(img_left)

            # right participant
            pid_right = participants[1]
            if isinstance(pid_right, int) and pid_right < 0:
                inst = self.npc_instances.get(pid_right, {})
                url = inst.get("image_url")
                img_right = await self._load_image_for_entity(url, DEFAULT_NPC_URLS, size=(avatar_w, avatar_w), default_type="npc", npc_instance=inst)
            else:
                user = self.bot.get_user(pid_right)
                url = None
                if user:
                    try:
                        url = str(user.display_avatar.replace(size=avatar_w).url)
                    except Exception:
                        url = None
                img_right = await self._load_image_for_entity(url, DEFAULT_NPC_URLS, size=(avatar_w, avatar_w), default_type="npc")

            if pid_right in dead_ids:
                img_right = self._apply_dead_overlay(img_right)

            try:
                canvas.paste(img_left, (left_x, y), img_left)
            except Exception:
                canvas.paste(img_left, (left_x, y))
            try:
                canvas.paste(img_right, (right_x, y), img_right)
            except Exception:
                canvas.paste(img_right, (right_x, y))

        else:
            # fallback to original left-to-right or centered layout
            slot_w = min(avatar_size, max(32, avail_w // n))
            avatar_w = min(avatar_size, slot_w)
            total_width_needed = n * slot_w + (n - 1) * 8  # 8 px gap

            if layout == "center" or center:
                x = max(padding, (width - total_width_needed) // 2)
            else:
                x = padding

            y = (height - avatar_w) // 2

            for pid in participants:
                # load image for participant
                if isinstance(pid, int) and pid < 0:
                    inst = self.npc_instances.get(pid, {})
                    url = inst.get("image_url")
                    img = await self._load_image_for_entity(url, DEFAULT_NPC_URLS, size=(avatar_w, avatar_w), default_type="npc", npc_instance=inst)
                else:
                    user = self.bot.get_user(pid)
                    url = None
                    if user:
                        try:
                            url = str(user.display_avatar.replace(size=avatar_w).url)
                        except Exception:
                            url = None
                    img = await self._load_image_for_entity(url, DEFAULT_NPC_URLS, size=(avatar_w, avatar_w), default_type="npc")

                # apply dead overlay if needed
                if pid in dead_ids:
                    img = self._apply_dead_overlay(img)

                # paste avatar onto background
                try:
                    canvas.paste(img, (x, y), img)
                except Exception:
                    # fallback: paste without mask
                    canvas.paste(img, (x, y))

                x += slot_w + 8

        # Note: no text is drawn onto the image. All textual information is added to the embed.

        bio = io.BytesIO()
        canvas.save(bio, "PNG")
        bio.seek(0)
        filename = "result.png"
        file = File(bio, filename=filename)

        embed = discord.Embed(title=title, color=self._random_color())
        embed.set_image(url=f"attachment://{filename}")

        return embed, file

    # -----------------------
    # Signup embed refresh helper (new)
    # -----------------------
    async def _refresh_signup_embed(self, signup_message_id: int):
        """
        Update the signup embed to show current counts:
          - Signed up: <total> (Bots: <bots>)
        Keeps existing thumbnail and other fields intact where possible.
        """
        game = self.active_games.get(signup_message_id)
        if not game:
            return
        try:
            guild = self.bot.get_guild(game["guild_id"])
            if not guild:
                return
            channel = guild.get_channel(game["channel_id"])
            if not channel:
                return
            msg = await channel.fetch_message(signup_message_id)
            embed = msg.embeds[0] if msg.embeds else discord.Embed(title="Battle Royale Signup")
            total = len(game.get("players", []))
            bots = sum(1 for p in game.get("players", []) if isinstance(p, int) and p < 0)

            # update or add the Signed up field
            found = False
            for i, f in enumerate(embed.fields):
                if f.name == "Signed up":
                    embed.set_field_at(i, name="Signed up", value=f"{total} (Bots: {bots})", inline=False)
                    found = True
                    break
            if not found:
                embed.add_field(name="Signed up", value=f"{total} (Bots: {bots})", inline=False)

            # edit the message
            await msg.edit(embed=embed)
        except Exception:
            return

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

        # pick a thumbnail URL: prefer config, then module defaults
        thumb_url = None
        try:
            cfg_thumbs = await self.config.default_signup_thumb_urls()
        except Exception:
            cfg_thumbs = []
        candidates = [u for u in (cfg_thumbs or DEFAULT_SIGNUP_THUMB_URLS) if u]
        if candidates:
            random.shuffle(candidates)
            thumb_url = candidates[0]

        embed = discord.Embed(
            title="Battle Royale Signup",
            description="Click **Join** to enter the next Battle Royale. Mods can add NPCs with `battleroyale addnpc`.",
            color=color,
        )
        if thumb_url:
            embed.set_thumbnail(url=thumb_url)

        # initial counts
        total = 0
        bots = 0
        embed.add_field(name="Signed up", value=f"{total} (Bots: {bots})", inline=False)
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
        """List saved enemy templates with emoji-based pagination (10 entries per page)."""
        if not self.enemy_templates:
            await ctx.send("No enemy templates saved.")
            return
    
        # Page size: 10 entries per page
        PAGE_SIZE = 10
        items = [(t.get("name", "Unnamed"), t.get("image_url") or "None") for t in self.enemy_templates]
    
        # Build embeds (pages)
        embeds: List[discord.Embed] = []
        total_pages = (len(items) + PAGE_SIZE - 1) // PAGE_SIZE
        for i in range(0, len(items), PAGE_SIZE):
            chunk = items[i : i + PAGE_SIZE]
            embed = discord.Embed(title="Enemy Templates", color=self._random_color())
            for name, url in chunk:
                embed.add_field(name=name, value=url, inline=False)
            page = (i // PAGE_SIZE) + 1
            embed.set_footer(text=f"Page {page}/{total_pages}")
            embeds.append(embed)
    
        # Send first page
        current = 0
        message = await ctx.send(embed=embeds[current])
    
        # Navigation emojis
        EMOJI_PREV = "◀️"
        EMOJI_NEXT = "▶️"
        EMOJI_STOP = "⏹️"
        nav_emojis = (EMOJI_PREV, EMOJI_STOP, EMOJI_NEXT)
    
        # Add reactions (best-effort)
        for e in nav_emojis:
            try:
                await message.add_reaction(e)
            except Exception:
                pass
    
        def check(reaction: discord.Reaction, user: discord.User):
            if reaction.message.id != message.id:
                return False
            if user.bot:
                return False
            try:
                # allow invoker or server mods/admins
                if user.id == ctx.author.id:
                    return True
                member = ctx.guild.get_member(user.id) if ctx.guild else None
                if member and self.is_mod_or_admin(member):
                    return True
            except Exception:
                pass
            return False
    
        # Reaction handling loop
        while True:
            try:
                reaction, user = await self.bot.wait_for("reaction_add", timeout=120.0, check=check)
            except asyncio.TimeoutError:
                try:
                    await message.clear_reactions()
                except Exception:
                    pass
                break
    
            # keep UI tidy by removing the user's reaction (requires Manage Messages)
            try:
                await message.remove_reaction(reaction.emoji, user)
            except Exception:
                pass
    
            if reaction.emoji == EMOJI_STOP:
                try:
                    await message.clear_reactions()
                except Exception:
                    pass
                break
            elif reaction.emoji == EMOJI_NEXT:
                if current < len(embeds) - 1:
                    current += 1
                    try:
                        await message.edit(embed=embeds[current])
                    except Exception:
                        pass
            elif reaction.emoji == EMOJI_PREV:
                if current > 0:
                    current -= 1
                    try:
                        await message.edit(embed=embeds[current])
                    except Exception:
                        pass
            # ignore other emojis and continue loop

    @battleroyale.command(name="leaderboard")
    async def battleroyale_leaderboard(self, ctx: commands.Context, top: int = 10, thumbnail: str = None):
        """Show a leaderboard of users with the most Battle Royale victories.
        Usage: battleroyale leaderboard [top]
        - top: number of entries to show (1-25)
        Note: thumbnail arg is ignored; the thumbnail comes from the module-level DEFAULT_LEADERBOARD_THUMB_URL.
        Mentions are shown inside the embed but will not ping users.
        """
        # sanitize top and cap to 25 (Discord embed field limit)
        try:
            top = int(top)
        except Exception:
            top = 10
        top = max(1, min(top, 25))
    
        # Build normalized mapping from self.leaderboard (accept "user:<id>" and legacy numeric keys)
        normalized: Dict[str, int] = {}
        for k, v in (self.leaderboard or {}).items():
            # Only include user entries; skip npc keys entirely
            if isinstance(k, str) and k.startswith("user:"):
                nk = k
            else:
                # legacy numeric key -> assume user
                try:
                    nk = f"user:{int(k)}"
                except Exception:
                    # non-numeric or npc-like keys are ignored
                    continue
            normalized[nk] = normalized.get(nk, 0) + int(v)
    
        # If no normalized entries found, fall back to scanning persisted/active games for legacy wins (users only)
        if not normalized:
            raw = load_json_file(GAMES_FILE, {})
            persisted_games = []
            if isinstance(raw, dict):
                persisted_games = list(raw.values())
            elif isinstance(raw, list):
                persisted_games = raw
            all_games = persisted_games + [g for g in self.active_games.values()]
    
            wins_legacy: Dict[int, int] = {}
            for g in all_games:
                winner = g.get("winner")
                if winner is None:
                    wlist = g.get("winners") or g.get("victors")
                    if isinstance(wlist, list) and len(wlist) > 0:
                        winner = wlist[0]
                # only count positive user IDs
                if isinstance(winner, int) and winner > 0:
                    wins_legacy[winner] = wins_legacy.get(winner, 0) + 1
    
            if not wins_legacy:
                await ctx.send("No recorded user victories found.")
                return
    
            for uid, cnt in wins_legacy.items():
                normalized[f"user:{uid}"] = normalized.get(f"user:{uid}", 0) + cnt
    
        # Sort and take top entries
        items = sorted(normalized.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    
        # Build embed (cleaner layout)
        embed = discord.Embed(title="Battle Royale Leaderboard", color=self._random_color())
        embed.set_footer(text=f"Top {len(items)} players by victories")
        embed.timestamp = discord.utils.utcnow()
    
        # Thumbnail selection order (enforced):
        # 1) module-level DEFAULT_LEADERBOARD_THUMB_URL (first entry)
        # 2) configured leaderboard_thumbnail_url (persistent)
        # 3) top user's avatar (only as last resort)
        thumbnail_url: Optional[str] = None
    
        # 1) module-level constant (this is the one you set at the top of the file)
        try:
            if DEFAULT_LEADERBOARD_THUMB_URL:
                candidates = [u for u in DEFAULT_LEADERBOARD_THUMB_URL if u]
                if candidates:
                    thumbnail_url = candidates[0]
        except Exception:
            thumbnail_url = None
    
        # 2) configured persistent URL (only if module-level not set)
        if not thumbnail_url:
            try:
                cfg_thumb = await self.config.leaderboard_thumbnail_url()
                if cfg_thumb:
                    thumbnail_url = cfg_thumb
            except Exception:
                thumbnail_url = None
    
        # 3) top user's avatar (only if still None)
        if not thumbnail_url and items:
            top_uid = None
            for key, _ in items:
                if key.startswith("user:"):
                    try:
                        top_uid = int(key.split(":", 1)[1])
                        break
                    except Exception:
                        top_uid = None
            if top_uid:
                top_user = self.bot.get_user(top_uid)
                if top_user:
                    try:
                        avatar = getattr(top_user, "display_avatar", None) or getattr(top_user, "avatar", None)
                        if avatar:
                            thumbnail_url = str(avatar.url)
                    except Exception:
                        thumbnail_url = None
                else:
                    try:
                        fetched = await self.bot.fetch_user(top_uid)
                        avatar = getattr(fetched, "display_avatar", None) or getattr(fetched, "avatar", None)
                        if avatar:
                            thumbnail_url = str(avatar.url)
                    except Exception:
                        thumbnail_url = None
    
        # Apply thumbnail if available
        if thumbnail_url:
            try:
                embed.set_thumbnail(url=thumbnail_url)
            except Exception:
                pass
    
        # Build a compact, pretty description with medals for top 3 and mention strings (no pings)
        medals = ["🥇", "🥈", "🥉"]
        lines: List[str] = []
        for rank, (key, count) in enumerate(items, start=1):
            # Resolve mention string only (no duplicate display name)
            try:
                kind, id_str = key.split(":", 1)
                pid = int(id_str)
            except Exception:
                mention_str = str(key)
            else:
                mention_str = f"<@{pid}>"
    
            medal = medals[rank - 1] if rank <= 3 else f"#{rank}"
            # single-line entry: medal + mention (visual) + wins
            lines.append(f"{medal} {mention_str} — **{count}** wins")
    
        embed.description = "\n".join(lines)
    
        # Send embed with AllowedMentions set to none so mentions inside the embed do not ping
        try:
            await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            # fallback: send embed only without allowed_mentions param
            try:
                await ctx.send(embed=embed)
            except Exception:
                await ctx.send("Could not display the leaderboard at this time.")
       
    @battleroyale.command(name="reset")
    @commands.is_owner()
    async def battleroyale_reset(self, ctx: commands.Context, confirm: str = None):
        """Reset the persistent Battle Royale leaderboard.
        Usage: battleroyale reset confirm
        Note: This command is owner-only and will clear the on-disk leaderboard.json.
        """
        # determine the bot prefix to show in the confirmation prompt
        prefix = None
        try:
            prefix = getattr(ctx, "clean_prefix", None) or getattr(ctx, "prefix", None)
        except Exception:
            prefix = None
        if not prefix:
            prefix = "[p]"  # fallback if prefix can't be determined
    
        # require explicit confirmation token
        if confirm != "confirm":
            await ctx.send(f"This will permanently clear the leaderboard. To proceed, run: `{prefix}battleroyale reset confirm`")
            return
    
        # clear in-memory leaderboard and persist
        try:
            self.leaderboard = {}
            await self._save_leaderboard()
        except Exception:
            # attempt best-effort file write and report failure
            try:
                save_json_file(LEADERBOARD_FILE, {})
            except Exception:
                await ctx.send("Failed to reset leaderboard due to a file I/O error.")
                return
    
        await ctx.send("Leaderboard has been reset.")

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

        # Refresh signup embed to reflect new counts
        try:
            await self._refresh_signup_embed(signup_message_id)
        except Exception:
            pass

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

        # Refresh signup embed to reflect new counts
        try:
            await self._refresh_signup_embed(signup_message_id)
        except Exception:
            pass

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
        """
        Start the provided game dict but run it in the signup channel stored
        on the signup (game['channel_id']). This creates a minimal ctx-like
        proxy so the existing _run_game_loop signature does not need to change.
        """
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
            self.bot.remove_view(view=None, message_id=game.get("signup_message_id"))
        except Exception:
            pass

        # Resolve the channel where the signup was posted
        signup_channel = None
        try:
            guild = self.bot.get_guild(game.get("guild_id"))
            if guild:
                signup_channel = guild.get_channel(game.get("channel_id"))
            if signup_channel is None:
                signup_channel = await self.bot.fetch_channel(game.get("channel_id"))
        except Exception:
            signup_channel = None

        if signup_channel is None:
            await ctx.send("Could not find the signup channel for that game; start aborted.")
            game["running"] = False
            await self._save_games()
            return

        # Create a minimal ctx-like proxy that mirrors the real ctx interface used by the loop.
        class _CtxProxy:
            def __init__(self, original_ctx, channel):
                self._orig = original_ctx
                self.channel = channel
                self.author = getattr(original_ctx, "author", None)
                self.guild = getattr(original_ctx, "guild", None)

            async def send(self, *args, **kwargs):
                # Prefer sending into the signup channel; fall back to original ctx.send if needed.
                try:
                    return await self.channel.send(*args, **kwargs)
                except Exception:
                    return await self._orig.send(*args, **kwargs)

        proxy_ctx = _CtxProxy(ctx, signup_channel)

        try:
            # Call the existing game loop without modifying its signature.
            await self._run_game_loop(proxy_ctx, game)
        finally:
            # ensure the game is no longer marked running and perform cleanup as before
            game["running"] = False

            used_ids: Set[int] = set()
            for g in self.active_games.values():
                for pid in g.get("players", []):
                    if isinstance(pid, int) and pid < 0:
                        used_ids.add(pid)
            for nid in list(self.npc_instances.keys()):
                if nid not in used_ids:
                    self.npc_instances.pop(nid, None)
            await self._save_npcs()

            try:
                self.active_games.pop(game.get("signup_message_id"), None)
            except Exception:
                pass

            await self._save_games()

            try:
                self.bot.remove_view(view=None, message_id=game.get("signup_message_id"))
            except Exception:
                pass

    # -----------------------
    # Main game loop 
    # -----------------------
    async def _run_game_loop(self, ctx: commands.Context, game: Dict):
        """
        Simplified game loop that runs until one participant remains.
        Each iteration:
          - choose action type (pvp/event) with 70/30 split
          - select participants (two for pvp, one or more for event)
          - resolve outcome using survival probabilities
          - send an embed with the result and the image attached inside the embed
        """
        channel = ctx.channel

        # quick guard
        if not game.get("players") or len(game.get("players", [])) < 2:
            await ctx.send("Not enough participants to run the game.")
            return

        # track dead ids to show overlays in images
        dead_ids: Set[int] = set()

        round_num = 1
        # run until one remains
        while True:
            # refresh players from game state in case of external changes
            players = [p for p in game.get("players", [])]

            # stop if game cancelled or ended
            if not players or len(players) <= 1:
                break

            action, participants, event = self._select_combatants(game)
            if action == "none":
                break

            # Build round title and result lines
            if action == "pvp":
                round_title = f"Round {round_num} — PvP"
                attacker, defender = participants[0], participants[1]
                survived, text = self._resolve_attack_single(attacker, defender)
                result_lines = [text]
                if not survived:
                    try:
                        game["players"].remove(defender)
                    except ValueError:
                        pass
                    dead_ids.add(defender)

                # generate varied flavor text for PvP
                flavor = self._pvp_flavor_text(attacker, defender, survived)

                # compose image and embed, attach file and send (use 'separate' layout for PvP)
                embed, file = await self._compose_and_attach_image(ctx, round_title, participants, dead_ids, event=None, victory=False, layout="separate")

                # Put all textual info into the embed, not on the image
                embed.add_field(name="Round", value=str(round_num), inline=True)
                embed.add_field(name="Type", value="PvP", inline=True)
                embed.add_field(name="Battle", value=flavor, inline=False)  # renamed from "Flavor" to "Battle"
                embed.add_field(name="Result", value="\n".join(result_lines), inline=False)

            else:
                # Use the event name as the attacker label so flavor text and result reference the Event
                attacker_label = event.get("name") if event else "Event"
                round_title = f"Round {round_num} — {attacker_label}"
                result_lines = []
                for target in participants:
                    survived, text = self._resolve_attack_single(None, target, attacker_label=attacker_label)
                    result_lines.append(text)
                    if not survived:
                        try:
                            game["players"].remove(target)
                        except ValueError:
                            pass
                        dead_ids.add(target)

                # persist game state after each round
                await self._save_games()
                await self._save_npcs()

                # compose image and embed, attach file and send
                # pass event so event-specific background can be used; center avatars for events
                embed, file = await self._compose_and_attach_image(ctx, round_title, participants, dead_ids, event=event, victory=False, layout="center")

                # Put all textual info into the embed, not on the image
                embed.add_field(name="Round", value=str(round_num), inline=True)
                embed.add_field(name="Type", value=(event.get("name") if event else "Event"), inline=True)

                # Add event description (flavor text) when available
                if event:
                    desc = event.get("description") or "No description."
                    embed.add_field(name="Event", value=desc, inline=False)

                embed.add_field(name="Result", value="\n".join(result_lines), inline=False)

            # persist game state after each round (ensure saved even for PvP path)
            await self._save_games()
            await self._save_npcs()

            # send as a single message with attachment embedded
            try:
                await channel.send(embed=embed, file=file)
            except Exception:
                # fallback: send text if image fails
                await channel.send("\n".join(result_lines))

            # small delay between rounds to avoid rate limits and give players time
            await asyncio.sleep(1.0)
            round_num += 1

        # final summary
        remaining = game.get("players", [])
        if remaining:
            winner = remaining[0]
            try:
                await self._record_winner(winner)
            except Exception:
                pass                
            winner_name = self._format_participant_name(winner)
            victory_text = self._victory_flavor_text(winner)
            
            try:
                game["winner"] = winner                
                game["winners"] = [winner]
                await self._save_games()
            except Exception:
                pass
                
            # Resolve user mention and avatar URL (for real users) or NPC instance (for NPCs)
            avatar_url = None
            mention_text = None
            npc_inst = None
            try:
                if isinstance(winner, int) and winner >= 0:
                    user = self.bot.get_user(winner)
                    if user:
                        mention_text = user.mention
                        try:
                            avatar_url = str(user.display_avatar.replace(size=512).url)
                        except Exception:
                            avatar_url = None
                else:
                    npc_inst = self.npc_instances.get(winner)
            except Exception:
                avatar_url = None
                mention_text = None
                npc_inst = None

            # Build the textual embed (no redundant "is the last one standing" line)
            v_embed = discord.Embed(
                title="Battle Royale — Winner!",
                color=self._random_color(),
            )

            # Champion field: show only the mention for real users, otherwise show the formatted NPC/user name
            if mention_text:
                champion_value = mention_text
            else:
                champion_value = winner_name
            v_embed.add_field(name="Champion", value=champion_value, inline=True)
            v_embed.add_field(name="Victory", value=victory_text, inline=False)

            # Compose a banner image and overlay the winner's avatar (user or NPC) onto it
            try:
                banner_img = await self._load_image_for_entity(None, DEFAULT_VICTORY_URLS, size=COMPOSITE_SIZE, default_type="bg")
                if banner_img is None:
                    banner_img = Image.new("RGBA", COMPOSITE_SIZE, (30, 30, 30, 255))

                overlay_img = None
                avatar_diam = max(96, int(min(COMPOSITE_SIZE) * 0.22))

                # Try user avatar first
                if avatar_url:
                    try:
                        avatar_bytes = await self._fetch_image_bytes(avatar_url)
                        if avatar_bytes:
                            overlay_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
                            overlay_img = ImageOps.fit(overlay_img, (avatar_diam, avatar_diam), Image.LANCZOS)
                    except Exception:
                        overlay_img = None

                # If no user avatar, try NPC instance image via loader (resized)
                if overlay_img is None and npc_inst:
                    try:
                        overlay_img = await self._load_image_for_entity(npc_inst.get("image_url"), DEFAULT_NPC_URLS, size=(avatar_diam, avatar_diam), default_type="npc", npc_instance=npc_inst)
                    except Exception:
                        overlay_img = None

                # Paste overlay if available
                if overlay_img:
                    mask = Image.new("L", (avatar_diam, avatar_diam), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.ellipse((0, 0, avatar_diam, avatar_diam), fill=255)

                    margin_top = 18
                    x = (COMPOSITE_SIZE[0] - avatar_diam) // 2
                    y = margin_top

                    border = int(max(4, avatar_diam * 0.06))
                    if border:
                        border_box = Image.new("RGBA", (avatar_diam + border * 2, avatar_diam + border * 2), (0, 0, 0, 0))
                        bd_draw = ImageDraw.Draw(border_box)
                        bd_draw.ellipse((0, 0, avatar_diam + border * 2 - 1, avatar_diam + border * 2 - 1), fill=(10, 10, 10, 200))
                        bx = x - border
                        by = y - border
                        try:
                            banner_img.paste(border_box, (bx, by), border_box)
                        except Exception:
                            banner_img.paste(border_box, (bx, by))

                    try:
                        banner_img.paste(overlay_img, (x, y), mask)
                    except Exception:
                        banner_img.paste(overlay_img, (x, y))

                # Save and send banner as attachment referenced by embed
                bio = io.BytesIO()
                banner_img.save(bio, "PNG")
                bio.seek(0)
                filename = "victory_banner.png"
                file = File(bio, filename=filename)

                v_embed.set_image(url=f"attachment://{filename}")
                await channel.send(embed=v_embed, file=file)
            except Exception:
                try:
                    await channel.send(embed=v_embed)
                except Exception:
                    await channel.send(f"{winner_name} is the champion!")
        else:
            # No survivors path: send a rich embed with a remote banner image and flavor text
            try:
                no_embed = discord.Embed(
                    title="Battle Royale — No Survivors",
                    description="The battlefield falls silent. There are no survivors — everyone perished in the chaos.",
                    color=self._random_color(),
                )
                flavor = "A brutal contest with no victor. The ashes of battle are all that remain."
                no_embed.add_field(name="Outcome", value=flavor, inline=False)
                no_embed.set_footer(text="This Battle Royale ended with no survivors.")
        
                # Choose a remote banner URL: prefer configured default_no_survivors_urls, then configured bg/victory, then module fallbacks
                banner_url = None
                try:
                    cfg_no = await self.config.default_no_survivors_urls()
                except Exception:
                    cfg_no = []
        
                candidates = [u for u in (cfg_no or DEFAULT_NO_SURVIVORS_URLS) if u]
                if candidates:
                    random.shuffle(candidates)
                    banner_url = candidates[0]
        
                # If no configured no-survivors URL, fall back to configured bg/victory lists
                if not banner_url:
                    try:
                        cfg_bg = await self.config.default_bg_urls()
                    except Exception:
                        cfg_bg = []
                    candidates = [u for u in (cfg_bg or DEFAULT_VICTORY_URLS) if u]
                    if candidates:
                        random.shuffle(candidates)
                        banner_url = candidates[0]
        
                # final fallback: any module-level victory URL
                if not banner_url and DEFAULT_VICTORY_URLS:
                    banner_url = random.choice(DEFAULT_VICTORY_URLS)
        
                # If we have a banner URL, reference it directly in the embed (Discord will fetch it)
                if banner_url:
                    no_embed.set_image(url=banner_url)
        
                # --- ADDED: persist no-winner outcome so leaderboard can count finished games ---
                try:
                    game["winner"] = None
                    game["winners"] = []
                    await self._save_games()
                except Exception:
                    pass
                # --- END ADDED ---
        
                await channel.send(embed=no_embed)
            except Exception:
                await channel.send("The battle ended with no survivors. There is no winner.")

