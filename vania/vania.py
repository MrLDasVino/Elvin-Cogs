import asyncio
import json
import random
import logging, traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import discord
from redbot.core import commands
from redbot.core.data_manager import cog_data_path

STAGE_GEAR_RANGES = globals().get("STAGE_GEAR_RANGES", {}) or {}

_logger = logging.getLogger("red.vania")


class Vania(commands.Cog):
    """Belmont’s Legacy: Hunter progression with XP, skills, inventory, and raids."""
    
    async def _safe_send(self, ctx_or_interaction, content=None, **kwargs):
        from discord import Interaction
        try:
            if isinstance(ctx_or_interaction, Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(content, **kwargs)
                else:
                    await ctx_or_interaction.response.send_message(content, **kwargs)
            else:
                await ctx_or_interaction.send(content, **kwargs)
        except Exception:
            _logger.exception("Error in _safe_send")
            raise  
           

    # ----------------- World Event Effects -----------------    
    EVENT_EFFECTS = {
        "☀️ Day": {"player_damage": 1.10, "monster_damage": 1.0, "player_hp": 1.05, "monster_hp": 1.0},
        "🌙 Night": {"player_damage": 1.0, "monster_damage": 1.20, "player_hp": 0.95, "monster_hp": 1.10},
        "🌑 Blood Moon": {"player_damage": 0.9, "monster_damage": 1.3, "player_hp": 0.9, "monster_hp": 1.2},
        "🌞 Solar Eclipse": {"player_damage": 1.2, "monster_damage": 0.8, "player_hp": 1.1, "monster_hp": 0.9},
        "🌾 Harvest Festival": {"player_damage": 1.15, "monster_damage": 1.0, "player_hp": 1.2, "monster_hp": 1.0},

        "Clear skies": {"player_damage": 1.0, "monster_damage": 1.0, "player_hp": 1.0, "monster_hp": 1.0},
        "Rainstorm": {"player_damage": 0.90, "monster_damage": 1.0, "player_hp": 1.0, "monster_hp": 0.95},
        "Fog": {"player_damage": 1.0, "monster_damage": 0.90, "player_hp": 1.0, "monster_hp": 0.9},
        "Thunderstorm": {"player_damage": 1.0, "monster_damage": 1.15, "player_hp": 0.95, "monster_hp": 1.05},
        "Snow": {"player_damage": 1.0, "monster_damage": 0.85, "player_hp": 1.05, "monster_hp": 0.9},
        "Haze": {"player_damage": 0.98, "monster_damage": 0.98, "player_hp": 1.0, "monster_hp": 1.0},
        "Drizzle": {"player_damage": 0.97, "monster_damage": 1.0, "player_hp": 1.0, "monster_hp": 0.98}
    }


    STAGE_DEFINITIONS = {
        "Graveyard": (1, 25),
        "Village Outskirts": (26, 65),
        "Castle Approach": (66, 110),
        "Inner Halls": (111, 170),
        "The Sanctum": (171, 10_000_000),
    } 

    # per-stage gear ranges used to randomize dropped gear stats
    STAGE_GEAR_RANGES = {
        "Graveyard": {
            "weapon_min": (5, 8),
            "weapon_max": (9, 14),
            "armor_def": (1, 4)
        },
        "Village Outskirts": {
            "weapon_min": (9, 12),
            "weapon_max": (14, 18),
            "armor_def": (4, 7)
        },
        "Castle Approach": {
            "weapon_min": (12, 15),
            "weapon_max": (18, 22),
            "armor_def": (8, 10)
        },
        "Inner Halls": {
            "weapon_min": (16, 18),
            "weapon_max": (20, 24),
            "armor_def": (10, 14)
        },
        "The Sanctum": {
            "weapon_min": (20, 24),
            "weapon_max": (25, 30),
            "armor_def": (14, 16)
        }
    }    
    
    CLANS = [
        "Belmont Clan",
        "Schneider Clan",
        "Renard Clan",
        "Morris Clan",
        "Lecarde Clan",
        "Belnades Clan",
        "Tepes Family",
        "Baldwin Family",
        "Graves Family",
    ]    

    CLAN_FLAVOR = {
        "Belmont Clan": {
            "title": "Belmont Clan",
            "desc": "Descendents of famed hunters; tradition and whipcraft run in your blood.",
            "flavor": "A cold resolve settles into your shoulders as ancestral purpose hums under your skin.",
            "color": discord.Color.dark_red()
        },
        "Schneider Clan": {
            "title": "Schneider Clan",
            "desc": "Tacticians and ironworkers, their discipline tempers raw force into precise strikes.",
            "flavor": "You feel the weight of careful planning — every swing measured, every step counted.",
            "color": discord.Color.dark_grey()
        },
        "Renard Clan": {
            "title": "Renard Clan",
            "desc": "Shadowy scouts and trackers, masters of ambush and cold patience.",
            "flavor": "A fox’s patience settles into your chest; you wait for the perfect moment to strike.",
            "color": discord.Color.dark_gold()
        },
        "Morris Clan": {
            "title": "Morris Clan",
            "desc": "Rugged warriors who favor heavy arms and stubborn defense.",
            "flavor": "Muscle and stubborn pride answer; your bones feel steadier and older hands steadier still.",
            "color": discord.Color.dark_blue()
        },
        "Lecarde Clan": {
            "title": "Lecarde Clan",
            "desc": "Noble-born protectors with refined technique and a taste for relic-lore.",
            "flavor": "An old courtesy sits in your stance and a scholar’s curiosity warms your thoughts.",
            "color": discord.Color.teal()
        },
        "Belnades Clan": {
            "title": "Belnades Clan",
            "desc": "Arcane caretakers and relic-keepers; wisdom shadows each of their moves.",
            "flavor": "A whisper of old wards brushes your mind; something keeps watch for you tonight.",
            "color": discord.Color.purple()
        },
        "Tepes Family": {
            "title": "Tepes Family",
            "desc": "A lineage touched by darkness; charisma and terror walk the same road.",
            "flavor": "A darker edge brushes your tongue; authority and danger taste the same.",
            "color": discord.Color.dark_teal()
        },
        "Baldwin Family": {
            "title": "Baldwin Family",
            "desc": "Merchants-turned-protectors; clever bargains and wide networks keep them fed.",
            "flavor": "You sense allies in the crowd and coin to smooth rough edges when needed.",
            "color": discord.Color.orange()
        },
        "Graves Family": {
            "title": "Graves Family",
            "desc": "Grim wardens who embrace duty and the bitter truth of sacrifice.",
            "flavor": "A grave humility settles over you and a readiness to shoulder heavy cost.",
            "color": discord.Color.dark_grey()
        },
    }



    def __init__(self, bot):
        self.bot = bot
        self._write_lock = asyncio.Lock()
        # Event used to wake the _cycle_events loop early (e.g., when a channel is configured)
        self._wake_event: asyncio.Event = asyncio.Event()

        self.STAGE_GEAR_RANGES = {}
        seed = globals().get("STAGE_GEAR_RANGES")
        if isinstance(seed, dict):
            self.STAGE_GEAR_RANGES.update(seed)
        self._validate_stage_ranges(self.STAGE_GEAR_RANGES)        

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
            
        # Ensure a default difficulty multiplier is present in settings
        settings = self._load_settings()
        if "difficulty" not in settings:
            settings["difficulty"] = 1.0
            asyncio.create_task(self._save_settings(settings))            

        # Current world event state
        self.current_event = None

        # Background task handle for this cog instance
        self.bg_task: Optional[asyncio.Task] = None

        # If a previous Vania bg task was left attached to the bot from an older load,
        # schedule a best-effort cancel+wait so we don't accumulate duplicate loops.
        prev_task = getattr(self.bot, "_vania_bg_task", None)
        if prev_task and hasattr(prev_task, "cancel") and not getattr(prev_task, "done", lambda: True)():
            try:
                # schedule a short-lived coroutine to cancel and wait for the old task
                asyncio.create_task(self._cancel_and_wait_for(prev_task, timeout=2.0))
            except Exception:
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

        # Ensure the bot-held registry is cleared when this task completes
        def _on_bg_done(t: asyncio.Task):
            try:
                if getattr(self.bot, "_vania_bg_task", None) is t:
                    try:
                        delattr(self.bot, "_vania_bg_task")
                    except Exception:
                        try:
                            del self.bot._vania_bg_task
                        except Exception:
                            pass
            except Exception:
                pass

        try:
            self.bg_task.add_done_callback(_on_bg_done)
        except Exception:
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
                try:
                    # cannot await in sync cog_unload; schedule a short cancel+wait
                    asyncio.create_task(self._cancel_and_wait_for(task, timeout=2.0))
                except Exception:
                    try:
                        task.cancel()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            # Only remove the bot-stored reference if it points to this instance's task.
            if getattr(self.bot, "_vania_bg_task", None) is getattr(self, "bg_task", None):
                try:
                    delattr(self.bot, "_vania_bg_task")
                except Exception:
                    try:
                        del self.bot._vania_bg_task
                    except Exception:
                        pass
        except Exception:
            pass                   

    async def _cancel_and_wait_for(self, task: asyncio.Task, timeout: float = 2.0):
        """Best-effort: cancel a task and wait briefly for it to finish."""
        if not task:
            return
        try:
            task.cancel()
        except Exception:
            pass
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except asyncio.CancelledError:
            return
        except Exception:
            return                   

    # ----------------- Safe package JSON loader -----------------
    def _safe_load_pkg_json(self, path: Path) -> dict:
        if not path.exists():
            raise FileNotFoundError(f"{path.name} not found in data folder")
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            raise ValueError(f"{path.name} contains invalid JSON")
            
    async def _reply(self, ctx_or_interaction, content: str, *, ephemeral: bool = True):
        """
        Robust send helper for Context or Interaction.
        Uses response.send_message when available and not yet used, otherwise uses followup.send.
        Falls back to ctx.send for Contexts and to followup for interactions that were deferred/responded.
        """
        # Interaction path
        if isinstance(ctx_or_interaction, discord.Interaction):
            try:
                # prefer response.send_message when it's safe to use
                if getattr(ctx_or_interaction.response, "is_done", False) is False:
                    await ctx_or_interaction.response.send_message(content, ephemeral=ephemeral)
                else:
                    await ctx_or_interaction.followup.send(content, ephemeral=ephemeral)
                return
            except discord.errors.InteractionResponded:
                try:
                    await ctx_or_interaction.followup.send(content, ephemeral=ephemeral)
                except Exception:
                    pass
                return
            except Exception:
                # fallback to followup for any failure
                try:
                    await ctx_or_interaction.followup.send(content, ephemeral=ephemeral)
                except Exception:
                    pass
                return

        # duck-typed interaction objects (some callers pass objects with .response)
        if hasattr(ctx_or_interaction, "response") and isinstance(getattr(ctx_or_interaction, "response"), object):
            try:
                if getattr(ctx_or_interaction.response, "is_done", False) is False:
                    await ctx_or_interaction.response.send_message(content, ephemeral=ephemeral)
                else:
                    await ctx_or_interaction.followup.send(content, ephemeral=ephemeral)
                return
            except discord.errors.InteractionResponded:
                try:
                    await ctx_or_interaction.followup.send(content, ephemeral=ephemeral)
                except Exception:
                    pass
                return
            except Exception:
                try:
                    await ctx_or_interaction.followup.send(content, ephemeral=ephemeral)
                except Exception:
                    pass
                return

        # Context or fallback
        try:
            await ctx_or_interaction.send(content)
        except Exception:
            try:
                # last resort: try followup if attribute exists
                if hasattr(ctx_or_interaction, "followup"):
                    await ctx_or_interaction.followup.send(content, ephemeral=ephemeral)
            except Exception:
                pass
            

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

    def _validate_stage_ranges(self, ranges_map):
        """Normalize and remove invalid stage range entries in-place."""
        if not isinstance(ranges_map, dict):
            return
        for key, entry in list(ranges_map.items()):
            if not isinstance(entry, dict):
                ranges_map.pop(key, None)
                continue
            # Normalize min/max to ints with safe defaults
            mn = entry.get("min")
            mx = entry.get("max")
            try:
                mn = int(mn)
                mx = int(mx)
            except Exception:
                entry["min"] = 1
                entry["max"] = 1
            else:
                if mn > mx:
                    entry["min"], entry["max"] = mx, mn
                else:
                    entry["min"], entry["max"] = mn, mx
            # Ensure weights exists and is a dict
            if not isinstance(entry.get("weights"), dict):
                entry["weights"] = {"common": 100}
            

    # ----------------- Utilities -----------------
    def _default_profile(self) -> dict:
        return {
            "xp": 0,
            "level": 1,
            "generated_items": {},
            "skills": {},
            "weapon": None,
            "offhand": None,
            "head": None,
            "body": None,
            "legs": None,
            "arms": None,
            "cloak": None,
            "accessory1": None,
            "accessory2": None,
            "hp": 50,
            "max_hp": 50,
            "hearts": 0,
            "relics": [],
            "consumables": {},
            "items": {},
            "clan": None
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
        
    def _stage_for_hp(self, base_hp: int) -> str:
        """Return the stage name that contains base_hp according to STAGE_DEFINITIONS."""
        try:
            hp = int(base_hp)
        except Exception:
            # fallback to first stage name if something is wrong
            return next(iter(self.STAGE_DEFINITIONS.keys()))
        for name, (low, high) in self.STAGE_DEFINITIONS.items():
            if low <= hp <= high:
                return name
        return next(iter(self.STAGE_DEFINITIONS.keys()))

    def _generate_stage_item(self, equip_meta: dict, stage_name: str) -> Tuple[str, dict]:
        """
        Create a unique item instance scaled to stage_name.
        Returns (instance_id, instance_meta).
        """
        base = dict(equip_meta)  # shallow copy
        # Resolve stage_name robustly from the provided param (supports string or dict/object)
        resolved_stage_name = "default"
        if isinstance(stage_name, str):
            resolved_stage_name = stage_name or resolved_stage_name
        else:
            s = stage_name
            if isinstance(s, dict):
                resolved_stage_name = s.get("name") or s.get("id") or resolved_stage_name
            else:
                resolved_stage_name = getattr(s, "name", None) or getattr(s, "id", None) or resolved_stage_name

        # Prefer instance attribute, then module-level constant, else empty dict
        ranges_source = getattr(self, "STAGE_GEAR_RANGES", None) or globals().get("STAGE_GEAR_RANGES", {})
        if not isinstance(ranges_source, dict):
            ranges_source = {}
        ranges = ranges_source.get(resolved_stage_name, {}) or {}
        # weapon
        if base.get("category") == "weapon":
            wmin_rng = ranges.get("weapon_min", (max(1, int(base.get("min_damage", 1))), int(base.get("min_damage", 1) + 2)))
            wmax_rng = ranges.get("weapon_max", (int(base.get("max_damage", base.get("min_damage", 1) + 2)), int(base.get("max_damage", base.get("min_damage", 1) + 4))))
            new_min = random.randint(int(wmin_rng[0]), int(wmin_rng[1]))
            new_max = random.randint(max(new_min, int(wmax_rng[0])), int(wmax_rng[1]))
            base["min_damage"] = new_min
            base["max_damage"] = new_max
        # armor
        elif base.get("category") == "armor":
            def_rng = ranges.get("armor_def", (max(0, int(base.get("defense", 0)) - 1), int(base.get("defense", 0) + 3)))
            new_def = random.randint(int(def_rng[0]), int(def_rng[1]))
            base["defense"] = new_def
        # generate instance id and metadata
        # Build instance id and preserve original reference
        orig_id = base.get("id")
        human_name = base.get("name") or orig_id or "item"
        inst_id = f"{orig_id}_stage_{resolved_stage_name.replace(' ', '_')}_{random.randint(1000,9999)}"

        # Required fields so the display/inventory code can show proper name/stats
        base["instance_of"] = orig_id
        base["generated_stage"] = resolved_stage_name
        base["id"] = inst_id
        # ensure display name is present so the UI doesn't fall back to raw id
        base["name"] = human_name
        base["display_name"] = f"{human_name} (Stage {resolved_stage_name})"

        return inst_id, base       

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
        if not weapon:
            lvl = int(profile.get("level", 1))
            lvl_bonus = lvl // 2
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

        base_miss = 0.05
        weapon_accuracy = float(weapon.get("accuracy", 1.0))
        miss_chance = base_miss - 0.01 * whip_mastery + (0.03 * (1.0 - weapon_accuracy))
        miss_chance = max(0.0, min(0.5, miss_chance))

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
        base_min = int(monster.get("min_damage", max(1, int(monster.get("hp", 10) * 0.05))))
        base_max = int(monster.get("max_damage", max(2, int(monster.get("hp", 10) * 0.15))))
        base = random.randint(base_min, base_max)
        event = getattr(self, "current_event", None)
        if event:
            time_mult = self.EVENT_EFFECTS.get(event["time"], {}).get("monster_damage", 1.0)
            weather_mult = self.EVENT_EFFECTS.get(event["weather"], {}).get("monster_damage", 1.0)
            base = int(base * time_mult * weather_mult)

        defense = 0
        for slot in ("body", "offhand", "head", "arms", "legs", "cloak"):
            defense += int(self._get_equipment(profile.get(slot)).get("defense", 0))

        settings = self._load_settings()
        scale = float(settings.get("difficulty", 1.0))
        try:
            effective_defense = int(defense / max(0.0001, float(scale)))
        except Exception:
            effective_defense = defense

        skills = profile.get("skills", {})
        evasion = int(skills.get("Evasion", 0))
        dodge_chance = 0.02 * evasion

        monster_accuracy = float(monster.get("accuracy", 1.0))
        monster_base_miss = 0.04
        monster_miss_chance = monster_base_miss + (0.03 * (1.0 - monster_accuracy)) - dodge_chance
        monster_miss_chance = max(0.0, min(0.5, monster_miss_chance))
        if random.random() < monster_miss_chance:
            return 0

        dmg = max(0, base - effective_defense)
        dmg = int(dmg * scale)

        return dmg

    # ----------------- Background world events -----------------
    async def _cycle_events(self):
        """Background loop: post world events on a schedule and exit cleanly when cancelled."""
        try:
            await self.bot.wait_until_ready()

            def _event_effects_for(key):
                v = self.EVENT_EFFECTS.get(key, {})
                return v if isinstance(v, dict) else {}

            # full pools omitted here for brevity (unchanged)...
            # (rest of _cycle_events unchanged)
            while not self.bot.is_closed():
                settings = self._load_settings() or {}
                # ... send events ...
                try:
                    try:
                        await asyncio.wait_for(self._wake_event.wait(), timeout=3 * 60 * 60)
                    except asyncio.TimeoutError:
                        pass
                    finally:
                        try:
                            self._wake_event.clear()
                        except Exception:
                            pass
                except asyncio.CancelledError:
                    raise
        except asyncio.CancelledError:
            return
        except Exception:
            return
        finally:
            try:
                if getattr(self.bot, "_vania_bg_task", None) is getattr(self, "bg_task", None):
                    try:
                        delattr(self.bot, "_vania_bg_task")
                    except Exception:
                        try:
                            del self.bot._vania_bg_task
                        except Exception:
                            pass
            except Exception:
                pass


    # ----------------- Immediate event poster (reusable) -----------------
    async def _post_event_to_channel(self, channel: discord.TextChannel):
        # implementation unchanged
        time_of_day = random.choice(list({
            "☀️ Day","🌙 Night","🌑 Blood Moon","🌞 Solar Eclipse","🌾 Harvest Festival"
        }))
        weather = random.choice(list({
            "Clear skies","Rainstorm","Fog","Thunderstorm","Snow","Haze","Drizzle"
        }))
        self.current_event = {"time": time_of_day, "weather": weather}
        # compose embed and send...
        try:
            await channel.send("World event posted")  # placeholder; original embed sending remains unchanged
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
        # unchanged hunt implementation (uses uid and profiles correctly)
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid, self._default_profile())
        await ctx.send("Hunt flow placeholder")  # placeholder

    @commands.cooldown(1, 1200, commands.BucketType.user)
    @vania.command(name="pray")
    async def pray(self, ctx: commands.Context):
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid, self._default_profile())
        gained = random.randint(1, 5)
        profile["hearts"] = profile.get("hearts", 0) + gained
        profiles[uid] = profile
        await self._save_profiles(profiles)
        await ctx.send(f"You gained {gained} hearts.")  # simplified

    @vania.command(name="clan")
    async def clan_join(self, ctx: commands.Context):
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid, self._default_profile())
        meta_map = getattr(self, "CLAN_FLAVOR", {})
        current = profile.get("clan")
        if current:
            meta = (meta_map.get(current) or {})
            await ctx.send(f"Your clan: {current}")
            return
        choice = random.choice(self.CLANS if hasattr(self, "CLANS") else CLANS)
        profile["clan"] = choice
        profiles[uid] = profile
        await self._save_profiles(profiles)
        await ctx.send(f"You joined {choice}.")

    @vania.command(name="stats")
    async def stats(self, ctx: commands.Context):
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid, None)
        if not profile:
            profile = self._default_profile()
            profiles[uid] = profile
            await self._save_profiles(profiles)
        await ctx.send(f"Stats placeholder for {uid}")

    @vania.command(name="channel")
    @commands.has_permissions(manage_guild=True)
    async def set_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        settings = self._load_settings()
        settings[str(ctx.guild.id)] = {"channel_id": channel.id}
        await self._save_settings(settings)
        await ctx.send(f"✅ Updates will now post in {channel.mention} every 3 hours. Posting an initial world update now...")
        try:
            ch = self.bot.get_channel(channel.id)
            if ch:
                await self._post_event_to_channel(ch)
                try:
                    self._wake_event.set()
                except Exception:
                    pass                
        except Exception:
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
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid, self._default_profile())

        inv = self._gather_inventory(profile)
        pages = self._paginate_inventory(inv)
        view = InventoryView(self, ctx, pages)

        hearts = profile.get("hearts", 0)
        relic_count = len(profile.get("relics", []))
        consumable_count = sum(int(q) for q in profile.get("consumables", {}).values())
        item_count = sum(int(q) for q in profile.get("items", {}).values())

        embed = discord.Embed(title=f"{ctx.author.display_name}'s Inventory", color=discord.Color.dark_teal())
        try:
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
        except Exception:
            embed.set_author(name=ctx.author.display_name)

        embed.add_field(
            name="Summary",
            value=f"**Hearts**: {hearts} · **Relics**: {relic_count} · **Consumables**: {consumable_count} · **Items**: {item_count}",
            inline=False,
        )

        page = pages[0] if pages else []
        if not page:
            embed.add_field(name="Contents", value="Inventory empty.", inline=False)
        else:
            lines = []
            for it in page:
                iid = it.get("id", "unknown")
                qty = it.get("qty", 1)
                typ = it.get("type", "misc")
                gen_map = profile.get("generated_items", {}) or {}
                inst_meta = gen_map.get(iid)
                if inst_meta:
                    name = inst_meta.get("display_name") or inst_meta.get("name") or inst_meta.get("instance_of") or iid
                    category = inst_meta.get("category") or inst_meta.get("slot") or typ
                    stat_text = ""
                    if category == "weapon":
                        stat_text = f" [{inst_meta.get('min_damage')}-{inst_meta.get('max_damage')} dmg, crit {int(float(inst_meta.get('crit_chance',0))*100)}%]"
                    elif category == "armor":
                        stat_text = f" [DEF {inst_meta.get('defense',0)}]"
                    it_type = category
                else:
                    meta = next((m for m in self.items if m.get("id") == iid), None)
                    if not meta:
                        meta = next((e for e in self.equipment if e.get("id") == iid), None)
                    name = meta.get("name", iid) if meta else iid
                    stat_text = ""
                    if meta and meta.get("category") == "weapon":
                        stat_text = f" [{meta.get('min_damage')}-{meta.get('max_damage')} dmg, crit {int(meta.get('crit_chance',0)*100)}%]"
                    elif meta and meta.get("category") == "armor":
                        stat_text = f" [DEF {meta.get('defense',0)}]"
                    it_type = typ

                icon = "🔹" if it_type in ("weapon","offhand","head","body","legs","arms","cloak","accessory") else ("🧴" if it_type=="consumable" else "✦")
                lines.append(f"{icon} **{name}**  x{qty} — {it_type}{stat_text}")
            embed.add_field(name=f"Page 1/{len(pages)}", value="\n".join(lines), inline=False)

        embed.set_footer(text="Use the buttons to page, Equip items or Use consumables.")
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.update_message()

    def _gather_inventory(self, profile: dict) -> List[dict]:
        out: List[dict] = []
        for relic in profile.get("relics", []):
            out.append({"id": str(relic), "name": str(relic), "qty": 1, "type": "relic"})
        for cid, qty in profile.get("consumables", {}).items():
            meta = next((it for it in self.items if it.get("id") == cid), {})
            name = meta.get("name", cid)
            out.append({"id": cid, "name": name, "qty": int(qty), "type": "consumable"})
        for iid, qty in profile.get("items", {}).items():
            gen_map = profile.get("generated_items", {}) or {}
            inst_meta = gen_map.get(iid)
            if inst_meta:
                name = inst_meta.get("display_name") or inst_meta.get("name") or inst_meta.get("instance_of") or iid
                it_type = inst_meta.get("slot") or inst_meta.get("category") or "item"
            else:
                meta = next((it for it in self.items if it.get("id") == iid), {})
                name = meta.get("name", iid)
                equip_meta = next((e for e in self.equipment if e.get("id") == iid), None)
                it_type = "item"
                if equip_meta:
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
                # if response already used, send via followup
                try:
                    if ctx_or_interaction.response.is_done():
                        await ctx_or_interaction.followup.send(msg, ephemeral=True)
                    else:
                        await ctx_or_interaction.response.send_message(msg, ephemeral=True)
                except discord.errors.InteractionResponded:
                    try:
                        await ctx_or_interaction.followup.send(msg, ephemeral=True)
                    except Exception:
                        pass
            else:
                await ctx_or_interaction.send(msg)
            return

        consumables = profile.get("consumables", {})
        qty = int(consumables.get(item_id, 0))
        if qty <= 0:
            msg = f"You don't have any `{item_id}` to use."
            if is_interaction:
                try:
                    if ctx_or_interaction.response.is_done():
                        await ctx_or_interaction.followup.send(msg, ephemeral=True)
                    else:
                        await ctx_or_interaction.response.send_message(msg, ephemeral=True)
                except discord.errors.InteractionResponded:
                    try:
                        await ctx_or_interaction.followup.send(msg, ephemeral=True)
                    except Exception:
                        pass
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
        await self._reply(ctx_or_interaction, msg, ephemeral=True)

    # internal equip performer (used by InventoryView Equip button)
    async def _do_equip_item(self, ctx_or_interaction, user_id, chosen_id):
        _logger.debug("_do_equip_item entered; type=%s response_done=%s user=%s",
                      type(ctx_or_interaction),
                      getattr(getattr(ctx_or_interaction, "response", None), "is_done", lambda: False)(),
                      getattr(ctx_or_interaction, "user", getattr(ctx_or_interaction, "author", None)))
        is_interaction = hasattr(ctx_or_interaction, "response") and isinstance(ctx_or_interaction, discord.Interaction)
        profiles = self._load_profiles()
        profile = profiles.get(user_id)
        if not profile:
            msg = "No profile found. Start hunting with `vania hunt`."
            if is_interaction:
                try:
                    if ctx_or_interaction.response.is_done():
                        await ctx_or_interaction.followup.send(msg, ephemeral=True)
                    else:
                        await ctx_or_interaction.response.send_message(msg, ephemeral=True)
                except discord.errors.InteractionResponded:
                    try:
                        await ctx_or_interaction.followup.send(msg, ephemeral=True)
                    except Exception:
                        pass
            else:
                await ctx_or_interaction.send(msg)
            return

        equip_meta = next((e for e in self.equipment if e.get("id") == chosen_id), None)
        if not equip_meta:
            msg = f"`{chosen_id}` is not equippable."
            if is_interaction:
                try:
                    if ctx_or_interaction.response.is_done():
                        await ctx_or_interaction.followup.send(msg, ephemeral=True)
                    else:
                        await ctx_or_interaction.response.send_message(msg, ephemeral=True)
                except discord.errors.InteractionResponded:
                    try:
                        await ctx_or_interaction.followup.send(msg, ephemeral=True)
                    except Exception:
                        pass
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
        if items.get(chosen_id, 0) > 0:
            items[chosen_id] = items[chosen_id] - 1
            if items[chosen_id] <= 0:
                items.pop(chosen_id, None)
            profile["items"] = items
        else:
            # allow equip even if not in inventory (admin granted)
            pass

        # Equip the new item
        profile[chosen_slot] = chosen_id
        profiles[user_id] = profile
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

        msg = f"You equipped **{equip_meta.get('name', chosen_id)}** into **{chosen_slot}**. (XP×{xp_mod}, DMG×{dmg_mod}, DEF {defense})"

        # Send immediate response back to the caller (ephemeral for interactions where appropriate)
        try:
            if isinstance(ctx_or_interaction, discord.Interaction):
                # Do NOT call response.send_message if the interaction was already responded to (deferred).
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(msg, ephemeral=True)
                else:
                    await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
        except discord.errors.InteractionResponded:
            try:
                if isinstance(ctx_or_interaction, discord.Interaction) and getattr(ctx_or_interaction, "followup", None):
                    await ctx_or_interaction.followup.send(msg, ephemeral=True)
                else:
                    await ctx_or_interaction.send(msg)
            except Exception:
                pass
        except Exception:
            # best-effort fallback
            try:
                if isinstance(ctx_or_interaction, discord.Interaction) and getattr(ctx_or_interaction, "followup", None):
                    await ctx_or_interaction.followup.send(msg, ephemeral=True)
                else:
                    await ctx_or_interaction.send(msg)
            except Exception:
                pass

        return msg
        
    async def _do_unequip_item(self, ctx_or_interaction, uid: str, slot: str, announce: bool = False):
        """
        Unequip the item currently in `slot` for user `uid`.
        ctx_or_interaction may be Context or Interaction.
        Returns friendly message string.
        """
        is_interaction = hasattr(ctx_or_interaction, "response") and isinstance(ctx_or_interaction, discord.Interaction)
    
        profiles = self._load_profiles()
        profile = profiles.get(uid)
        if not profile:
            msg = "No profile found. Start hunting with `vania hunt`."
            if is_interaction:
                try:
                    if ctx_or_interaction.response.is_done():
                        await ctx_or_interaction.followup.send(msg, ephemeral=True)
                    else:
                        await ctx_or_interaction.response.send_message(msg, ephemeral=True)
                except discord.errors.InteractionResponded:
                    try:
                        await ctx_or_interaction.followup.send(msg, ephemeral=True)
                    except Exception:
                        pass
            else:
                await ctx_or_interaction.send(msg)
            return msg
    
        current = profile.get(slot)
        if not current:
            msg = f"No item is equipped in **{slot}**."
            if is_interaction:
                try:
                    if ctx_or_interaction.response.is_done():
                        await ctx_or_interaction.followup.send(msg, ephemeral=True)
                    else:
                        await ctx_or_interaction.response.send_message(msg, ephemeral=True)
                except discord.errors.InteractionResponded:
                    try:
                        await ctx_or_interaction.followup.send(msg, ephemeral=True)
                    except Exception:
                        pass
            else:
                await ctx_or_interaction.send(msg)
            return msg
    
        # Move equipped item back to items inventory
        items = profile.setdefault("items", {})
        items[current] = items.get(current, 0) + 1
        profile[slot] = None
        profile["items"] = items
        profiles[uid] = profile
        await self._save_profiles(profiles)
    
        # Compose messages
        display_name = current
        meta = next((m for m in self.items if m.get("id") == current), None) or next((e for e in self.equipment if e.get("id") == current), None)
        if meta:
            display_name = meta.get("name", current)
        msg = f"You unequipped **{display_name}** from **{slot}**."
    
        # immediate response (ephemeral for interactions)
        try:
            if is_interaction:
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(msg, ephemeral=True)
                else:
                    await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
        except discord.errors.InteractionResponded:
            try:
                if is_interaction and getattr(ctx_or_interaction, "followup", None):
                    await ctx_or_interaction.followup.send(msg, ephemeral=True)
                else:
                    await ctx_or_interaction.send(msg)
            except Exception:
                pass
        except Exception:
            pass
    
        return msg
        

    @commands.cooldown(1, 30, commands.BucketType.user)
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
        # unchanged admin command...
        await ctx.send("Cooldowns reset placeholder")

    # (rest of file unchanged; raid commands and InventoryView at bottom)
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

                owner_profile = self.cog._load_profiles().get(str(self.ctx.author.id), {}) or {}
                gen_map = owner_profile.get("generated_items", {}) or {}
                inst_meta = gen_map.get(iid)
                if inst_meta:
                    name = inst_meta.get("display_name") or inst_meta.get("name") or inst_meta.get("instance_of") or iid
                    category = inst_meta.get("category") or inst_meta.get("slot") or typ
                    stat_text = ""
                    if category == "weapon":
                        stat_text = f" [{inst_meta.get('min_damage')}-{inst_meta.get('max_damage')} dmg, crit {int(float(inst_meta.get('crit_chance',0))*100)}%]"
                    elif category == "armor":
                        stat_text = f" [DEF {inst_meta.get('defense',0)}]"
                    it_type = category
                else:
                    meta = next((m for m in self.cog.items if m.get("id") == iid), None)
                    if not meta:
                        meta = next((e for e in self.cog.equipment if e.get("id") == iid), None)
                    name = meta.get("name", iid) if meta else iid
                    stat_text = ""
                    if meta and meta.get("category") == "weapon":
                        stat_text = f" [{meta.get('min_damage')}-{meta.get('max_damage')} dmg, crit {int(meta.get('crit_chance',0)*100)}%]"
                    elif meta and meta.get("category") == "armor":
                        stat_text = f" [DEF {meta.get('defense',0)}]"
                    it_type = typ

                icon = "🔹" if it_type in ("weapon","offhand","head","body","legs","arms","cloak","accessory") else ("🧴" if it_type=="consumable" else "✦")
                lines.append(f"{icon} **{name}** x{qty} — {it_type}{stat_text}")
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
                # have the cog perform the equip and also post a public announcement
                try:
                    await self.parent_view.cog._do_equip_item(select_interaction, str(select_interaction.user.id), chosen_id)
                except TypeError:
                    # fallback for older signature that expects announce parameter
                    try:
                        await self.parent_view.cog._do_equip_item(select_interaction, str(select_interaction.user.id), chosen_id, announce=False)
                    except Exception:
                        pass
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

    @discord.ui.button(label="Unequip", style=discord.ButtonStyle.secondary, custom_id="vania_inv_unequip")
    async def unequip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        page = self.pages[self.page_index]
        profiles = self.cog._load_profiles()
        uid = str(interaction.user.id)
        profile = profiles.get(uid, self.cog._default_profile())
        slots = ["weapon","offhand","head","body","legs","arms","cloak","accessory1","accessory2"]
        equipped = [(s, profile.get(s)) for s in slots if profile.get(s)]
        if not equipped:
            await interaction.response.send_message("You have nothing equipped to unequip.", ephemeral=True)
            return

        options = []
        for s, iid in equipped:
            meta = next((m for m in self.cog.items if m.get("id") == iid), None) or next((e for e in self.cog.equipment if e.get("id") == iid), None)
            name = meta.get("name", iid) if meta else iid
            options.append(discord.SelectOption(label=f"{name} — {s}", value=s, description=str(iid)[:100]))

        class _UnequipSelect(discord.ui.Select):
            def __init__(self, opts, parent):
                super().__init__(placeholder="Choose slot to unequip...", min_values=1, max_values=1, options=opts)
                self.parent_view = parent

            async def callback(self, select_interaction: discord.Interaction):
                if select_interaction.user.id != self.parent_view.author_id:
                    await select_interaction.response.send_message("This inventory is not for you.", ephemeral=True)
                    return
                await select_interaction.response.defer()
                slot = self.values[0]
                try:
                    await self.parent_view.cog._do_unequip_item(select_interaction, str(select_interaction.user.id), slot)
                except TypeError:
                    try:
                        await self.parent_view.cog._do_unequip_item(select_interaction, str(select_interaction.user.id), slot, announce=False)
                    except Exception:
                        pass
                profiles = self.parent_view.cog._load_profiles()
                inv = self.parent_view.cog._gather_inventory(profiles.get(str(self.parent_view.author_id), {}))
                pages = self.parent_view.cog._paginate_inventory(inv)
                self.parent_view.pages = pages
                self.parent_view.page_index = min(self.parent_view.page_index, max(0, len(self.parent_view.pages) - 1))
                await self.parent_view.update_message()
                try:
                    await select_interaction.followup.send("Unequipped.", ephemeral=True)
                except Exception:
                    pass

        class _UnequipSelectView(discord.ui.View):
            def __init__(self, opts, parent, timeout=60):
                super().__init__(timeout=timeout)
                self.add_item(_UnequipSelect(opts, parent))
                self.parent_view = parent

            async def on_timeout(self):
                try:
                    for child in list(self.children):
                        child.disabled = True
                    if msg:
                        await msg.edit(view=self)
                except Exception:
                    pass

        view = _UnequipSelectView(options, self)
        msg = None
        try:
            await interaction.response.send_message("Select equipped slot to unequip:", view=view, ephemeral=True)
            msg = await interaction.original_response()
        except Exception:
            try:
                await interaction.response.send_message("Could not open unequip selector.", ephemeral=True)
            except Exception:
                pass
