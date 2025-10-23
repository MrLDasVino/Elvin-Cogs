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

    # ----------------- Utilities -----------------
    def _default_profile(self) -> dict:
        return {
            "xp": 0,
            "level": 1,
            "skills": {},
            # equipment slots
            "weapon": "vine_whip",
            "offhand": None,
            "head": None,
            "body": None,
            "legs": None,
            "arms": None,
            "cloak": None,
            "accessory1": None,
            "accessory2": None,
            # hp/hearts/inventory
            "hp": 100,
            "max_hp": 100,
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

    # ----------------- Combat helpers (turn-based) -----------------
    def _player_attack(self, profile: dict, monster: dict) -> Tuple[int, bool]:
        """
        Compute player's damage against the monster for one attack.
        Returns (damage, is_crit).
        Weapon metadata supported: min_damage, max_damage, damage_mod, xp_mod, crit_chance, crit_multiplier.
        Level and skill scaling applied.
        """
        weapon = self._get_equipment(profile.get("weapon"))
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

        is_crit = random.random() < crit_chance
        mult = crit_multiplier if is_crit else 1.0

        dmg = int(base * weapon_mod * level_scale * skill_scale * mult)
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

        # total defense = body + offhand (some offhands may add defense) + head/arms/legs/cloak
        defense = 0
        for slot in ("body", "offhand", "head", "arms", "legs", "cloak"):
            defense += int(self._get_equipment(profile.get(slot)).get("defense", 0))

        skills = profile.get("skills", {})
        evasion = int(skills.get("Evasion", 0))
        dodge_chance = 0.02 * evasion
        if random.random() < dodge_chance:
            return 0

        dmg = max(0, base - defense)
        return dmg

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
        Turn-based hunt: player and monster alternate attacks until one falls.
        Uses weapon and armor stats, skills for scaling, awards XP and Hearts on victory.
        """
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid, self._default_profile())

        # Prepare monster snapshot (copy so changes don't mutate base data)
        monster_def = random.choice(self.monsters)
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

        # Support probabilistic heart_reward object or integer
        def extract_heart_reward(hr):
            if isinstance(hr, dict):
                if random.random() <= float(hr.get("chance", 1.0)):
                    return int(hr.get("amount", 0))
                return 0
            return int(hr or 0)

        log_lines: List[str] = []
        player_hp = profile.get("hp", profile.get("max_hp", 100))
        player_max = profile.get("max_hp", 100)

        log_lines.append(f"A wild **{monster['name']}** appears (HP: {monster['hp']})!")

        round_count = 0
        while player_hp > 0 and monster["hp"] > 0 and round_count < 100:
            round_count += 1

            # Player attack
            p_dmg, was_crit = self._player_attack(profile, monster)
            monster["hp"] = max(0, monster["hp"] - p_dmg)
            crit_note = " 💥" if was_crit and p_dmg > 0 else ""
            log_lines.append(f"You strike the **{monster['name']}** for **{p_dmg}** damage{crit_note}. (Enemy {monster['hp']}/{monster['max_hp']})")
            if monster["hp"] == 0:
                break

            # Monster attack
            m_dmg = self._monster_attack(profile, monster)
            player_hp = max(0, player_hp - m_dmg)
            if m_dmg == 0:
                log_lines.append(f"The **{monster['name']}** attacks but you evade it.")
            else:
                log_lines.append(f"The **{monster['name']}** hits you for **{m_dmg}** damage. (You {player_hp}/{player_max})")
            if player_hp == 0:
                break

        # Outcome processing
        if monster["hp"] == 0:
            # Victory
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

            # Build log
            if hearts_awarded:
                profile["hearts"] = profile.get("hearts", 0) + hearts_awarded
                log_lines.append(f"You gained **{xp_gain} XP** and **{hearts_awarded} Heart{'s' if hearts_awarded != 1 else ''}**!")
            else:
                log_lines.append(f"You gained **{xp_gain} XP**!")

            if found_items:
                names = [next((it.get("name") for it in self.items if it.get("id") == iid), iid) for iid in found_items]
                log_lines.append("You found: " + ", ".join(f"**{n}**" for n in names))

            color = discord.Color.random()
        else:
            # Defeat
            log_lines.append("You were defeated and collapse to the ground.")
            player_hp = player_max // 2
            profile["hp"] = player_hp
            color = discord.Color.random()

        # Level-up logic (after XP applied)
        old_level = profile.get("level", 1)
        new_level = profile.get("xp", 0) // 100 + 1
        if new_level > old_level:
            levels_gained = new_level - old_level
            profile["level"] = new_level
            profile["max_hp"] = profile.get("max_hp", 100) + 5 * levels_gained
            player_hp = min(player_hp + 10 * levels_gained, profile["max_hp"])
            log_lines.append(f"You reached level {new_level}! Max HP +{5 * levels_gained}.")

        # Save final HP and profile
        profile["hp"] = player_hp
        profiles[uid] = profile
        await self._save_profiles(profiles)

        # Build embed
        victory = monster["hp"] == 0
        title = f"You {'defeated' if victory else 'were defeated by'} {monster['name']}"
        color = discord.Color.green() if victory else discord.Color.dark_red()

        # short health bars
        player_bar = self._health_bar(profile.get("hp", 0), profile.get("max_hp", 100), length=12)
        monster_bar = self._health_bar(monster["hp"], monster["max_hp"], length=12)

        # recent combat log (keep final 8 lines)
        recent_log = log_lines[-8:] if len(log_lines) > 8 else log_lines
        combat_text = "\n".join(recent_log)

        embed = discord.Embed(title=title, description=f"Round(s) fought: **{round_count}**", color=color)

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

        # rewards / drops
        reward_lines = []
        weapon = self._get_equipment(profile.get("weapon"))
        xp_gain = int(monster.get("xp_reward", 0) * float(weapon.get("xp_mod", 1.0)))
        hearts_awarded = extract_heart_reward(monster.get("heart_reward", 0))
        reward_lines.append(f"**XP**: +{xp_gain}")
        if hearts_awarded:
            reward_lines.append(f"**Hearts**: +{hearts_awarded}")
        if found_items:
            names = [next((it.get("name") for it in self.items if it.get("id") == iid), iid) for iid in found_items]
            reward_lines.append("**Found**: " + ", ".join(names))
        embed.add_field(name="Rewards", value="\n".join(reward_lines) if reward_lines else "None", inline=False)

        embed.set_footer(text=f"Tip: use `vania heal` to spend Hearts. • Rounds: {round_count}")
         await ctx.send(embed=embed)

    @commands.cooldown(1, 3600, commands.BucketType.user)
    @vania.command(name="pray")
    async def pray(self, ctx: commands.Context):
        """
        Pray at the altar to receive up to 5 Hearts. 1 hour cooldown per user.
        Grants a random amount between 1 and 5 Hearts (inclusive).
        """
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid, self._default_profile())

        gained = random.randint(1, 5)
        profile["hearts"] = profile.get("hearts", 0) + gained

        profiles[uid] = profile
        await self._save_profiles(profiles)

        embed = discord.Embed(
            title="You prayed at the altar",
            description=f"You received **{gained}** Heart{'s' if gained != 1 else ''}.",
            color=discord.Color.random()
        )
        embed.add_field(name="Hearts", value=str(profile.get("hearts", 0)), inline=True)
        await ctx.send(embed=embed)

    @vania.command(name="stats")
    async def stats(self, ctx: commands.Context):
        """View your hunter’s level, XP, hearts, equipped gear and slots."""
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid)
        if not profile:
            return await ctx.send("No profile found. Start hunting with `vania hunt`.")

        xp = profile.get("xp", 0)
        level = profile.get("level", xp // 100 + 1)
        skills = profile.get("skills", {})
        hearts = profile.get("hearts", 0)

        # Get equip names safely
        def eqname(slot):
            return self._get_equipment(profile.get(slot)).get("name", "None") if profile.get(slot) else "None"

        embed = discord.Embed(title=f"{ctx.author.display_name}'s Profile", color=discord.Color.random())
        embed.add_field(name="Level", value=level, inline=True)
        embed.add_field(name="XP", value=xp, inline=True)
        embed.add_field(name="Hearts", value=hearts, inline=True)

        embed.add_field(name="Weapon", value=eqname("weapon"), inline=True)
        embed.add_field(name="Offhand", value=eqname("offhand"), inline=True)
        embed.add_field(name="Head", value=eqname("head"), inline=True)
        embed.add_field(name="Body", value=eqname("body"), inline=True)
        embed.add_field(name="Legs", value=eqname("legs"), inline=True)
        embed.add_field(name="Arms", value=eqname("arms"), inline=True)
        embed.add_field(name="Cloak", value=eqname("cloak"), inline=True)
        embed.add_field(name="Accessory 1", value=eqname("accessory1"), inline=True)
        embed.add_field(name="Accessory 2", value=eqname("accessory2"), inline=True)

        embed.add_field(name="HP", value=f"{profile.get('hp',0)}/{profile.get('max_hp',0)}", inline=True)

        if skills:
            skill_list = "\n".join(f"{name}: Lv {lvl}" for name, lvl in skills.items())
            embed.add_field(name="Skills", value=skill_list, inline=False)

        await ctx.send(embed=embed)

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

        embed = discord.Embed(title=f"{ctx.author.display_name}'s Inventory", color=discord.Color.random())
        hearts = profile.get("hearts", 0)
        embed.add_field(name="Hearts", value=str(hearts), inline=True)
        if pages and pages[0]:
            page = pages[0]
            embed.description = "\n".join(
                f"`{i.get('id')}` • **{i.get('name')}** x{i.get('qty')} — {i.get('type','misc')}" for i in page
            )
        else:
            embed.description = "Inventory empty."

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
        """Spend Hearts to heal a portion of your HP. Cooldown applies."""
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid)
        if not profile:
            return await ctx.send("No profile found. Start hunting with `vania hunt`.")

        hearts = int(profile.get("hearts", 0))
        if hearts <= 0:
            return await ctx.send("You have no Hearts to spend for healing.")

        cost = 1
        heal_amount = max(10, profile.get("max_hp", 100) // 6)

        if hearts < cost:
            return await ctx.send(f"You need {cost} Hearts to heal (you have {hearts}).")

        profile["hearts"] = hearts - cost
        profile["hp"] = min(profile.get("max_hp", 100), profile.get("hp", 0) + heal_amount)
        profiles[uid] = profile
        await self._save_profiles(profiles)

        await ctx.send(f"You spent {cost} Heart and healed {heal_amount} HP. Current HP: {profile['hp']}/{profile['max_hp']}")

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
        super().__init__(timeout=120)
        self.cog = cog
        self.ctx = ctx
        self.author_id = ctx.author.id
        self.pages = pages
        self.page_index = 0
        self.message: Optional[discord.Message] = None

    async def update_message(self):
        page = self.pages[self.page_index]
        embed = discord.Embed(title=f"{self.ctx.author.display_name}'s Inventory", color=discord.Color.random())
        # show hearts
        hearts = self.cog._load_profiles().get(str(self.ctx.author.id), {}).get("hearts", 0)
        embed.add_field(name="Hearts", value=str(hearts), inline=True)

        if not page:
            embed.description = "This page is empty."
        else:
            lines = []
            for item in page:
                iid = item.get("id", "unknown")
                name = item.get("name", iid)
                qty = item.get("qty", 1)
                typ = item.get("type", "misc")
                lines.append(f"`{iid}` • **{name}** x{qty} — {typ}")
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
        # find first equippable item on page (slot names included in type)
        equippable = next((it for it in page if it.get("type") in ("weapon", "offhand", "head", "body", "legs", "arms", "cloak", "accessory")), None)
        if not equippable:
            # also accept generic 'armor' or 'item' if equipment metadata exists
            equippable = next((it for it in page if any(e.get("id") == it.get("id") for e in self.cog.equipment)), None)
        if not equippable:
            await interaction.response.send_message("No equippable item on this page to equip.", ephemeral=True)
            return
        item_id = equippable.get("id")
        await interaction.response.defer()
        await self.cog._do_equip_item(interaction, str(interaction.user.id), item_id)
        profiles = self.cog._load_profiles()
        inv = self.cog._gather_inventory(profiles.get(str(self.author_id), {}))
        pages = self.cog._paginate_inventory(inv)
        self.pages = pages
        self.page_index = min(self.page_index, max(0, len(self.pages) - 1))
        await self.update_message()
