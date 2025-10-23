import asyncio
import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import discord
from redbot.core import commands
from redbot.core.data_manager import cog_data_path


class Vania(commands.Cog):
    """Belmont’s Legacy: Hunter progression with XP, skills, inventory, and raids."""

    # ----------------- World Event Effects -----------------    
    EVENT_EFFECTS = {
        "☀️ Day": {
            "player_damage": 1.10,
            "monster_damage": 1.0,
            "player_hp": 1.05,     
            "monster_hp": 1.0,
        },
        "🌙 Night": {
            "player_damage": 1.0,
            "monster_damage": 1.20,
            "player_hp": 0.95,     
            "monster_hp": 1.10,    
        },
        "Clear skies": {
            "player_damage": 1.0,
            "monster_damage": 1.0,
            "player_hp": 1.0,
            "monster_hp": 1.0,
        },
        "Rainstorm": {
            "player_damage": 0.90,
            "monster_damage": 1.0,
            "player_hp": 1.0,
            "monster_hp": 0.95,    
        },
        "Fog": {
            "player_damage": 1.0,
            "monster_damage": 0.90,
            "player_hp": 1.0,
            "monster_hp": 0.9,
        },
        "Thunderstorm": {
            "player_damage": 1.0,
            "monster_damage": 1.15,
            "player_hp": 0.95,
            "monster_hp": 1.05,
        },
        "Snow": {
            "player_damage": 1.0,
            "monster_damage": 0.85,
            "player_hp": 1.05,
            "monster_hp": 0.9,
        },
        "🌑 Blood Moon": {
            "player_damage": 0.9,
            "monster_damage": 1.3,
            "player_hp": 0.9,
            "monster_hp": 1.2,
        },
        "🌞 Solar Eclipse": {
            "player_damage": 1.2,
            "monster_damage": 0.8,
            "player_hp": 1.1,
            "monster_hp": 0.9,
        },
        "🌾 Harvest Festival": {
            "player_damage": 1.15,
            "monster_damage": 1.0,
            "player_hp": 1.2,
            "monster_hp": 1.0,
        },
    }  

    STAGE_DEFINITIONS = {
        "Graveyard": (1, 25),
        "Village Outskirts": (26, 65),
        "Castle Approach": (66, 110),
        "Inner Halls": (111, 170),
        "The Sanctum": (171, 10_000_000),
    }  

    def __init__(self, bot):
        self.bot = bot
        self._write_lock = asyncio.Lock()

        # Data folder inside cog package
        data_pkg = Path(__file__).parent / "data"
        self.monsters = self._safe_load_pkg_json(data_pkg / "monsters.json")
        self.items = self._safe_load_pkg_json(data_pkg / "items.json")
        self.skills_def = self._safe_load_pkg_json(data_pkg / "skills.json")
        self.equipment = self._safe_load_pkg_json(data_pkg / "equipment.json")
        self.bosses = self._safe_load_pkg_json(data_pkg / "bosses.json")

        # Cog runtime data folder (Red's data path)
        data_folder = cog_data_path(self)
        data_folder.mkdir(parents=True, exist_ok=True)

        self.raid_file = data_folder / "raids.json"
        self.data_file = data_folder / "profiles.json"

        # Settings file for channel configuration
        self.settings_file = data_folder / "settings.json"
        if not self.settings_file.exists():
            self.settings_file.write_text(json.dumps({}))

        # Current world event state
        self.current_event = None

        # Background task handle for this cog instance
        self.bg_task: Optional[asyncio.Task] = None

        # If a previous Vania bg task was left attached to the bot from an older load,
        # attempt to cancel it so we don't accumulate duplicate loops.
        prev_task = getattr(self.bot, "_vania_bg_task", None)
        if prev_task and hasattr(prev_task, "cancel") and not getattr(prev_task, "done", lambda: True)():
            try:
                prev_task.cancel()
            except Exception:
                pass

        # Start this instance's background loop and register it on the bot so future reloads can find it.
        self.bg_task = self.bot.loop.create_task(self._cycle_events())
        try:
            self.bot._vania_bg_task = self.bg_task
        except Exception:
            # Some bot objects may not allow arbitrary attributes; ignore failure.
            pass   

        # Ensure files exist and are valid JSON
        for f in (self.raid_file, self.data_file):
            if not f.exists():
                f.write_text(json.dumps({}))
            else:
                try:
                    json.loads(f.read_text())
                except Exception:
                    backup = f.with_suffix(f".corrupt_{int(random.random()*1e9)}.bak")
                    f.rename(backup)
                    f.write_text(json.dumps({}))
                    
    def cog_unload(self):
        """Cancel background task on cog unload and clear bot registry to avoid leftover tasks."""
        try:
            task = getattr(self, "bg_task", None)
            if task and not task.done():
                task.cancel()
        except Exception:
            pass
        try:
            # Only remove the bot-stored reference if it points to this instance's task.
            if getattr(self.bot, "_vania_bg_task", None) is getattr(self, "bg_task", None):
                try:
                    delattr(self.bot, "_vania_bg_task")
                except Exception:
                    # fallback if delattr fails
                    try:
                        del self.bot._vania_bg_task
                    except Exception:
                        pass
        except Exception:
            pass                   

    # ----------------- Safe package JSON loader -----------------
    def _safe_load_pkg_json(self, path: Path) -> dict:
        if not path.exists():
            raise FileNotFoundError(f"{path.name} not found in data folder")
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            raise ValueError(f"{path.name} contains invalid JSON")

    # ----------------- Profiles and Raids (thread-safe saves) -----------------
    def _load_profiles(self) -> dict:
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return {}

    async def _save_profiles(self, data: dict):
        tmp = self.data_file.with_suffix(".tmp")
        async with self._write_lock:
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(self.data_file)

    def _load_raids(self) -> dict:
        try:
            return json.loads(self.raid_file.read_text())
        except Exception:
            return {}

    async def _save_raids(self, data: dict):
        tmp = self.raid_file.with_suffix(".tmp")
        async with self._write_lock:
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(self.raid_file)
            
    # ----------------- Settings helpers -----------------
    def _load_settings(self) -> dict:
        try:
            return json.loads(self.settings_file.read_text())
        except Exception:
            return {}

    async def _save_settings(self, data: dict):
        tmp = self.settings_file.with_suffix(".tmp")
        async with self._write_lock:
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(self.settings_file)            

    # ----------------- Utilities -----------------
    def _default_profile(self) -> dict:
        return {
            "xp": 0,
            "level": 1,
            "skills": {},
            # equipment slots
            "weapon": None,
            "offhand": None,
            "head": None,
            "body": None,
            "legs": None,
            "arms": None,
            "cloak": None,
            "accessory1": None,
            "accessory2": None,
            # hp/hearts/inventory
            "hp": 50,
            "max_hp": 50,
            "hearts": 0,
            "relics": [],
            "consumables": {},
            "items": {}
        }

    def _get_equipment(self, equip_id: Optional[str]) -> dict:
        if not equip_id:
            return {}
        return next((e for e in self.equipment if e.get("id") == equip_id), {})

    def _health_bar(self, current: int, maximum: int, length: int = 20) -> str:
        maximum = max(1, int(maximum))
        current = max(0, min(current, maximum))
        filled = int(current / maximum * length)
        return "█" * filled + "─" * (length - filled)

    # ---------- Leveling curve configuration and helpers (steeper) ----------
    # Base XP for level 1->2 and exponential scale per level
    xp_base: int = 100
    xp_scale: float = 1.5  # much steeper growth

    def _xp_for_level(self, level: int) -> int:
        """
        XP required to advance from `level` to `level + 1`.
        Exponential growth: base * scale^(level-1)
        """
        lvl = max(1, int(level))
        return int(self.xp_base * (self.xp_scale ** (lvl - 1)))

    def _level_from_xp(self, total_xp: int) -> int:
        """
        Convert cumulative total_xp into a discrete level.
        Subtract per-level requirements until remaining XP is less than the next-level requirement.
        Safety cap to avoid infinite loops.
        """
        xp = max(0, int(total_xp))
        lvl = 1
        max_iters = 1000
        iters = 0
        while xp >= self._xp_for_level(lvl) and iters < max_iters:
            xp -= self._xp_for_level(lvl)
            lvl += 1
            iters += 1
        return lvl

    # ----------------- Combat helpers (turn-based) -----------------
    def _player_attack(self, profile: dict, monster: dict) -> Tuple[int, bool]:
        """
        Compute player's damage against the monster for one attack.
        Returns (damage, is_crit).
        Weapon metadata supported: min_damage, max_damage, damage_mod, xp_mod, crit_chance, crit_multiplier.
        Level and skill scaling applied.
        """
        weapon = self._get_equipment(profile.get("weapon"))
        # Unarmed: base 5-10 plus a small level-based bonus so fists scale slightly with level.
        # Apply a reduced weapon_mod so unarmed remains weaker than proper weapons.
        if not weapon:
            lvl = int(profile.get("level", 1))
            # small per-level bonus (e.g., +0.5 damage per level, rounded down)
            lvl_bonus = lvl // 2  # 0 at lvl1, +1 every 2 levels
            base_min = 5 + lvl_bonus
            base_max = 10 + lvl_bonus
            base = random.randint(base_min, base_max)
            weapon_mod = 0.75
        else:
            base_min = int(weapon.get("min_damage", 8))
            base_max = int(weapon.get("max_damage", 14))
            base = random.randint(base_min, base_max)
            weapon_mod = float(weapon.get("damage_mod", 1.0))

        lvl = int(profile.get("level", 1))
        level_scale = 1.0 + 0.05 * max(0, lvl - 1)

        skills = profile.get("skills", {})
        whip_mastery = int(skills.get("WhipMastery", 0))
        skill_scale = 1.0 + 0.10 * whip_mastery

        crit_chance = float(weapon.get("crit_chance", 0.05)) + 0.01 * whip_mastery
        crit_multiplier = float(weapon.get("crit_multiplier", 1.5))

        # --- Player miss / accuracy ---
        # Base miss chance; reduced by WhipMastery and modified by weapon 'accuracy' (default 1.0).
        base_miss = 0.05
        weapon_accuracy = float(weapon.get("accuracy", 1.0))
        # accuracy >1.0 reduces miss, <1.0 increases it; clamp to [0.0, 0.5]
        miss_chance = base_miss - 0.01 * whip_mastery + (0.03 * (1.0 - weapon_accuracy))
        miss_chance = max(0.0, min(0.5, miss_chance))

        # Miss cancels the attack (no crit)
        if random.random() < miss_chance:
            return 0, False

        is_crit = random.random() < crit_chance
        mult = crit_multiplier if is_crit else 1.0

        dmg = int(base * weapon_mod * level_scale * skill_scale * mult)
        event = getattr(self, "current_event", None)
        if event:
            time_mult = self.EVENT_EFFECTS.get(event["time"], {}).get("player_damage", 1.0)
            weather_mult = self.EVENT_EFFECTS.get(event["weather"], {}).get("player_damage", 1.0)
            dmg = int(dmg * time_mult * weather_mult)        
        return max(0, dmg), is_crit

    def _monster_attack(self, profile: dict, monster: dict) -> int:
        """
        Compute monster damage against player for one attack.
        Monster metadata supported: min_damage, max_damage.
        Armor defense reduces damage; Evasion skill can dodge.
        """
        base_min = int(monster.get("min_damage", max(1, int(monster.get("hp", 10) * 0.05))))
        base_max = int(monster.get("max_damage", max(2, int(monster.get("hp", 10) * 0.15))))
        base = random.randint(base_min, base_max)
        event = getattr(self, "current_event", None)
        if event:
            time_mult = self.EVENT_EFFECTS.get(event["time"], {}).get("monster_damage", 1.0)
            weather_mult = self.EVENT_EFFECTS.get(event["weather"], {}).get("monster_damage", 1.0)
            base = int(base * time_mult * weather_mult)        

        # total defense = body + offhand (some offhands may add defense) + head/arms/legs/cloak
        defense = 0
        for slot in ("body", "offhand", "head", "arms", "legs", "cloak"):
            defense += int(self._get_equipment(profile.get(slot)).get("defense", 0))

        skills = profile.get("skills", {})
        evasion = int(skills.get("Evasion", 0))
        dodge_chance = 0.02 * evasion
        # Monster accuracy modifier (monster defs can include 'accuracy' default 1.0)
        monster_accuracy = float(monster.get("accuracy", 1.0))
        # base miss for monsters is small; reduced by accuracy >1.0
        monster_base_miss = 0.04
        monster_miss_chance = monster_base_miss + (0.03 * (1.0 - monster_accuracy)) - dodge_chance
        monster_miss_chance = max(0.0, min(0.5, monster_miss_chance))
        if random.random() < monster_miss_chance:
            return 0

        dmg = max(0, base - defense)
        return dmg
        
    # ----------------- Background world events -----------------
    async def _cycle_events(self):
        """Background loop: post world events on a schedule and exit cleanly when cancelled."""
        try:
            await self.bot.wait_until_ready()
    
            # Flavor pools tuned for a Gothic Castlevania mood
            time_flavor = {
                "☀️ Day": [
                    "A pale sun climbs above the jagged rooftops; the streets smell of cold soot and memory.",
                    "Dawn creeps across the crumbling spires, light like a blade against shadows.",
                    "A thin glare washes the alleyways, revealing ruined banners and forgotten promises.",
                    "The day seems borrowed, every warmth uneasy and measured like a toll.",
                    "Pigeons scatter from spires; even small noises echo as if the city keeps secrets.",
                    "Shopkeepers shutter windows with hands that tremble as if expecting old debts.",
                    "A brittle clarity settles on the lanes; the light shows stains that time refuses to hide."                    
                ],
                "🌙 Night": [
                    "The moon bleeds silver over the castle towers; distant howls stitch the dark.",
                    "A velvet night wraps the land, and every echo seems to hold a warning.",
                    "Lanterns gutter and a thousand small shadows lengthen into accusations.",
                    "Night smells of peat and iron; footsteps seem larger than their makers.",
                    "Cat-calls and whispered bargains scrape down under-arches like stray wind.",
                    "A solitary bell tolls somewhere; its hollow sound tastes like unfinished business.",
                    "The alleys sew themselves closed under a shawl of velvet and chill."                    
                ],
                "🌑 Blood Moon": [
                    "The moon turns bruised and red; creatures of old grow bold and cruel.",
                    "Under the Blood Moon the land tastes of iron and old sins; none sleep easy.",
                    "Bloodlight paints the hedgerows; even the trees look like they remember wrath.",
                    "Shadows take on teeth and hunger; lamplight fizzles under their glare.",
                    "The world smells of copper and old war; every animal bares a sharper edge.",
                    "Faint music warps through the streets, a warped lullaby that twines with hunger.",
                    "Eyes gleam where there should be none; patrols stop to listen and do not speak."                    
                ],
                "🌞 Solar Eclipse": [
                    "A hush falls as the sun is swallowed; shadows move with unnatural intent.",
                    "Daylight falters and the world leans toward a strange, burning calm.",
                    "Shadows stretch long and wrong; colors wash out like old paintings left to the rain.",
                    "A distant roar seems to come from the sun itself as it blinks and hides.",
                    "People pause mid-step as if the air has become a question they cannot answer.",
                    "Light thins to a coin's edge; heat and cold argue in the same breath.",
                    "Birdsong stops; where it should be, there is only a waiting that smells of ash."                    
                ],
                "🌾 Harvest Festival": [
                    "Lanterns sway and a fragile cheer hangs in the air, but the fields whisper of offerings paid.",
                    "A hollow celebration; laughter and music thinly veil the scent of old bargains.",
                    "Banners fold over with careful hands; smiles look practiced, like carved things.",
                    "The fair smells of honey and iron; joy seems to be keeping one eye closed.",
                    "Children dart between stalls, their laughter too bright for the dust beneath their feet.",
                    "The feast tables groan with bounty while furtive glances count coins in shadow.",
                    "A fiddler plays a merry tune with a tremor at the edge; the tune never quite resolves."                    
                ],
            }
    
            weather_flavor = {
                "Clear skies": [
                    "The sky hangs clear but unforgiving, an empty witness to any wickedness below.",
                    "Stars gaze down like patient judges; the air is brittle and watchful.",
                    "Distant lights blink like watchful eyes; nothing moves without being seen.",
                    "The wind is thin and sharp, as if the world itself has been whittled.",
                    "Cold light reveals more than comfort; it shows the map of old scars.",
                    "The horizon looks too honest; secrets seem to gather in the corners.",
                    "Silence sits heavy beneath that clear ceiling; even birds fly less boldly."                    
                ],
                "Rainstorm": [
                    "Rain lashes like a thousand tiny blades; the cobbles gleam with old, forgotten blood.",
                    "A cold downpour drums a funeral march on slate roofs and wilted flags.",
                    "Water runs in black ribbons down gutters; faces blur in the downpour like wet portraits.",
                    "The rain smells of metal and memory; people hurry as if someone follows.",
                    "Storm drains cough up the city\u2019s past; the sound is like an old throat clearing.",
                    "Umbrellas bloom like dark mushrooms; each one a small, guarded secret.",
                    "Puddles mirror the sky but show a darker version that never quite matches."                    
                ],
                "Fog": [
                    "A thick fog slithers through alleys, swallowing shapes and swallowing sound.",
                    "Veils of mist hide more than they reveal; footsteps could belong to friend or fiend.",
                    "Figures loom and unloom in the haze; the world loses its edges and gains whispers.",
                    "Moist air tastes faintly of old iron and the hush of basements long sealed.",
                    "Lanterns appear as halos around strangers; faces come and go like old debts.",
                    "The fog carries distant laughter that might, or might not, be human.",
                    "Paths double back on themselves; a man may find he has walked nowhere and always."                    
                ],
                "Thunderstorm": [
                    "Lightning cracks the heavens like a summoned whip; thunder answers with an animal roar.",
                    "Storm and shadow collude, each flash revealing silhouettes of the damned.",
                    "Electric light stabs the sky and leaves black ink stains where it touched.",
                    "Thunder rolls like cartwheels of fate; every window shivers in answer.",
                    "Sparks leap from iron railings as if the town itself grows teeth for the night.",
                    "The first gust smells of ozone and warnings; roofs groan as if recalling weight.",
                    "Rain hammers like small mallets; the world seems to be hammered back into shape."                    
                ],
                "Snow": [
                    "Snow falls like ash upon the ruins; each flake muffles the groan of old bones.",
                    "A hush of cold white softens even the harshest moans of the night.",
                    "Footprints vanish quickly, swallowed by clean, cruel silence and cold.",
                    "Icicles hang like knives from eaves; every step cracks like a small, brittle oath.",
                    "Breath paints the air in ghostly puffs; the town exhales as if all agreed to wait.",
                    "Snowflakes glitter on tarnished metal like tiny, indifferent stars.",
                    "The world looks politely dead; those who walk it feel small and secretive."                    
                ],
                "🌑 Blood Moon": [
                    "A red haze thins across the horizon; scents sharpen and teeth twitch in hunger.",
                    "The sky oozes bloodlight; even the bravest pause as old things rouse.",
                    "The light makes familiar features look feral; statues seem to leer from their plinths.",
                    "Animals move with a strange ceremony; their eyes reflect a poem of hunger.",
                    "Streetlights bleed color into puddles; reflections seem to whisper names.",
                    "The wind carries a far-off chorus that sounds like old prayers and older curses.",
                    "Shadows gather in corners and exchange news with low, slitted voices."                    
                ],
                "🌞 Solar Eclipse": [
                    "Shadows writhe where light should be; a strange warmth and cold war in the air.",
                    "The sky warps and the world holds its breath, as if something watches from the dark.",
                    "People stop mid-breath as the eclipse folds the day in half; even dogs sit still.",
                    "Shadows pool at doorways like oil; walking through them feels like stepping into sleep.",
                    "Light frays like old cloth at the edges; everything looks like a stage prop.",
                    "A dull, sweet smell rises from drains as if the city exhales an old secret.",
                    "You can hear distant things more clearly; not because they are louder, but because the world is thinner."                    
                ],
                "🌾 Harvest Festival": [
                    "Lanterns hang, faces glow, and yet the fields whisper of tolls exacted long ago.",
                    "Bounty and bargains walk hand in hand; the feast hides small, necessary sacrifices.",
                    "Trays clink; someone laughs too loudly while someone else counts coins in the dark.",
                    "The bread is warm and the ale goes down easy, but each mouth tastes a little of debt.",
                    "Children trade trinkets with solemn faces, as if they understand obligations beyond their years.",
                    "A troupe of masked performers moves like a slow omen through the square.",
                    "The smell of roasted meat mingles with the faint, sharp perfume of old offerings."                    
                ],
            }
    
            # small mapping for embed color per time/weather for mood
            color_map = {
                "☀️ Day": discord.Color.dark_gold(),
                "🌙 Night": discord.Color.dark_purple(),
                "Clear skies": discord.Color.blue(),
                "Rainstorm": discord.Color.dark_blue(),
                "Fog": discord.Color.greyple(),
                "Thunderstorm": discord.Color.dark_magenta(),
                "Snow": discord.Color.light_grey(),
                "🌑 Blood Moon": discord.Color.dark_red(),
                "🌞 Solar Eclipse": discord.Color.dark_teal(),
                "🌾 Harvest Festival": discord.Color.orange()
            }
    
            # optional decorative images keyed by weather/time (replace with your own hosted art URLs)
            art_map = {k: None for k in color_map.keys()}
    
            while not self.bot.is_closed():
                settings = self._load_settings()
                for guild_id, conf in settings.items():
                    chan_id = conf.get("channel_id")
                    channel = self.bot.get_channel(chan_id)
                    if not channel:
                        continue
    
                    # pick time and weather, set current_event
                    time_of_day = random.choice(list(time_flavor.keys()))
                    weather = random.choice(list(weather_flavor.keys()))
                    self.current_event = {"time": time_of_day, "weather": weather}
    
                    # assemble flavor: one time snippet + one weather snippet, plus a mechanical hint line
                    t_snip = random.choice(time_flavor.get(time_of_day, ["The hour turns."]))
                    w_snip = random.choice(weather_flavor.get(weather, ["The air shifts."]))
                    mech_time = self.EVENT_EFFECTS.get(time_of_day, {})
                    mech_weather = self.EVENT_EFFECTS.get(weather, {})
                    affects = []
                    if mech_time.get("player_damage", 1.0) != 1.0 or mech_weather.get("player_damage", 1.0) != 1.0:
                        affects.append("player damage")
                    if mech_time.get("monster_damage", 1.0) != 1.0 or mech_weather.get("monster_damage", 1.0) != 1.0:
                        affects.append("monster damage")
                    if mech_time.get("player_hp", 1.0) != 1.0 or mech_weather.get("player_hp", 1.0) != 1.0:
                        affects.append("player HP")
                    if mech_time.get("monster_hp", 1.0) != 1.0 or mech_weather.get("monster_hp", 1.0) != 1.0:
                        affects.append("monster HP")
                    affects_text = " · ".join(affects) if affects else "no mechanical changes"
    
                    # build embed with gothic styling
                    color_choice = color_map.get(weather, discord.Color.dark_grey()) or color_map.get(time_of_day, discord.Color.dark_grey())
                    embed = discord.Embed(
                        title=f"World Event — {time_of_day} • {weather}",
                        description=f"{t_snip}\n\n{w_snip}",
                        color=color_choice
                    )
    
                    # optional artwork
                    art = art_map.get(weather) or art_map.get(time_of_day)
                    if art:
                        embed.set_image(url=art)
    
                    embed.add_field(name="Castlevania Note", value="Shadows lengthen, monsters stir; prepare your whip and steel.", inline=False)
                    embed.add_field(name="Mechanical Effects", value=affects_text, inline=False)
                    embed.set_footer(text=f"Time: {time_of_day} • Weather: {weather} • Effects: {affects_text}")
    
                    try:
                        await channel.send(embed=embed)
                    except Exception:
                        pass
    
                # Sleep in one chunk but respond quickly to cancellation
                await asyncio.sleep(3 * 60 * 60)
        except asyncio.CancelledError:
            # Task was cancelled (cog unload / reload); exit quietly.
            return
        except Exception:
            # Unexpected error: exit quietly to avoid runaway tasks. Consider logging if you want to inspect.
            return


    # ----------------- Immediate event poster (reusable) -----------------
    async def _post_event_to_channel(self, channel: discord.TextChannel):
        """
        Compose and send a single world-event embed (same style as _cycle_events).
        Returns the chosen event dict so callers can inspect or set current_event.
        """
        # pick time and weather
        time_of_day = random.choice(list({
            "☀️ Day","🌙 Night","🌑 Blood Moon","🌞 Solar Eclipse","🌾 Harvest Festival"
        }))
        weather = random.choice(list({
            "Clear skies","Rainstorm","Fog","Thunderstorm","Snow","🌑 Blood Moon","🌞 Solar Eclipse","🌾 Harvest Festival"
        }))
        self.current_event = {"time": time_of_day, "weather": weather}

        # reuse flavor pools and maps defined in _cycle_events scope by rebuilding minimal copies here
        time_flavor = {
            "☀️ Day": ["A pale sun climbs above the jagged rooftops; the streets smell of cold soot and memory."],
            "🌙 Night": ["The moon bleeds silver over the castle towers; distant howls stitch the dark."],
            "🌑 Blood Moon": ["The moon turns bruised and red; creatures of old grow bold and cruel."],
            "🌞 Solar Eclipse": ["A hush falls as the sun is swallowed; shadows move with unnatural intent."],
            "🌾 Harvest Festival": ["Lanterns sway and a fragile cheer hangs in the air, but the fields whisper of offerings paid."],
        }
        weather_flavor = {
            "Clear skies": ["The sky hangs clear but unforgiving, an empty witness to any wickedness below."],
            "Rainstorm": ["Rain lashes like a thousand tiny blades; the cobbles gleam with old, forgotten blood."],
            "Fog": ["A thick fog slithers through alleys, swallowing shapes and swallowing sound."],
            "Thunderstorm": ["Lightning cracks the heavens like a summoned whip; thunder answers with an animal roar."],
            "Snow": ["Snow falls like ash upon the ruins; each flake muffles the groan of old bones."],
            "🌑 Blood Moon": ["A red haze thins across the horizon; scents sharpen and teeth twitch in hunger."],
            "🌞 Solar Eclipse": ["Shadows writhe where light should be; a strange warmth and cold war in the air."],
            "🌾 Harvest Festival": ["Lanterns hang, faces glow, and yet the fields whisper of tolls exacted long ago."],
        }
        color_map = {
            "☀️ Day": discord.Color.dark_gold(),
            "🌙 Night": discord.Color.dark_purple(),
            "Clear skies": discord.Color.blue(),
            "Rainstorm": discord.Color.dark_blue(),
            "Fog": discord.Color.greyple(),
            "Thunderstorm": discord.Color.dark_magenta(),
            "Snow": discord.Color.light_grey(),
            "🌑 Blood Moon": discord.Color.dark_red(),
            "🌞 Solar Eclipse": discord.Color.dark_teal(),
            "🌾 Harvest Festival": discord.Color.orange()
        }

        t_snip = random.choice(time_flavor.get(time_of_day, ["The hour turns."]))
        w_snip = random.choice(weather_flavor.get(weather, ["The air shifts."]))

        mech_time = self.EVENT_EFFECTS.get(time_of_day, {})
        mech_weather = self.EVENT_EFFECTS.get(weather, {})
        affects = []
        if mech_time.get("player_damage", 1.0) != 1.0 or mech_weather.get("player_damage", 1.0) != 1.0:
            affects.append("player damage")
        if mech_time.get("monster_damage", 1.0) != 1.0 or mech_weather.get("monster_damage", 1.0) != 1.0:
            affects.append("monster damage")
        if mech_time.get("player_hp", 1.0) != 1.0 or mech_weather.get("player_hp", 1.0) != 1.0:
            affects.append("player HP")
        if mech_time.get("monster_hp", 1.0) != 1.0 or mech_weather.get("monster_hp", 1.0) != 1.0:
            affects.append("monster HP")
        affects_text = " · ".join(affects) if affects else "no mechanical changes"

        embed = discord.Embed(
            title=f"World Event — {time_of_day} • {weather}",
            description=f"{t_snip}\n\n{w_snip}",
            color=color_map.get(weather) or color_map.get(time_of_day) or discord.Color.dark_grey()
        )
        embed.add_field(name="Castlevania Note", value="Shadows lengthen, monsters stir; prepare your whip and steel.", inline=False)
        embed.add_field(name="Mechanical Effects", value=affects_text, inline=False)
        embed.set_footer(text=f"Time: {time_of_day} • Weather: {weather} • Effects: {affects_text}")

        try:
            await channel.send(embed=embed)
        except Exception:
            pass

        return self.current_event            

    # ----------------- Event listeners for raid participant persistence -----------------
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot:
            return
        raids = self._load_raids()
        for boss_id, data in list(raids.items()):
            if data.get("message_id") == reaction.message.id and data.get("channel_id") == reaction.message.channel.id:
                if str(reaction.emoji) != "✅":
                    return
                participants = set(data.get("participants", []))
                participants.add(str(user.id))
                data["participants"] = list(participants)
                raids[boss_id] = data
                await self._save_raids(raids)
                return

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.User):
        if user.bot:
            return
        raids = self._load_raids()
        for boss_id, data in list(raids.items()):
            if data.get("message_id") == reaction.message.id and data.get("channel_id") == reaction.message.channel.id:
                if str(reaction.emoji) != "✅":
                    return
                participants = set(data.get("participants", []))
                participants.discard(str(user.id))
                data["participants"] = list(participants)
                raids[boss_id] = data
                await self._save_raids(raids)
                return

    # ----------------- Commands -----------------
    @commands.group(name="vania", invoke_without_command=True)
    async def vania(self, ctx: commands.Context):
        """Main command for Belmont’s Legacy RPG."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @commands.cooldown(1, 30, commands.BucketType.user)
    @vania.command(name="hunt")
    async def hunt(self, ctx: commands.Context):
        """
        Turn-based hunt with stage selection: choose a stage (HP-range) and fight a monster sampled from that stage.
        """
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid, self._default_profile())

        # Prevent starting a hunt if player is down at 0 HP
        if int(profile.get("hp", profile.get("max_hp", 100))) <= 0:
            return await ctx.send("You are at 0 HP and cannot hunt. Use `vania heal` or a revive item first.")

        # Build select options from STAGE_DEFINITIONS
        options = []
        for name, (low, high) in self.STAGE_DEFINITIONS.items():
            # keep option label visible but hide HP range from the dropdown description
            options.append(discord.SelectOption(label=name, value=name, description=""))

        # Temporary select view for stage choice
        class _StageSelect(discord.ui.Select):
            def __init__(self, opts):
                super().__init__(placeholder="Choose a stage to hunt in...", min_values=1, max_values=1, options=opts)

            async def callback(self, interaction: discord.Interaction):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("This selection is not for you.", ephemeral=True)
                    return
                # acknowledge quickly, record selection, then immediately disable the UI so it cannot be reused
                await interaction.response.defer()
                view.selected = self.values[0]
                # disable all child components so the message shows the expired/locked state
                try:
                    for c in list(view.children):
                        c.disabled = True
                    if msg:
                        await msg.edit(content=f"Stage selected: **{view.selected}**", view=view)
                except Exception:
                    pass
                view.stop()

        class _StageView(discord.ui.View):
            def __init__(self, opts, timeout: int = 60):
                super().__init__(timeout=timeout)
                self.add_item(_StageSelect(opts))
                self.selected: Optional[str] = None

            async def on_timeout(self):
                try:
                    for c in list(self.children):
                        c.disabled = True
                    if msg:
                        await msg.edit(view=self)
                except Exception:
                    pass

        view = _StageView(options)
        msg = await ctx.send("Choose a stage to hunt in:", view=view)
        try:
            await view.wait()
        except Exception:
            pass

        if not view.selected:
            try:
                await msg.edit(content="Hunt cancelled (no stage selected).", view=view)
            except Exception:
                pass
            return

        stage_name = view.selected
        low, high = self.STAGE_DEFINITIONS.get(stage_name, (1, 10_000_000))

        # Filter monsters by their base hp in package data (monster_def["hp"])
        candidates = [m for m in self.monsters if isinstance(m.get("hp"), (int, float)) and low <= int(m.get("hp", 0)) <= high]
        if not candidates:
            # fallback to whole pool if none match
            candidates = self.monsters
            await ctx.send(f"No monsters configured for **{stage_name}**; sampling from full monster pool.")

        # Sample monster from candidates
        monster_def = random.choice(candidates)
        monster = {
            "id": monster_def.get("id"),
            "name": monster_def.get("name", "Unknown"),
            "hp": int(monster_def.get("hp", 10)),
            "max_hp": int(monster_def.get("hp", 10)),
            "xp_reward": int(monster_def.get("xp_reward", 0)),
            "heart_reward": monster_def.get("heart_reward", 0),
            "min_damage": monster_def.get("min_damage"),
            "max_damage": monster_def.get("max_damage"),
            "crit_chance": monster_def.get("crit_chance", 0.0),
            "crit_multiplier": monster_def.get("crit_multiplier", 1.0),
            "image": monster_def.get("image"),
        }

        # Apply HP buffs/debuffs from world event
        event = getattr(self, "current_event", None)
        if event:
            hp_mult = self.EVENT_EFFECTS.get(event["time"], {}).get("monster_hp", 1.0)
            hp_mult *= self.EVENT_EFFECTS.get(event["weather"], {}).get("monster_hp", 1.0)
            monster["hp"] = int(monster["hp"] * hp_mult)
            monster["max_hp"] = int(monster["max_hp"] * hp_mult)

        # Support probabilistic heart_reward object or integer
        def extract_heart_reward(hr):
            if isinstance(hr, dict):
                if random.random() <= float(hr.get("chance", 1.0)):
                    return int(hr.get("amount", 0))
                return 0
            return int(hr or 0)

        # --- from here onward we reuse the original hunt combat code unchanged ---
        log_lines: List[str] = []

        # ---------------- Flavor text pools ----------------
        player_hit_flavor = [
            "A clean strike finds its mark, ringing in the silent air.",
            "Your whip sings through the air and bites deep into its flesh.",
            "You slash in a wide arc, and the monster recoils, leaving a dark smear.",
            "A precise strike lands on a vulnerable spot, blood beading like on wrought iron.",
            "You follow through with a brutal riposte that cuts off its momentum.",
            "You thrust forward, your weapon finding purchase and tearing a ragged wound.",
            "A brutal snap of leather — the monster staggers, clutching at torn hide.",
            "Your blade/whip bites with practiced cruelty; the creature's roar falters.",
            "The attack cleaves cleanly, leaving a slow, red trail down its flank.",
            "Steel sings as it meets sinew; the monster's eyes flash with surprised pain.",
            "You find a seam and pry it open; the wound breathes out a small, bitter hiss.",
            "Leather snaps and sinew parts; the beast staggers as if remembering an old injury.",
            "Your strike lands with cold precision, like a clockwork blade finding its mark."            
        ]
        player_crit_flavor = [
            "A crushing critical! The blow rends armor and bone; a cry shatters the night.",
            "A devastating hit pierces through its defenses, leaving it stunned and bleeding.",
            "Critical strike! Your weapon cleaves true, spilling a bitter, copper smell.",
            "You strike with uncanny force; the monster staggers and gurgles, its life unwinding.",
            "A deathly strike lands with terrible grace; the creature's eyes dim.",
            "The blow splits armor like parchment; something essential snaps inside the beast.",
            "A fatal seam opens; the creature's howl cuts off as life pours like dark wine.",
            "You hit the fulcrum of its balance; it collapses in a heap of ruined fury.",
            "A thunderous strike rends hide and metal alike, and silence rushes in.",
            "Your weapon sings a cold, final note as it rends the monster's stubborn heart."            
        ]
        player_miss_flavor = [
            "Your attack grazes harmlessly off its hide, sparks flying from cursed mail.",
            "You overcommit and your strike slides off; the beast's grin widens.",
            "You swing wide; the monster slips out of reach and hisses like cold wind.",
            "Your blow finds only air — something unseen laughs from the rafters.",
            "Your blow finds only air — something unseen laughs from the rafters.",
            "You misjudge its reach and the tip of your weapon whistles past nothing.",
            "The creature ducks as if it expected your move; you taste dust and regret.",
            "Your footing betrays you and the blow stings nothing but wind.",
            "A shadowed hand seems to guide your weapon away; luck, or something else, spares you.",
            "Your strike clips empty air; for a heartbeat you feel foolish and fortunate."            
        ]

        monster_hit_flavor = [
            "A savage blow slams into you, cold fire blooming under the skin.",
            "The beast's claw rakes across your flesh, teeth like knives looking to finish the job.",
            "It lunges and connects with brutal force; the world tilts and smells of iron.",
            "A vicious strike rattles your bones and leaves a ringing in your ears.",
            "A raw, animal swipe bites into you, leaving a hot sting that lingers.",
            "A brutal arc of talon finds you; your breath fogs as pain blooms.",
            "Bone meets bone in a jolt that tastes like old iron and lost resolve.",
            "The attack tears clothing and flesh alike; you stagger with something gone.",
            "A grinding strike crushes breath and thought alike; the world simplifies to pain.",
            "The monster's limb smashes home; stars bloom behind your eyes and you sway."            
        ]
        monster_crit_flavor = [
            "A bone-crushing hit! Pain explodes across your body as breath slips away.",
            "The monster finds a weakness and lands a brutal strike that reorders your senses.",
            "A devastating blow sends you reeling; stars and shadows dance together.",
            "A monstrous strike rends your defenses; you taste dust and old regrets.",
            "A lethal arc breaks ribs and resolve; you feel your strength unraveling.",
            "The blow drives you to your knees; the world narrows to a single, hot point.",
            "A grievous strike rearranges your senses; you hear distant things as if through water.",
            "It lands with catastrophic force; you wish the ground would swallow you faster.",
            "A crippling hit steals motion and steals breath; the night rushes in cold and precise."            
        ]
        monster_miss_flavor = [
            "You nimbly avoid the monster's strike, feeling the chill of almost-death pass.",
            "The monster overreaches and misses, its momentum betraying it.",
            "You duck and the attack slashes past; a shiver runs down your spine.",
            "A near miss; the air where it struck smells faintly of rot.",
            "Its claws rake only curtain and shadow; you blink and count your blessings.",
            "The beast's jaw snaps shut on empty space; it huffs and repositions with animal grace.",
            "You sidestep like a practiced dancer; the attack eats only lantern light.",
            "The strike collapses into the cobbles with a hollow thunk; you feel the world tilt with relief.",
            "It swings at ghosts and catches nothing but cold air; for once, fortune favors you."            
        ]

        victory_flavor = [
            "The creature collapses, its life leaving it in a ragged sigh; the air smells faintly of victory and dust.",
            "With a final cry, the monster falls and the night grows quieter yet somehow hungrier.",
            "You stand victorious as the beast crumples at your feet, a small triumph against the dark.",
            "The last of its strength fades; you have prevailed, though the cost is written on your bones.",
            "Silence follows the death; even the rats seem to bow as the thing dies.",
            "You breathe and the world seems to obey for a moment; victory tastes faint and iron-rich.",
            "Limbs slacken and the creature's eyes dim; you feel an old, small pride like a light.",
            "Blood soaks the cobbles and your hands tremble, but the night is a little quieter.",
            "The beast unravels like poor stitching; you stand amid the loose threads and call it done.",
            "A hush falls and then the city exhales; the alley seems to respect you, briefly."            
        ]
        defeat_flavor = [
            "Darkness closes around you as you fall to the dirt; the world narrows to a single, cold point.",
            "You collapse, breath shallow and vision blurred; the hunt has turned on you at last.",
            "The monster stands over you as your strength ebbs away, its shadow swallowing the light.",
            "Pain and cold take you; this hunt ends in failure and the ground drinks your warmth.",
            "Your hands tremble and the lamp guttering in the throat of night seems to wink out.",
            "The world narrows until sound is a long way off; you taste iron and regret.",
            "Limbs fail and the sky tilts; the last thing you see is the monster's slow, terrible silhouette.",
            "The night folds over you like a heavy cloth; your breath fogs and fails to warm it.",
            "You lie beneath the creature's silent decree; the cobbles remember your foolishness.",
            "The lamp gutter fades and the darkness is patient; your heartbeat slows into the earth."            
        ]
        
        def choose_player_hit_text(dmg: int, crit: bool, monster: dict) -> str:
            if dmg <= 0:
                return random.choice(player_miss_flavor)
            if crit:
                return random.choice(player_crit_flavor)
            return random.choice(player_hit_flavor)

        def choose_monster_hit_text(dmg: int, crit_like: bool) -> str:
            if dmg == 0:
                return random.choice(monster_miss_flavor)
            if crit_like:
                return random.choice(monster_crit_flavor)
            return random.choice(monster_hit_flavor)

        player_hp = profile.get("hp", profile.get("max_hp", 100))
        player_max = profile.get("max_hp", 100)
        
        # Apply player HP buffs/debuffs from world event
        event = getattr(self, "current_event", None)
        if event:
            hp_mult = self.EVENT_EFFECTS.get(event["time"], {}).get("player_hp", 1.0)
            hp_mult *= self.EVENT_EFFECTS.get(event["weather"], {}).get("player_hp", 1.0)
            player_max = int(player_max * hp_mult)
            # scale current HP proportionally
            player_hp = min(int(player_hp * hp_mult), player_max)        

        # include selected stage in the log header for clarity
        log_lines.append(f"A wild **{monster['name']}** appears (HP: {monster['hp']})! — {stage_name}")
        event = getattr(self, "current_event", None)
        if event:
            log_lines.append(
                f"🌍 Current world state: {event['time']} • {event['weather']} (affecting HP and damage!)"
            )

        round_count = 0
        while player_hp > 0 and monster["hp"] > 0 and round_count < 100:
            round_count += 1
            p_dmg, was_crit = self._player_attack(profile, monster)
            monster["hp"] = max(0, monster["hp"] - p_dmg)
            crit_note = " 💥" if was_crit and p_dmg > 0 else ""
            hit_text = choose_player_hit_text(p_dmg, was_crit, monster)
            log_lines.append(f"You strike the **{monster['name']}** for **{p_dmg}** damage{crit_note}. {hit_text} (Enemy {monster['hp']}/{monster['max_hp']})")
            if monster["hp"] == 0:
                break

            m_dmg = self._monster_attack(profile, monster)
            player_hp = max(0, player_hp - m_dmg)
            crit_like = False
            try:
                maxd = int(monster.get("max_damage", 0) or 10)
            except Exception:
                maxd = 10
            if m_dmg >= max(1, int(maxd * 0.8)):
                crit_like = True
            mon_text = choose_monster_hit_text(m_dmg, crit_like)
            if m_dmg == 0:
                log_lines.append(f"The **{monster['name']}** attacks but you evade it. {mon_text}")
            else:
                log_lines.append(f"The **{monster['name']}** hits you for **{m_dmg}** damage. {mon_text} (You {player_hp}/{player_max})")
            if player_hp == 0:
                break

        # Outcome processing (same as original)
        found_items: List[str] = []
        xp_gain: int = 0
        hearts_awarded: int = 0

        if monster["hp"] == 0:
            weapon = self._get_equipment(profile.get("weapon"))
            xp_gain = int(monster.get("xp_reward", 0) * float(weapon.get("xp_mod", 1.0)))
            hearts_awarded = extract_heart_reward(monster.get("heart_reward", 0))
            profile["xp"] = profile.get("xp", 0) + xp_gain
            drops = monster_def.get("drops", [])
            found_items = []
            for drop in drops:
                if random.random() <= float(drop.get("drop_chance", 0)):
                    iid = drop["item_id"]
                    items = profile.setdefault("items", {})
                    items[iid] = items.get(iid, 0) + 1
                    found_items.append(iid)
            if hearts_awarded:
                profile["hearts"] = profile.get("hearts", 0) + hearts_awarded
                log_lines.append(f"You gained **{xp_gain} XP** and **{hearts_awarded} Heart{'s' if hearts_awarded != 1 else ''}**!")
            else:
                log_lines.append(f"You gained **{xp_gain} XP**!")
            if found_items:
                names = []
                for iid in found_items:
                    meta = next((it for it in self.items if it.get("id") == iid), None)
                    if not meta:
                        meta = next((e for e in self.equipment if e.get("id") == iid), None)
                    display_name = meta.get("name", iid) if meta else iid
                    names.append(display_name)
                log_lines.append("You found: " + ", ".join(f"**{n}**" for n in names))
            log_lines.append(random.choice(victory_flavor) if 'victory_flavor' in locals() else "You stand victorious.")
            color = discord.Color.random()
        else:
            flavor = random.choice(defeat_flavor) if 'defeat_flavor' in locals() else "You were defeated."
            log_lines.append(flavor)
            log_lines.append("You were defeated and collapse to the ground.")
            player_hp = 0
            profile["hp"] = 0
            color = discord.Color.random()

        old_level = int(profile.get("level", 1))
        new_level = self._level_from_xp(profile.get("xp", 0))
        if new_level > old_level:
            levels_gained = new_level - old_level
            profile["level"] = new_level
            profile["max_hp"] = profile.get("max_hp", 100) + 5 * levels_gained
            player_hp = min(player_hp + 10 * levels_gained, profile["max_hp"])
            log_lines.append(f"You reached level {new_level}! Max HP +{5 * levels_gained}.")

        profile["hp"] = player_hp
        profiles[uid] = profile
        await self._save_profiles(profiles)

        victory = monster["hp"] == 0
        title = f"You {'defeated' if victory else 'were defeated by'} {monster['name']}"
        embed_color = discord.Color.green() if victory else discord.Color.dark_red()
        player_bar = self._health_bar(profile.get("hp", 0), profile.get("max_hp", 100), length=12)
        monster_bar = self._health_bar(monster["hp"], monster["max_hp"], length=12)
        recent_log = log_lines[-8:] if len(log_lines) > 8 else log_lines
        combat_text = "\n".join(recent_log)
        embed = discord.Embed(title=title, description=f"Round(s) fought: **{round_count}**", color=embed_color)
        try:
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
        except Exception:
            embed.set_author(name=ctx.author.display_name)
        if monster.get("image"):
            embed.set_thumbnail(url=monster.get("image"))
        embed.add_field(
            name="Player",
            value=(
                f"**HP** {profile.get('hp',0)}/{profile.get('max_hp',0)}\n"
                f"{player_bar}\n"
                f"**Lvl** {profile.get('level',1)} • **XP** {profile.get('xp',0)}"
            ),
            inline=True
        )
        embed.add_field(
            name=monster["name"],
            value=(
                f"**HP** {monster['hp']}/{monster['max_hp']}\n"
                f"{monster_bar}\n"
                f"**XP Reward** {monster.get('xp_reward',0)}"
            ),
            inline=True
        )
        embed.add_field(name="Combat Log", value=combat_text or "No actions recorded.", inline=False)
        reward_lines = []
        weapon = self._get_equipment(profile.get("weapon"))
        xp_gain_calc = int(monster.get("xp_reward", 0) * float(weapon.get("xp_mod", 1.0))) if weapon else int(monster.get("xp_reward", 0))
        hearts_awarded_calc = extract_heart_reward(monster.get("heart_reward", 0))
        if victory:
            reward_lines.append(f"**XP**: +{xp_gain_calc}")
            if hearts_awarded:
                reward_lines.append(f"**Hearts**: +{hearts_awarded}")
            if found_items:
                names = []
                for iid in found_items:
                    meta = next((it for it in self.items if it.get("id") == iid), None)
                    if not meta:
                        meta = next((e for e in self.equipment if e.get("id") == iid), None)
                    display_name = meta.get("name", iid) if meta else iid
                    names.append(display_name)
                reward_lines.append("**Found**: " + ", ".join(names))
        else:
            reward_lines.append("None")
        embed.add_field(name="Rewards", value="\n".join(reward_lines) if reward_lines else "None", inline=False)
        event = getattr(self, "current_event", None)
        if event:
            embed.set_footer(
                text=f"World Event: {event['time']} • {event['weather']} • Rounds: {round_count}"
            )
        else:
            embed.set_footer(text=f"Rounds: {round_count}")
        await ctx.send(embed=embed)

    @commands.cooldown(1, 1200, commands.BucketType.user)
    @vania.command(name="pray")
    async def pray(self, ctx: commands.Context):
        """
        Flavored pray command: receive 1–5 Hearts with a short prayer text and rich embed.
        """
        flavor_lines = [
            "You kneel and whisper to the old gods; the altar answers with a cold, patient wind.",
            "A warm gust brushes your face as light spills from the altar, as if the past exhales.",
            "You offer a quiet plea; a faint chime replies from the stones, echoing old bargains.",
            "You close your eyes and, for a moment, feel watched by something both kind and terrible.",
            "Candles tremble when your prayer ends; the air tastes faintly of iron and comfort.",
            "The altar exhales a sigh of relief; a soft warmth loosens the knots in your chest.",
            "A bell rings somewhere deep beneath the chapel; the sound settles into your bones.",
            "An image shivers in the candlelight and a presence leans close as if to listen.",
            "A perfumed breath brushes your face; the altar's answer is small but sincere.",
            "You sense hands smoothing the edges of your day; some small thing is made right.",
            "A faint chorus hums under your feet, and with it comes the sense that debts shift."            
        ]

        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid, self._default_profile())

        gained = random.randint(1, 5)
        profile["hearts"] = profile.get("hearts", 0) + gained

        profiles[uid] = profile
        await self._save_profiles(profiles)

        # Build rich embed
        embed = discord.Embed(
            title="You prayed at the altar",
            description=random.choice(flavor_lines),
            color=discord.Color.gold()
        )
        try:
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
        except Exception:
            embed.set_author(name=ctx.author.display_name)

        embed.add_field(name="Hearts Gained", value=f"**{gained}**", inline=True)
        embed.add_field(name="Total Hearts", value=str(profile.get("hearts", 0)), inline=True)
        embed.set_footer(text="May these Hearts keep your will unbroken. • Try `vania heal` to spend them.")
        await ctx.send(embed=embed)

    @vania.command(name="stats")
    async def stats(self, ctx: commands.Context):
        """View your hunter’s level, XP, hearts, equipped gear and slots (rich embed)."""
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid, None)
        if not profile:
            # create a default profile and persist it so stats always shows something
            profile = self._default_profile()
            profiles[uid] = profile
            await self._save_profiles(profiles)

        xp = int(profile.get("xp", 0))
        # derive level from total XP using the new curve to keep UI consistent
        level = self._level_from_xp(xp)
        skills = profile.get("skills", {})
        hearts = int(profile.get("hearts", 0))
        hp = int(profile.get("hp", 0))
        max_hp = int(profile.get("max_hp", 100))

        # small helpers
        def eqname(slot):
            return self._get_equipment(profile.get(slot)).get("name", "None") if profile.get(slot) else "None"

        def eq_icon(slot):
            return self._get_equipment(profile.get(slot)).get("image") if profile.get(slot) else None

        # Build embed
        embed = discord.Embed(title=f"{ctx.author.display_name}'s Hunter Sheet", color=discord.Color.blurple())
        try:
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
        except Exception:
            embed.set_author(name=ctx.author.display_name)

        # Top summary (HP bar, level, XP, Hearts)
        hp_bar = self._health_bar(hp, max_hp, length=18)
        percent = int(hp / max_hp * 100) if max_hp > 0 else 0
        embed.add_field(name="Status", value=f"**HP** {hp}/{max_hp} · {hp_bar} · **{percent}%**\n**Level** {level} · **XP** {xp}\n**Hearts** {hearts}", inline=False)

        # Equipment snapshot: show weapon + all wearable slots 
        weapon_name = eqname("weapon")
        offhand_name = eqname("offhand")
        body_name = eqname("body")
        head_name = eqname("head")
        legs_name = eqname("legs")
        arms_name = eqname("arms")
        cloak_name = eqname("cloak")
        accessories = f"{eqname('accessory1')}, {eqname('accessory2')}"

        embed.add_field(name="Weapon", value=weapon_name, inline=True)
        embed.add_field(name="Offhand", value=offhand_name, inline=True)
        embed.add_field(name="Body", value=body_name, inline=True)

        embed.add_field(name="Head", value=head_name, inline=True)
        embed.add_field(name="Legs", value=legs_name, inline=True)
        embed.add_field(name="Arms", value=arms_name, inline=True)

        embed.add_field(name="Cloak", value=cloak_name, inline=True)
        embed.add_field(name="Accessories", value=accessories, inline=True)

        # Optional thumbnail: weapon image if available, else first equipped item image
        thumb = eq_icon("weapon") or eq_icon("body") or eq_icon("head")
        if thumb:
            embed.set_thumbnail(url=thumb)

        # Skills block (compact, sorted by level desc) and truncated to avoid embed overflow
        if skills:
            skill_items = sorted(skills.items(), key=lambda kv: (-int(kv[1]), kv[0]))
            skill_items = skill_items[:12]  # keep list reasonable to avoid embed overflow
            skill_lines = [f"**{name}** Lv {lvl}" for name, lvl in skill_items]
            if len(skills) > 12:
                skill_lines.append(f"...and {len(skills)-12} more")
            embed.add_field(name="Skills", value="\n".join(skill_lines), inline=False)

        # Inventory quick counts (relics, consumables, items)
        relic_count = len(profile.get("relics", []))
        consumable_count = sum(int(q) for q in profile.get("consumables", {}).values())
        item_count = sum(int(q) for q in profile.get("items", {}).values())
        embed.add_field(name="Inventory", value=f"Relics: **{relic_count}** · Consumables: **{consumable_count}** · Items: **{item_count}**", inline=False)

        # Footer with hints and safe send fallback
        embed.set_footer(text="Use `vania inventory` to manage gear and `vania heal` to spend Hearts.")
        try:
            await ctx.send(embed=embed)
        except Exception as exc:
            # fallback: send a short text summary and log the exception to console
            try:
                await ctx.send(f"{ctx.author.display_name}'s Profile — Level {level}, XP {xp}, Hearts {hearts}, HP {hp}/{max_hp}")
            except Exception:
                pass
            print(f"[vania.stats] error sending embed for {uid}: {exc}")
            
    @vania.command(name="channel")
    @commands.has_permissions(manage_guild=True)
    async def set_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel where day/night & weather events will be posted every 3 hours."""
        settings = self._load_settings()
        settings[str(ctx.guild.id)] = {"channel_id": channel.id}
        await self._save_settings(settings)
        await ctx.send(f"✅ Updates will now post in {channel.mention} every 3 hours. Posting an initial world update now...")

        # Immediately post an event to the newly configured channel
        try:
            # best-effort: get channel object and post a styled event
            ch = self.bot.get_channel(channel.id)
            if ch:
                await self._post_event_to_channel(ch)
        except Exception:
            # non-fatal; the background loop will continue posting on schedule
            pass         

    @vania.command(name="train")
    async def train(self, ctx: commands.Context, skill: str):
        """
        Spend XP to unlock or upgrade a skill.
        Skills must exist in skills.json to be trained.
        """
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid)
        if not profile:
            return await ctx.send("Start hunting first with `vania hunt`.")

        if skill not in self.skills_def:
            valid = ", ".join(sorted(self.skills_def.keys()))
            return await ctx.send(f"Unknown skill `{skill}`. Valid skills: {valid}")

        skills = profile.setdefault("skills", {})
        current = skills.get(skill, 0)
        defined_cost = self.skills_def.get(skill, {}).get("base_cost")
        cost = int(defined_cost) if defined_cost is not None else (current + 1) * 50

        if profile["xp"] < cost:
            return await ctx.send(f"You need {cost} XP to train {skill} (you have {profile['xp']} XP).")

        profile["xp"] -= cost
        skills[skill] = current + 1
        profiles[uid] = profile
        await self._save_profiles(profiles)

        embed = discord.Embed(title="Training Complete", description=f"{skill} upgraded to level {skills[skill]}!", color=discord.Color.random())
        embed.add_field(name="XP Remaining", value=str(profile["xp"]))
        await ctx.send(embed=embed)

    # ----------------- Inventory, Equip (integrated), Heal Implementation -----------------
    @vania.command(name="inventory")
    async def inventory(self, ctx: commands.Context):
        """List items, relics, and consumables with pagination and quick-use and equip buttons."""
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid, self._default_profile())

        inv = self._gather_inventory(profile)
        pages = self._paginate_inventory(inv)
        view = InventoryView(self, ctx, pages)

        # Build richer inventory embed
        hearts = profile.get("hearts", 0)
        relic_count = len(profile.get("relics", []))
        consumable_count = sum(int(q) for q in profile.get("consumables", {}).values())
        item_count = sum(int(q) for q in profile.get("items", {}).values())

        embed = discord.Embed(title=f"{ctx.author.display_name}'s Inventory", color=discord.Color.dark_teal())
        try:
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
        except Exception:
            embed.set_author(name=ctx.author.display_name)

        # Top summary
        embed.add_field(
            name="Summary",
            value=f"**Hearts**: {hearts} · **Relics**: {relic_count} · **Consumables**: {consumable_count} · **Items**: {item_count}",
            inline=False,
        )

        # Show page 1 content in a prettier table-like list
        page = pages[0] if pages else []
        if not page:
            embed.add_field(name="Contents", value="Inventory empty.", inline=False)
        else:
            lines = []
            for it in page:
                iid = it.get("id", "unknown")
                qty = it.get("qty", 1)
                typ = it.get("type", "misc")
                # show a small icon hint for type
                icon = "🔹" if typ in ("weapon","offhand","head","body","legs","arms","cloak","accessory") else ("🧴" if typ=="consumable" else "✦")

                # resolve display name from items.json or equipment.json
                meta = next((m for m in self.items if m.get("id") == iid), None)
                if not meta:
                    meta = next((e for e in self.equipment if e.get("id") == iid), None)
                name = meta.get("name", iid) if meta else iid

                # look up equipment stats if this is equippable
                stat_text = ""
                if meta and meta.get("category") == "weapon":
                    stat_text = f" [{meta.get('min_damage')}-{meta.get('max_damage')} dmg, crit {int(meta.get('crit_chance',0)*100)}%]"
                elif meta and meta.get("category") == "armor":
                    stat_text = f" [DEF {meta.get('defense',0)}]"

                lines.append(f"{icon} **{name}**  x{qty} — {typ}{stat_text}")
            embed.add_field(name=f"Page 1/{len(pages)}", value="\n".join(lines), inline=False)

        # Footer / hint and attach view
        embed.set_footer(text="Use the buttons to page, Equip items or Use consumables.")
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.update_message()

    def _gather_inventory(self, profile: dict) -> List[dict]:
        """
        Convert stored profile fields into a flat list of items suitable for display.
        Expected profile keys: 'relics' (list), 'consumables' (dict id->qty), 'items' (dict id->qty)
        Returns list of dicts with keys: id, name, qty, type.
        """
        out: List[dict] = []
        for relic in profile.get("relics", []):
            out.append({"id": str(relic), "name": str(relic), "qty": 1, "type": "relic"})
        for cid, qty in profile.get("consumables", {}).items():
            meta = next((it for it in self.items if it.get("id") == cid), {})
            name = meta.get("name", cid)
            out.append({"id": cid, "name": name, "qty": int(qty), "type": "consumable"})
        for iid, qty in profile.get("items", {}).items():
            meta = next((it for it in self.items if it.get("id") == iid), {})
            name = meta.get("name", iid)
            equip_meta = next((e for e in self.equipment if e.get("id") == iid), None)
            it_type = "item"
            if equip_meta:
                # map equipment slot to inventory type for display
                slot = equip_meta.get("slot") or equip_meta.get("category")
                it_type = slot if slot else equip_meta.get("category", "item")
            out.append({"id": iid, "name": name, "qty": int(qty), "type": it_type})
        return out

    def _paginate_inventory(self, inventory: List[dict], per_page: int = 6) -> List[List[dict]]:
        pages: List[List[dict]] = []
        for i in range(0, len(inventory), per_page):
            pages.append(inventory[i : i + per_page])
        if not pages:
            pages.append([])
        return pages

    # internal performer for use (kept for reuse by InventoryView)
    async def _do_use_item(self, ctx_or_interaction, uid: str, item_id: str, target: Optional[discord.Member]):
        """
        ctx_or_interaction may be either Context or Interaction.
        The function performs validations, applies effects, updates profile, and sends a reply.
        """
        is_interaction = hasattr(ctx_or_interaction, "response") and isinstance(ctx_or_interaction, discord.Interaction)

        profiles = self._load_profiles()
        profile = profiles.get(uid)
        if not profile:
            msg = "No profile found. Start hunting with `vania hunt`."
            if is_interaction:
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        consumables = profile.get("consumables", {})
        qty = int(consumables.get(item_id, 0))
        if qty <= 0:
            msg = f"You don't have any `{item_id}` to use."
            if is_interaction:
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        meta = next((it for it in self.items if it.get("id") == item_id), {})
        kind = meta.get("effect", "heal")
        name = meta.get("name", item_id)

        target_uid = uid
        target_member = None

        tprofile = profiles.get(target_uid, self._default_profile())

        result_lines = []
        if kind == "heal":
            amount = int(meta.get("value", 25))
            old = tprofile.get("hp", tprofile.get("max_hp", 100))
            tprofile["hp"] = min(tprofile.get("max_hp", 100), old + amount)
            target_name = "you"
            result_lines.append(f"{name} healed {amount} HP for {target_name}.")
        elif kind == "revive":
            if tprofile.get("hp", 0) > 0:
                result_lines.append("Target is not down; revive not needed.")
            else:
                tprofile["hp"] = tprofile.get("max_hp", 100) // 2
                target_name = "you"
                result_lines.append(f"{name} revived {target_name} to {tprofile['hp']} HP.")
        elif kind == "buff":
            buff_name = meta.get("buff_name", "power")
            duration = int(meta.get("duration", 300)) if meta.get("duration") else 300
            tprofile.setdefault("temp_buffs", []).append({"name": buff_name, "expires_in": duration})
            result_lines.append(f"{name} granted {buff_name} for {duration} seconds.")
        else:
            result_lines.append(f"{name} used (no effect implemented).")

        consumables[item_id] = max(0, qty - 1)
        if consumables[item_id] == 0:
            consumables.pop(item_id, None)
        profile["consumables"] = consumables

        profiles[uid] = profile
        profiles[target_uid] = tprofile

        await self._save_profiles(profiles)

        msg = "\n".join(result_lines)
        if is_interaction:
            await ctx_or_interaction.response.send_message(msg)
        else:
            await ctx_or_interaction.send(msg)

    # internal equip performer (used by InventoryView Equip button)
    async def _do_equip_item(self, ctx_or_interaction, uid: str, item_id: str):
        is_interaction = hasattr(ctx_or_interaction, "response") and isinstance(ctx_or_interaction, discord.Interaction)
        profiles = self._load_profiles()
        profile = profiles.get(uid)
        if not profile:
            msg = "No profile found. Start hunting with `vania hunt`."
            if is_interaction:
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        equip_meta = next((e for e in self.equipment if e.get("id") == item_id), None)
        if not equip_meta:
            msg = f"`{item_id}` is not equippable."
            if is_interaction:
                await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return

        # Determine slot for this equipment
        slot = equip_meta.get("slot") or equip_meta.get("category")
        chosen_slot = None
        if slot == "accessory":
            if not profile.get("accessory1"):
                chosen_slot = "accessory1"
            elif not profile.get("accessory2"):
                chosen_slot = "accessory2"
            else:
                chosen_slot = "accessory1"  # default replace; can be improved to prompt
        else:
            # Normalize names to allowed slot set
            mapping = {
                "weapon": "weapon",
                "offhand": "offhand",
                "head": "head",
                "body": "body",
                "legs": "legs",
                "arms": "arms",
                "cloak": "cloak",
            }
            chosen_slot = mapping.get(slot, None)
            if chosen_slot is None:
                chosen_slot = "weapon" if equip_meta.get("category") == "weapon" else "body"

        if chosen_slot not in ("weapon","offhand","head","body","legs","arms","cloak","accessory1","accessory2"):
            chosen_slot = "weapon" if equip_meta.get("category") == "weapon" else "body"

        # If there's an item currently equipped in that slot, move it back to items inventory
        prev = profile.get(chosen_slot)
        if prev:
            items = profile.setdefault("items", {})
            items[prev] = items.get(prev, 0) + 1
            profile["items"] = items

        # Remove one unit of the item from inventory if it exists there
        items = profile.setdefault("items", {})
        if items.get(item_id, 0) > 0:
            items[item_id] = items[item_id] - 1
            if items[item_id] <= 0:
                items.pop(item_id, None)
            profile["items"] = items
        else:
            # allow equip even if not in inventory (admin granted)
            pass

        # Equip the new item
        profile[chosen_slot] = item_id
        profiles[uid] = profile
        await self._save_profiles(profiles)

        # Compute combined stats for report
        weapon = self._get_equipment(profile.get("weapon"))
        body = self._get_equipment(profile.get("body"))
        offhand = self._get_equipment(profile.get("offhand"))
        # total defense from main defensive slots
        defense = 0
        for s in ("body", "offhand", "head", "arms", "legs", "cloak"):
            defense += int(self._get_equipment(profile.get(s)).get("defense", 0))

        xp_mod = float(weapon.get("xp_mod", 1.0)) if weapon else 1.0
        dmg_mod = float(weapon.get("damage_mod", 1.0)) if weapon else 1.0

        msg = f"You equipped **{equip_meta.get('name', item_id)}** into **{chosen_slot}**. (XP×{xp_mod}, DMG×{dmg_mod}, DEF {defense})"
        if is_interaction:
            await ctx_or_interaction.response.send_message(msg)
        else:
            await ctx_or_interaction.send(msg)

    @commands.cooldown(1, 60, commands.BucketType.user)
    @vania.command(name="heal")
    async def heal(self, ctx: commands.Context):
        """
        Flavored heal: spend Hearts to heal. Uses full-heal logic when possible and shows a rich embed with flavor.
        """
        heal_flavor = [
            "You press the Heart to your chest; warmth spreads like a slow sunrise and old aches loosen.",
            "A soft gold glow surrounds you as the Hearts' power knits flesh and spirit into brittle strength.",
            "Memory and muscle mend beneath the gentle pulse; scars smooth and breath steadies.",
            "Energy floods your limbs; the wound sews itself closed with a whisper and the air smells faintly of incense.",
            "The Heart thrums in your palm; light travels up your veins and the cold recedes from your bones.",
            "A steady hum runs through your bones; pain loosens its grip and you stand more whole.",
            "The warmth settles like a blanket; small cracks knit and the world stops wobbling.",
            "Tension unwinds along your spine as if invisible hands stitch you back together.",
            "A soft light pools into wounds and sips away the worst of the night's sharpness.",
            "You feel the past stitches close; breathing becomes easier and hope a quiet companion."            
        ]
        low_heal_flavor = [
            "The Hearts offer a small comfort, sealing the worst of your wounds and sharpening resolve.",
            "A faint pulse returns to you; not whole, but steady enough to fight another hour.",
            "A shard of warmth finds you and stitches a line of courage into aching limbs.",
            "You feel a small tide of warmth; it does not fix all, but it keeps you moving.",
            "A dull glow settles in your chest and dulls the edge of pain for now.",
            "The wound binds enough for breath to come easier; it is not perfect, but sufficient.",
            "A trickle of light repairs a few small tears; your steps return, imperfect but yours.",
            "A modest warmth mends what it can; the rest will need more time or sacrifice."            
        ]

        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid)
        if not profile:
            return await ctx.send("No profile found. Start hunting with `vania hunt`.")

        hearts = int(profile.get("hearts", 0))
        if hearts <= 0:
            return await ctx.send("You have no Hearts to spend for healing.")

        per_heart = max(10, profile.get("max_hp", 100) // 6)
        current_hp = int(profile.get("hp", 0))
        max_hp = int(profile.get("max_hp", 100))
        missing = max_hp - current_hp
        if missing <= 0:
            return await ctx.send("You are already at full HP.")

        hearts_needed = (missing + per_heart - 1) // per_heart

        if hearts >= hearts_needed:
            hearts_spent = hearts_needed
            healed = missing
            profile["hp"] = max_hp
            profile["hearts"] = hearts - hearts_spent
            flavor = random.choice(heal_flavor)
            title = "Fully Healed"
            color = discord.Color.green()
        else:
            hearts_spent = hearts
            healed = min(missing, per_heart * hearts_spent)
            profile["hp"] = min(max_hp, current_hp + healed)
            profile["hearts"] = 0
            flavor = random.choice(low_heal_flavor)
            title = "Partially Healed"
            color = discord.Color.orange()

        profiles[uid] = profile
        await self._save_profiles(profiles)

        embed = discord.Embed(title=title, description=flavor, color=color)
        try:
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
        except Exception:
            embed.set_author(name=ctx.author.display_name)

        embed.add_field(name="Hearts Spent", value=f"**{hearts_spent}**", inline=True)
        embed.add_field(name="HP Healed", value=f"**{healed}**", inline=True)
        embed.add_field(name="Current HP", value=f"{profile['hp']}/{max_hp}", inline=True)
        embed.add_field(name="Hearts Remaining", value=str(profile.get("hearts", 0)), inline=True)
        embed.set_footer(text="Hearts are precious. Use them wisely or save them for revives.")
        await ctx.send(embed=embed)

    @vania.command(name="resetcool")
    @commands.has_permissions(manage_guild=True)
    async def vania_resetcool(self, ctx: commands.Context, member: discord.Member, *, command_name: str = "all"):
        """
        Admin: reset cooldowns for a user for Vania cog commands only.
        Usage:
          - vania resetcool @User            -> resets all vania command cooldowns for that user
          - vania resetcool @User command   -> resets cooldown for a single vania command (by full or partial name)
        Requires Manage Guild permission.
        """
        if member is None:
            return await ctx.send("Specify a user to reset cooldowns for.")

        orig_author = ctx.author
        try:
            # Temporarily impersonate the target user on the context for reset_cooldown calls
            ctx.author = member

            reset_list: List[str] = []
            failed_list: List[str] = []

            # Gather all runtime Command objects that belong to this cog (includes group subcommands).
            # Flatten group children and deduplicate by qualified_name.
            seen = set()
            cog_cmds = []
            for c in (c for c in self.bot.commands if getattr(c, "cog", None) is self):
                if c.qualified_name not in seen:
                    seen.add(c.qualified_name)
                    cog_cmds.append(c)
                # include subcommands for Group/GroupCog commands
                try:
                    children = list(getattr(c, "all_commands", {}).values()) or []
                except Exception:
                    children = []
                for ch in children:
                    if getattr(ch, "cog", None) is self and ch.qualified_name not in seen:
                        seen.add(ch.qualified_name)
                        cog_cmds.append(ch)

            if command_name.lower() in ("all", "*"):
                # reset for every command in this cog
                for cmd in cog_cmds:
                    try:
                        cmd.reset_cooldown(ctx)
                        reset_list.append(cmd.qualified_name)
                    except Exception:
                        failed_list.append(getattr(cmd, "qualified_name", str(cmd)))
            else:
                # try to resolve a specific command among this cog's commands (partial match supported)
                target = None
                # exact qualified name or name match first
                for c in cog_cmds:
                    if c.qualified_name == command_name or c.name == command_name:
                        target = c
                        break
                # partial match by start
                if target is None:
                    candidates = [c for c in cog_cmds if c.name.startswith(command_name) or c.qualified_name.startswith(command_name)]
                    if len(candidates) == 1:
                        target = candidates[0]
                    elif len(candidates) > 1:
                        names = ", ".join(c.qualified_name for c in candidates)
                        return await ctx.send(f"Multiple vania commands match `{command_name}`: {names}. Use the full command name.")
                    else:
                        return await ctx.send(f"No vania command found matching `{command_name}`.")

                try:
                    target.reset_cooldown(ctx)
                    reset_list.append(target.qualified_name)
                except Exception:
                    failed_list.append(target.qualified_name)

            # Build a single description string and guard embed size
            desc_lines: List[str] = []
            if reset_list:
                desc_lines.append(f"Reset cooldowns for: {', '.join(reset_list)}")
            if failed_list:
                desc_lines.append(f"Failed to reset: {', '.join(failed_list)}")
            if not desc_lines:
                desc_lines.append("No cooldowns were reset.")
            full_desc = "\n".join(desc_lines)

            if len(full_desc) <= 1800:
                embed = discord.Embed(title="Vania Cooldowns Reset", description=full_desc, color=discord.Color.blurple())
                try:
                    embed.set_author(name=member.display_name, icon_url=getattr(member.avatar, "url", None))
                except Exception:
                    embed.set_author(name=member.display_name)
                await ctx.send(embed=embed)
            else:
                # fallback to text splits if result is huge
                header = f"Vania cooldowns reset for {member.display_name}"
                try:
                    header_embed = discord.Embed(title=header, description="Output too large for a single embed; sending as text.", color=discord.Color.blurple())
                    header_embed.set_author(name=member.display_name)
                    await ctx.send(embed=header_embed)
                except Exception:
                    await ctx.send(header)
                chunk_size = 1900
                start = 0
                while start < len(full_desc):
                    chunk = full_desc[start : start + chunk_size]
                    await ctx.send(f"```txt\n{chunk}\n```")
                    start += chunk_size
        finally:
            # restore original context author
            ctx.author = orig_author
            
    # ----------------- Admin: reset player/server progress -----------------
    @vania.command(name="resetprogress")
    @commands.has_permissions(manage_guild=True)
    async def reset_progress(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """
        Admin command to reset progress.
        - `vania resetprogress @User` resets that user's profile (after confirmation).
        - `vania resetprogress` resets all saved profiles (server-wide) (after confirmation).
        """
        # determine target
        if member:
            target_text = f"user **{member.display_name}** (ID {member.id})"
            scope = "user"
            target_id = str(member.id)
        else:
            target_text = "the entire server (all saved profiles)"
            scope = "server"
            target_id = None

        # Confirmation view
        class _ConfirmResetView(discord.ui.View):
            def __init__(self, invoker_id: int, timeout: int = 60):
                super().__init__(timeout=timeout)
                self.result: Optional[bool] = None
                self.invoker_id = invoker_id

            @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, custom_id="vania_reset_confirm")
            async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != self.invoker_id:
                    await interaction.response.send_message("Only the command invoker can confirm this action.", ephemeral=True)
                    return
                if not interaction.user.guild_permissions.manage_guild:
                    await interaction.response.send_message("You lack Manage Guild to perform this.", ephemeral=True)
                    return
                self.result = True
                for child in list(self.children):
                    child.disabled = True
                await interaction.response.edit_message(content="Confirmed — performing reset...", view=self)
                self.stop()

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="vania_reset_cancel")
            async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != self.invoker_id:
                    await interaction.response.send_message("Only the command invoker can cancel.", ephemeral=True)
                    return
                self.result = False
                for child in list(self.children):
                    child.disabled = True
                await interaction.response.edit_message(content="Reset cancelled.", view=self)
                self.stop()

            async def on_timeout(self):
                try:
                    for child in list(self.children):
                        child.disabled = True
                    if message:
                        await message.edit(content="Reset timed out — no changes were made.", view=self)
                except Exception:
                    pass

        prompt = (
            f"WARNING — you are about to reset progress for {target_text}.\n\n"
            "This action is irreversible. Confirm to proceed, or Cancel to abort."
        )
        view = _ConfirmResetView(ctx.author.id)
        message = await ctx.send(prompt, view=view)
        await view.wait()

        if view.result is not True:
            if view.result is False:
                await ctx.send("Reset cancelled.")
            return

        profiles = self._load_profiles()
        if scope == "user":
            if target_id in profiles:
                profiles.pop(target_id, None)
                await self._save_profiles(profiles)
                await ctx.send(f"✅ Reset progress for {member.mention} ({member.id}).")
            else:
                await ctx.send(f"No stored profile found for {member.mention} ({member.id}). Nothing to reset.")
        else:
            # server-wide reset: backup then clear
            try:
                backup_file = self.data_file.with_suffix(f".bak_{int(random.random()*1e9)}")
                backup_file.write_text(self.data_file.read_text())
            except Exception:
                pass
            profiles = {}
            await self._save_profiles(profiles)
            await ctx.send("✅ All saved profiles have been reset for this cog. A backup was created where possible.")

        print(f"[vania.reset_progress] {ctx.author} ({ctx.author.id}) reset {scope} {target_id or 'ALL'} in guild {ctx.guild.id}")         


    # ----------------- Raid commands (unchanged) -----------------
    @vania.group(name="raid", invoke_without_command=True)
    async def raid(self, ctx: commands.Context):
        """Raid commands: schedule and start boss fights."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @raid.command(name="schedule")
    @commands.admin_or_permissions(manage_guild=True)
    async def raid_schedule(self, ctx: commands.Context, boss_id: str, channel: discord.TextChannel):
        """Schedule a raid against <boss_id> in the specified channel."""
        boss = next((b for b in self.bosses if b.get("id") == boss_id), None)
        if not boss:
            return await ctx.send(f"No boss found with ID `{boss_id}`.")

        embed = discord.Embed(title=f"Raid Sign-Up: {boss['name']}", description="React with ✅ to join the raid!", color=discord.Color.random())
        embed.add_field(name="Boss HP", value=str(boss.get("hp")), inline=False)
        msg = await channel.send(embed=embed)
        await msg.add_reaction("✅")

        raids = self._load_raids()
        raids[boss_id] = {
            "channel_id": channel.id,
            "message_id": msg.id,
            "participants": []
        }
        await self._save_raids(raids)
        await ctx.send(f"Raid vs **{boss['name']}** scheduled in {channel.mention}.")

    @raid.command(name="start")
    @commands.admin_or_permissions(manage_guild=True)
    async def raid_start(self, ctx: commands.Context, boss_id: str):
        """Start the scheduled raid, resolve combat, and handle win or loss."""
        raids = self._load_raids()
        entry = raids.get(boss_id)
        if not entry:
            return await ctx.send(f"No active raid found for `{boss_id}`.")

        boss = next((b for b in self.bosses if b.get("id") == boss_id), None)
        if not boss:
            return await ctx.send(f"Boss definition for `{boss_id}` missing.")

        channel = self.bot.get_channel(entry.get("channel_id"))
        if channel is None:
            return await ctx.send("Raid channel not found.")

        msg = None
        try:
            msg = await channel.fetch_message(entry.get("message_id"))
        except Exception:
            msg = None

        participant_ids = set(entry.get("participants", []))
        if not participant_ids and msg:
            reaction = discord.utils.get(msg.reactions, emoji="✅")
            if reaction:
                users = [u async for u in reaction.users() if not u.bot]
                participant_ids = {str(u.id) for u in users}

        if not participant_ids:
            return await ctx.send("No participants joined the raid.")

        boss_max_hp = int(boss.get("hp", 1000))
        boss_hp = boss_max_hp
        reports: List[str] = []
        profiles = self._load_profiles()

        for pid in list(participant_ids):
            user_obj = self.bot.get_user(int(pid))
            name = user_obj.display_name if user_obj else f"User {pid}"
            prof = profiles.get(pid, self._default_profile())
            lvl = int(prof.get("level", 1))
            weapon = self._get_equipment(prof.get("weapon"))
            weapon_mod = float(weapon.get("damage_mod", 1.0))
            base = random.randint(20, 50)
            dmg = int(base * (1 + 0.05 * (lvl - 1)) * weapon_mod)
            boss_hp = max(0, boss_hp - dmg)
            reports.append(f"**{name}** hits for {dmg}")
            if boss_hp == 0:
                break

        bar = self._health_bar(boss_hp, boss_max_hp)
        description = "\n".join(reports)
        description += f"\n\nBoss HP: `{boss_hp}/{boss_max_hp}`\n{bar}"
        image_url = boss.get("image")

        embed = discord.Embed(title=f"Raid vs {boss['name']}", description=description, color=discord.Color.red() if boss_hp > 0 else discord.Color.random())
        if image_url:
            embed.set_image(url=image_url)

        await channel.send(embed=embed)

        if boss_hp == 0:
            profiles = self._load_profiles()
            reward_lines = []
            for pid in list(participant_ids):
                member = self.bot.get_user(int(pid))
                display = member.display_name if member else f"User {pid}"
                profile = profiles.get(pid, self._default_profile())
                xp = int(boss.get("xp_reward", 0))
                hearts = int(boss.get("heart_reward", 0))
                relic_pool = boss.get("relic_pool", [])
                relic = random.choice(relic_pool) if relic_pool else None
                profile["xp"] = profile.get("xp", 0) + xp
                profile["hearts"] = profile.get("hearts", 0) + hearts
                if relic:
                    profile["relics"] = profile.get("relics", []) + [relic]
                profiles[pid] = profile
                line = f"{display}: +{xp} XP, +{hearts} Hearts"
                if relic:
                    line += f", **{relic}**"
                reward_lines.append(line)
            await self._save_profiles(profiles)

            victory_embed = discord.Embed(title="Raid Victory!", description="\n".join(reward_lines), color=discord.Color.random())
            if image_url:
                victory_embed.set_thumbnail(url=image_url)
            await channel.send(embed=victory_embed)
        else:
            fail_embed = discord.Embed(title="Raid Failed", description=(f"The raid against **{boss['name']}** has failed. The boss still stands victorious."), color=discord.Color.random())
            if image_url:
                fail_embed.set_thumbnail(url=image_url)
            await channel.send(embed=fail_embed)

        raids.pop(boss_id, None)
        await self._save_raids(raids)


# ----------------- Inventory View (outside class) -----------------
class InventoryView(discord.ui.View):
    def __init__(self, cog: Vania, ctx: commands.Context, pages: List[List[dict]]):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.author_id = ctx.author.id
        self.pages = pages
        self.page_index = 0
        self.message: Optional[discord.Message] = None

    async def on_timeout(self):
        try:
            for child in list(self.children):
                child.disabled = True
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass

    async def update_message(self):
        page = self.pages[self.page_index]
        embed = discord.Embed(title=f"{self.ctx.author.display_name}'s Inventory", color=discord.Color.random())
        hearts = self.cog._load_profiles().get(str(self.ctx.author.id), {}).get("hearts", 0)
        embed.add_field(name="Hearts", value=str(hearts), inline=True)

        if not page:
            embed.description = "This page is empty."
        else:
            lines = []
            for item in page:
                iid = item.get("id", "unknown")
                qty = item.get("qty", 1)
                typ = item.get("type", "misc")

                meta = next((m for m in self.cog.items if m.get("id") == iid), None)
                if not meta:
                    meta = next((e for e in self.cog.equipment if e.get("id") == iid), None)
                name = meta.get("name", iid) if meta else iid

                stat_text = ""
                if meta and meta.get("category") == "weapon":
                    stat_text = f" [{meta.get('min_damage')}-{meta.get('max_damage')} dmg, crit {int(meta.get('crit_chance',0)*100)}%]"
                elif meta and meta.get("category") == "armor":
                    stat_text = f" [DEF {meta.get('defense',0)}]"

                icon = "🔹" if typ in ("weapon","offhand","head","body","legs","arms","cloak","accessory") else ("🧴" if typ=="consumable" else "✦")

                lines.append(f"{icon} **{name}** x{qty} — {typ}{stat_text}")
            embed.description = "\n".join(lines)

        embed.set_footer(text=f"Page {self.page_index + 1}/{len(self.pages)}  •  Use equippables with Equip button, consumables with Use button")
        if self.message:
            try:
                await self.message.edit(embed=embed, view=self)
            except Exception:
                pass


    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This inventory is not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary, custom_id="vania_inv_prev")
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page_index = max(0, self.page_index - 1)
        await interaction.response.defer()
        await self.update_message()

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, custom_id="vania_inv_next")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page_index = min(len(self.pages) - 1, self.page_index + 1)
        await interaction.response.defer()
        await self.update_message()

    @discord.ui.button(label="Use", style=discord.ButtonStyle.primary, custom_id="vania_inv_use")
    async def use_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        page = self.pages[self.page_index]
        if not page:
            await interaction.response.send_message("No item to use on this page.", ephemeral=True)
            return
        consumable = next((it for it in page if it.get("type") == "consumable"), None)
        if not consumable:
            await interaction.response.send_message("No consumable on this page to use. Use Equip for equippable items.", ephemeral=True)
            return
        item_id = consumable.get("id")
        await interaction.response.defer()
        await self.cog._do_use_item(interaction, str(interaction.user.id), item_id, target=None)
        profiles = self.cog._load_profiles()
        inv = self.cog._gather_inventory(profiles.get(str(self.author_id), {}))
        pages = self.cog._paginate_inventory(inv)
        self.pages = pages
        self.page_index = min(self.page_index, max(0, len(self.pages) - 1))
        await self.update_message()

    @discord.ui.button(label="Equip", style=discord.ButtonStyle.success, custom_id="vania_inv_equip")
    async def equip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        page = self.pages[self.page_index]
        if not page:
            await interaction.response.send_message("No item to equip on this page.", ephemeral=True)
            return

        equippables = []
        for it in page:
            iid = it.get("id")
            typ = it.get("type", "")
            if typ in ("weapon","offhand","head","body","legs","arms","cloak","accessory"):
                equippables.append(it)
                continue
            if any(e.get("id") == iid for e in self.cog.equipment):
                equippables.append(it)

        if not equippables:
            await interaction.response.send_message("No equippable item on this page to equip.", ephemeral=True)
            return

        options = []
        for it in equippables:
            iid = it.get("id")
            meta = next((m for m in self.cog.items if m.get("id") == iid), None)
            if not meta:
                meta = next((e for e in self.cog.equipment if e.get("id") == iid), None)
            name = meta.get("name", iid) if meta else iid
            qty = it.get("qty", 1)
            typ = it.get("type", "item")
            label = f"{name} x{qty}"
            desc = f"{typ}"
            options.append(discord.SelectOption(label=label, value=iid, description=desc[:100]))

        class _EquipSelect(discord.ui.Select):
            def __init__(self, opts, parent):
                super().__init__(placeholder="Choose item to equip...", min_values=1, max_values=1, options=opts)
                self.parent_view = parent

            async def callback(self, select_interaction: discord.Interaction):
                chosen_id = self.values[0]
                if select_interaction.user.id != self.parent_view.author_id:
                    await select_interaction.response.send_message("You cannot equip for someone else.", ephemeral=True)
                    return
                await select_interaction.response.defer()
                await self.parent_view.cog._do_equip_item(select_interaction, str(select_interaction.user.id), chosen_id)
                profiles = self.parent_view.cog._load_profiles()
                inv = self.parent_view.cog._gather_inventory(profiles.get(str(self.parent_view.author_id), {}))
                pages = self.parent_view.cog._paginate_inventory(inv)
                self.parent_view.pages = pages
                self.parent_view.page_index = min(self.parent_view.page_index, max(0, len(self.parent_view.pages) - 1))
                await self.parent_view.update_message()
                try:
                    # resolve display name for friendly ack
                    meta = next((m for m in self.parent_view.cog.items if m.get("id") == chosen_id), None) or next((e for e in self.parent_view.cog.equipment if e.get("id") == chosen_id), None)
                    display = meta.get("name", chosen_id) if meta else chosen_id
                    await select_interaction.followup.send(f"Equipped **{display}**.", ephemeral=True)
                except Exception:
                    pass

        class _EquipSelectView(discord.ui.View):
            def __init__(self, opts, parent, timeout=60):
                super().__init__(timeout=timeout)
                self.add_item(_EquipSelect(opts, parent))
                self.parent_view = parent

            async def on_timeout(self):
                try:
                    for child in list(self.children):
                        child.disabled = True
                    if msg:
                        await msg.edit(view=self)
                except Exception:
                    pass

        view = _EquipSelectView(options, self)
        msg = None
        try:
            await interaction.response.send_message("Select an item to equip:", view=view, ephemeral=True)
            msg = await interaction.original_response()
        except Exception:
            try:
                await interaction.response.send_message("Could not open equip selector.", ephemeral=True)
            except Exception:
                pass
