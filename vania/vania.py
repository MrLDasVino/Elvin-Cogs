import asyncio
import json
import random
from pathlib import Path
from typing import Dict, List, Optional

import discord
from redbot.core import commands
from redbot.core.data_manager import cog_data_path


class Vania(commands.Cog):
    """Belmont’s Legacy: Hunter progression with XP and skills."""

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
                # if existing file invalid, back it up and reinitialize
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
            "weapon": "vine_whip",
            "armor": None,
            "hp": 100,
            "max_hp": 100,
            "hearts": 0,
            "relics": []
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

    # ----------------- Event listeners for raid participant persistence -----------------
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot:
            return
        raids = self._load_raids()
        # find matching raid by message id and channel
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
        """Begin a monster hunt using monsters.json and apply gear effects."""
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid, self._default_profile())

        # Pick a random monster and fetch its image URL
        monster = random.choice(self.monsters)
        image_url = monster.get("image")

        # Gear stats
        weapon = self._get_equipment(profile.get("weapon"))
        armor = self._get_equipment(profile.get("armor"))
        xp_mod = float(weapon.get("xp_mod", 1.0))
        dmg_mod = float(weapon.get("damage_mod", 1.0))
        defense = int(armor.get("defense", 0))

        # Battle outcome
        if random.random() <= float(monster.get("win_chance", 0.5)):
            base_xp = int(monster.get("xp_reward", 0))
            xp_gain = int(base_xp * xp_mod)
            profile["xp"] += xp_gain
            description = f"You defeated **{monster['name']}** and gained {xp_gain} XP!"
            color = discord.Color.green()
        else:
            base_dmg = random.randint(5, 15)
            damage = max(0, int(base_dmg * dmg_mod) - defense)
            profile["hp"] = max(0, profile["hp"] - damage)
            description = f"The **{monster['name']}** wounded you for {damage} HP!"
            color = discord.Color.orange()

        # Collapse handling
        if profile["hp"] == 0:
            description += "\nYour HP dropped to 0. You collapse and revive at half HP."
            profile["hp"] = profile["max_hp"] // 2

        # Level-up logic: every 100 XP = 1 level
        old_level = profile.get("level", 1)
        new_level = profile["xp"] // 100 + 1
        if new_level > old_level:
            levels_gained = new_level - old_level
            profile["level"] = new_level
            # increase max hp and heal a portion
            profile["max_hp"] = profile.get("max_hp", 100) + 5 * levels_gained
            profile["hp"] = min(profile["hp"] + 10 * levels_gained, profile["max_hp"])
            description += f"\nYou reached level {new_level}! Max HP +{5 * levels_gained}."

        profiles[uid] = profile
        await self._save_profiles(profiles)

        # Build embed with image
        embed = discord.Embed(title="Monster Hunt", description=description, color=color)
        if image_url:
            embed.set_image(url=image_url)
        embed.add_field(name="HP", value=f"{profile['hp']}/{profile['max_hp']}", inline=True)
        embed.add_field(name="XP", value=str(profile["xp"]), inline=True)
        embed.add_field(name="Level", value=str(profile.get("level", 1)), inline=True)
        await ctx.send(embed=embed)

    @vania.command(name="stats")
    async def stats(self, ctx: commands.Context):
        """View your hunter’s level, XP, and equipped whip."""
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid)
        if not profile:
            return await ctx.send("No profile found. Start hunting with `vania hunt`.")

        xp = profile["xp"]
        level = profile.get("level", xp // 100 + 1)
        weapon_id = profile.get("weapon", "vine_whip")
        armor_id = profile.get("armor")
        weapon = self._get_equipment(weapon_id)
        armor = self._get_equipment(armor_id)
        weapon_name = weapon.get("name", "None")
        armor_name = armor.get("name", "None")
        skills = profile.get("skills", {})

        embed = discord.Embed(title=f"{ctx.author.display_name}'s Profile", color=discord.Color.dark_blue())
        embed.add_field(name="Level", value=level, inline=True)
        embed.add_field(name="XP", value=xp, inline=True)
        embed.add_field(name="Weapon", value=weapon_name, inline=True)
        embed.add_field(name="Armor", value=armor_name, inline=True)
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

        # Validate skill against skills_def
        if skill not in self.skills_def:
            valid = ", ".join(sorted(self.skills_def.keys()))
            return await ctx.send(f"Unknown skill `{skill}`. Valid skills: {valid}")

        skills = profile.setdefault("skills", {})
        current = skills.get(skill, 0)
        # Skill cost can come from skills_def or default formula
        defined_cost = self.skills_def.get(skill, {}).get("base_cost")
        cost = int(defined_cost) if defined_cost is not None else (current + 1) * 50

        if profile["xp"] < cost:
            return await ctx.send(f"You need {cost} XP to train {skill} (you have {profile['xp']} XP).")

        profile["xp"] -= cost
        skills[skill] = current + 1
        profiles[uid] = profile
        await self._save_profiles(profiles)

        embed = discord.Embed(title="Training Complete", description=f"{skill} upgraded to level {skills[skill]}!", color=discord.Color.green())
        embed.add_field(name="XP Remaining", value=str(profile["xp"]))
        await ctx.send(embed=embed)

    @vania.command(name="equip")
    async def equip(self, ctx: commands.Context, item_id: str):
        """Equip a weapon or armor from equipment.json."""
        profiles = self._load_profiles()
        uid = str(ctx.author.id)
        profile = profiles.get(uid)
        if not profile:
            return await ctx.send("Start hunting first with `vania hunt`.")

        item = next((e for e in self.equipment if e.get("id") == item_id), None)
        if not item:
            return await ctx.send(f"No equipment found with ID `{item_id}`.")

        # Equip by category
        category = item.get("category")
        if category == "weapon":
            profile["weapon"] = item_id
        elif category == "armor":
            profile["armor"] = item_id
        else:
            return await ctx.send("Item category not equippable.")

        profiles[uid] = profile
        await self._save_profiles(profiles)

        # Show resulting stats succinctly
        weapon = self._get_equipment(profile.get("weapon"))
        armor = self._get_equipment(profile.get("armor"))
        xp_mod = weapon.get("xp_mod", 1.0)
        dmg_mod = weapon.get("damage_mod", 1.0)
        defense = armor.get("defense", 0)

        await ctx.send(f"You have equipped **{item['name']}** as your {category}. (XP×{xp_mod}, DMG×{dmg_mod}, DEF {defense})")

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

        embed = discord.Embed(title=f"Raid Sign-Up: {boss['name']}", description="React with ✅ to join the raid!", color=discord.Color.purple())
        embed.add_field(name="Boss HP", value=str(boss.get("hp")), inline=False)
        msg = await channel.send(embed=embed)
        await msg.add_reaction("✅")

        raids = self._load_raids()
        raids[boss_id] = {
            "channel_id": channel.id,
            "message_id": msg.id,
            "participants": []  # persisted participant IDs (strings)
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

        # Try to fetch message, if missing fallback to participants stored
        msg = None
        try:
            msg = await channel.fetch_message(entry.get("message_id"))
        except Exception:
            msg = None

        # Attempt to read participants from saved file first, fallback to reactions if missing
        participant_ids = set(entry.get("participants", []))
        if not participant_ids and msg:
            reaction = discord.utils.get(msg.reactions, emoji="✅")
            if reaction:
                participant_ids = {str(u.id) for u in await reaction.users().flatten() if not u.bot}

        if not participant_ids:
            return await ctx.send("No participants joined the raid.")

        # Simulate group damage, scaled by profile stats
        boss_max_hp = int(boss.get("hp", 1000))
        boss_hp = boss_max_hp
        reports: List[str] = []
        profiles = self._load_profiles()

        for pid in list(participant_ids):
            user_obj = self.bot.get_user(int(pid))
            name = user_obj.display_name if user_obj else f"User {pid}"
            # Load or default profile
            prof = profiles.get(pid, self._default_profile())
            lvl = int(prof.get("level", 1))
            weapon = self._get_equipment(prof.get("weapon"))
            weapon_mod = float(weapon.get("damage_mod", 1.0))
            # Base damage ranges scaled by level and weapon
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

        embed = discord.Embed(title=f"Raid vs {boss['name']}", description=description, color=discord.Color.red() if boss_hp > 0 else discord.Color.gold())
        if image_url:
            embed.set_image(url=image_url)

        await channel.send(embed=embed)

        # Win or Loss branch, rewarding by contribution equally for now
        if boss_hp == 0:
            # Victory: reward participants
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

            victory_embed = discord.Embed(title="Raid Victory!", description="\n".join(reward_lines), color=discord.Color.green())
            if image_url:
                victory_embed.set_thumbnail(url=image_url)
            await channel.send(embed=victory_embed)
        else:
            fail_embed = discord.Embed(title="Raid Failed", description=(f"The raid against **{boss['name']}** has failed. The boss still stands victorious."), color=discord.Color.dark_gray())
            if image_url:
                fail_embed.set_thumbnail(url=image_url)
            await channel.send(embed=fail_embed)

        # Cleanup raid entry
        raids.pop(boss_id, None)
        await self._save_raids(raids)
