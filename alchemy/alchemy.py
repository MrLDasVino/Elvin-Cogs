from typing import Optional, Dict, List
import json
import logging
import random
from pathlib import Path

import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify

log = logging.getLogger("red.alchemy")

DEFAULTS = {
    "recipes": {},  # key: "element1+element2" (sorted) -> result
    "users": {},  # user_id (str) -> list of discovered elements
    "auto_imported": False,  # one-time flag to avoid re-importing recipes.json
}


def _normalize(name: str) -> str:
    return name.strip().lower()


def _key_for(*parts: str) -> str:
    cleaned = [_normalize(p) for p in parts if p is not None and p != ""]
    return "+".join(sorted(cleaned))


def _pretty_name(name: str) -> str:
    return name.replace("_", " ").title()


def _random_color() -> discord.Color:
    """Return a random discord.Color."""
    return discord.Color.from_rgb(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))


class Alchemy(commands.Cog):
    """An alchemy combination game."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xA1C3B4D5E6F70809)
        self.config.register_global(**DEFAULTS)
        # Start background task to perform one-time import without blocking init
        try:
            self.bot.loop.create_task(self._maybe_auto_import())
        except Exception:
            log.exception("Failed to schedule auto-import task for Alchemy cog.")

    # ---------- Auto-import ----------
    async def _maybe_auto_import(self):
        """Check config flag and import recipes.json once if present.

        This routine will NOT DM the owner. It only logs and sets the flag.
        Use the owner-only forceimport command to import and post a summary to a channel.
        """
        try:
            cfg = await self.config.all()
            if cfg.get("auto_imported", False):
                log.debug("Alchemy: recipes.json already auto-imported; skipping.")
                return

            recipes_path = Path(__file__).parent / "recipes.json"
            if not recipes_path.exists():
                log.info("Alchemy: no recipes.json found for auto-import.")
                return

            try:
                with recipes_path.open("r", encoding="utf-8") as f:
                    mapping = json.load(f)
            except Exception as e:
                log.exception("Alchemy: failed to parse recipes.json during auto-import: %s", e)
                return

            if not isinstance(mapping, dict):
                log.error("Alchemy: recipes.json must contain a JSON object mapping keys to results.")
                return

            recipes = await self.config.recipes()
            added = []
            skipped = []
            for k, v in mapping.items():
                if not isinstance(k, str) or "+" not in k:
                    skipped.append(str(k))
                    continue
                parts = [p.strip() for p in k.split("+") if p.strip()]
                if not parts:
                    skipped.append(k)
                    continue
                key = _key_for(*parts)
                if key in recipes:
                    log.debug("Alchemy: skipping existing recipe %s", key)
                    continue
                recipes[key] = _normalize(v)
                added.append(f"{'+'.join(parts)} -> {v}")

            await self.config.recipes.set(recipes)
            await self.config.auto_imported.set(True)

            log.info(
                "Alchemy: auto-imported recipes.json; added %d recipes, skipped %d invalid entries.",
                len(added),
                len(skipped),
            )
        except Exception:
            log.exception("Alchemy: unexpected error during auto-import routine.")

    # ---------- Internal helpers ----------
    async def _get_recipes(self) -> Dict[str, str]:
        return await self.config.recipes()

    async def _get_recipe(self, *parts: str) -> Optional[str]:
        key = _key_for(*parts)
        recipes = await self._get_recipes()
        return recipes.get(key)

    async def _set_recipe(self, key: str, result: str):
        recipes = await self._get_recipes()
        recipes[key] = _normalize(result)
        await self.config.recipes.set(recipes)

    async def _remove_recipe_key(self, key: str) -> bool:
        recipes = await self._get_recipes()
        if key in recipes:
            recipes.pop(key)
            await self.config.recipes.set(recipes)
            return True
        return False

    async def _add_discovery(self, user_id: int, element: str) -> bool:
        users = await self.config.users()
        uid = str(user_id)
        user_list = users.get(uid, [])
        element = _normalize(element)
        if element not in user_list:
            user_list.append(element)
            users[uid] = user_list
            await self.config.users.set(users)
            return True
        return False

    async def _get_user_discoveries(self, user_id: int) -> List[str]:
        users = await self.config.users()
        return users.get(str(user_id), [])

    async def _all_elements_set(self) -> set:
        recipes = await self._get_recipes()
        elements = set()
        for k, v in recipes.items():
            parts = k.split("+")
            for p in parts:
                elements.add(_normalize(p))
            elements.add(_normalize(v))
        return elements

    # ---------- Commands ----------
    @commands.group()
    async def alchemy(self, ctx: commands.Context):
        """Alchemy commands group."""
        pass

    @alchemy.command(name="combine")
    async def combine(self, ctx: commands.Context, left: str, right: str):
        """Combine two elements. Example: [p]alchemy combine fire water"""
        left_n = _normalize(left)
        right_n = _normalize(right)
        result = await self._get_recipe(left_n, right_n)
        if not result:
            embed = discord.Embed(
                title="Nothing happened",
                description=f"Combining **{_pretty_name(left_n)}** and **{_pretty_name(right_n)}** produced nothing.",
                color=_random_color(),
            )
            embed.set_footer(text="Try different combinations or ask an owner to add more recipes.")
            await ctx.send(embed=embed)
            return

        discovered_new = await self._add_discovery(ctx.author.id, result)
        title = "New Discovery!" if discovered_new else "Already Discovered"
        embed = discord.Embed(
            title=title,
            description=f"**{_pretty_name(left_n)}** + **{_pretty_name(right_n)}** → **{_pretty_name(result)}**",
            color=_random_color(),
        )
        total = len(await self._all_elements_set())
        user_list = await self._get_user_discoveries(ctx.author.id)
        discovered = len(user_list)
        pct = 0 if total == 0 else int((discovered / total) * 100)
        embed.add_field(name="Your progress", value=f"{discovered}/{total} elements discovered ({pct}%)", inline=False)
        embed.set_footer(text="Use [p]alchemy my to view your discoveries.")
        await ctx.send(embed=embed)

    @alchemy.command(name="list")
    async def list_elements(self, ctx: commands.Context):
        """List all known elements (from recipes)."""
        elements = sorted(list(await self._all_elements_set()))
        if not elements:
            embed = discord.Embed(
                title="No elements yet",
                description="No recipes are registered. Ask the bot owner to import recipes.",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return

        pretty = [f"• **{_pretty_name(e)}**" for e in elements]
        pages = list(pagify("\n".join(pretty), delims=["\n"], page_length=1500))
        for i, page in enumerate(pages, start=1):
            embed = discord.Embed(title="Known Elements", description=page, color=_random_color())
            embed.set_footer(text=f"Page {i}/{len(pages)}")
            await ctx.send(embed=embed)

    @alchemy.command(name="my")
    async def my_discoveries(self, ctx: commands.Context):
        """Show your discovered elements."""
        user_list = await self._get_user_discoveries(ctx.author.id)
        if not user_list:
            embed = discord.Embed(
                title="No discoveries yet",
                description="You haven't discovered any elements. Combine things with [p]alchemy combine!",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return

        pretty = [f"• **{_pretty_name(e)}**" for e in sorted(user_list)]
        pages = list(pagify("\n".join(pretty), delims=["\n"], page_length=1500))
        for i, page in enumerate(pages, start=1):
            embed = discord.Embed(title=f"{ctx.author.display_name}'s Discoveries", description=page, color=_random_color())
            embed.set_footer(text=f"Page {i}/{len(pages)}")
            await ctx.send(embed=embed)

    @alchemy.command(name="leaderboard")
    async def leaderboard(self, ctx: commands.Context):
        """Show top discoverers."""
        users = await self.config.users()
        if not users:
            embed = discord.Embed(
                title="No discoveries yet",
                description="No one has discovered elements yet.",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return

        scores = []
        for uid, lst in users.items():
            scores.append((int(uid), len(lst)))
        scores.sort(key=lambda x: x[1], reverse=True)
        lines = []
        for i, (uid, count) in enumerate(scores[:10], start=1):
            member = ctx.guild.get_member(uid) if ctx.guild else None
            name = member.display_name if member else f"User {uid}"
            lines.append(f"**{i}. {name}** — {count} elements")
        embed = discord.Embed(title="Alchemy Leaderboard", description="\n".join(lines), color=_random_color())
        await ctx.send(embed=embed)

    # ---------- Owner-only management (embeds for feedback) ----------
    @alchemy.command(name="addrecipe")
    @commands.is_owner()
    async def add_recipe(self, ctx: commands.Context, a: str, b: str, *, result: str):
        """Add a recipe. Owner only. Example: [p]alchemy addrecipe fire water steam"""
        key = _key_for(a, b)
        recipes = await self._get_recipes()
        if key in recipes:
            embed = discord.Embed(
                title="Recipe exists",
                description=f"A recipe for **{_pretty_name(a)} + {_pretty_name(b)}** already exists.",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return
        await self._set_recipe(key, result)
        embed = discord.Embed(
            title="Recipe added",
            description=f"**{_pretty_name(a)}** + **{_pretty_name(b)}** → **{_pretty_name(result)}**",
            color=_random_color(),
        )
        await ctx.send(embed=embed)

    @alchemy.command(name="removerecipe")
    @commands.is_owner()
    async def remove_recipe(self, ctx: commands.Context, a: str, b: str):
        """Remove a recipe. Owner only."""
        key = _key_for(a, b)
        removed = await self._remove_recipe_key(key)
        if not removed:
            embed = discord.Embed(
                title="Not found",
                description=f"No recipe for **{_pretty_name(a)} + {_pretty_name(b)}** was found.",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return
        embed = discord.Embed(
            title="Recipe removed",
            description=f"Removed recipe for **{_pretty_name(a)} + {_pretty_name(b)}**.",
            color=_random_color(),
        )
        await ctx.send(embed=embed)

    @alchemy.command(name="recipes")
    @commands.is_owner()
    async def list_recipes(self, ctx: commands.Context):
        """List all recipes (owner only)."""
        recipes = await self._get_recipes()
        if not recipes:
            embed = discord.Embed(title="No recipes", description="No recipes registered.", color=_random_color())
            await ctx.send(embed=embed)
            return

        lines = []
        for k, v in recipes.items():
            parts = k.split("+")
            pretty_parts = " + ".join(_pretty_name(p) for p in parts)
            lines.append(f"**{pretty_parts}** → **{_pretty_name(v)}**")

        pages = list(pagify("\n".join(lines), delims=["\n"], page_length=1500))
        for i, page in enumerate(pages, start=1):
            embed = discord.Embed(title="Registered Recipes", description=page, color=_random_color())
            embed.set_footer(text=f"Page {i}/{len(pages)}")
            await ctx.send(embed=embed)

    @alchemy.command(name="addrecipes")
    @commands.is_owner()
    async def add_recipes_bulk(self, ctx: commands.Context, *, json_recipes: str):
        """Add multiple recipes from a JSON mapping.
        Example: [p]alchemy addrecipes {"fire+water":"steam","earth+water":"mud"}
        """
        try:
            mapping = json.loads(json_recipes)
        except Exception:
            embed = discord.Embed(
                title="Invalid JSON",
                description="Provide a valid JSON mapping: {\"a+b\":\"result\", ...}",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return
        recipes = await self._get_recipes()
        added = []
        skipped = []
        for k, v in mapping.items():
            if "+" in k:
                parts = [p.strip() for p in k.split("+") if p.strip()]
                if not parts:
                    skipped.append(k)
                    continue
                key = _key_for(*parts)
                recipes[key] = _normalize(v)
                added.append(f"{' + '.join(_pretty_name(p) for p in parts)} → {_pretty_name(v)}")
            else:
                skipped.append(k)
        await self.config.recipes.set(recipes)

        desc = ""
        if added:
            desc += "**Added recipes:**\n" + "\n".join(added) + "\n\n"
        if skipped:
            desc += "**Skipped invalid keys:**\n" + ", ".join(skipped)
        embed = discord.Embed(title="Bulk import complete", description=desc, color=_random_color())
        await ctx.send(embed=embed)

    @alchemy.command(name="importfile")
    @commands.is_owner()
    async def import_file(self, ctx: commands.Context):
        """Import recipes from an attached JSON file. Owner only."""
        if not ctx.message.attachments:
            embed = discord.Embed(
                title="No file attached",
                description="Attach a JSON file with recipes and run this command again.",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return
        att = ctx.message.attachments[0]
        data = await att.read()
        try:
            mapping = json.loads(data.decode())
        except Exception:
            embed = discord.Embed(
                title="Invalid JSON file",
                description="The attached file could not be parsed as JSON.",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return
        recipes = await self._get_recipes()
        added = []
        skipped = []
        for k, v in mapping.items():
            if "+" in k:
                parts = [p.strip() for p in k.split("+") if p.strip()]
                if not parts:
                    skipped.append(k)
                    continue
                key = _key_for(*parts)
                recipes[key] = _normalize(v)
                added.append(f"{' + '.join(_pretty_name(p) for p in parts)} → {_pretty_name(v)}")
            else:
                skipped.append(k)
        await self.config.recipes.set(recipes)

        desc = ""
        if added:
            desc += "**Imported recipes:**\n" + "\n".join(added) + "\n\n"
        if skipped:
            desc += "**Skipped invalid keys:**\n" + ", ".join(skipped)
        embed = discord.Embed(title="Import complete", description=desc or "No valid recipes found.", color=_random_color())
        await ctx.send(embed=embed)

    @alchemy.command(name="exportrecipes")
    @commands.is_owner()
    async def export_recipes(self, ctx: commands.Context):
        """Export current recipes as JSON (printed to chat). Owner only."""
        recipes = await self._get_recipes()
        pretty = json.dumps(recipes, indent=2)
        pages = list(pagify(pretty, delims=["\n"], page_length=1500))
        for i, page in enumerate(pages, start=1):
            embed = discord.Embed(
                title="Exported Recipes" if i == 1 else f"Exported Recipes (cont. {i})",
                description=f"```json\n{page}\n```",
                color=_random_color(),
            )
            embed.set_footer(text=f"Page {i}/{len(pages)}")
            await ctx.send(embed=embed)

    @alchemy.command(name="hint")
    async def hint(self, ctx: commands.Context):
        """Get a hint: an undiscovered element you could discover from existing recipes."""
        recipes = await self._get_recipes()
        if not recipes:
            embed = discord.Embed(
                title="No recipes available",
                description="There are no recipes to hint from. Ask the owner to import recipes.",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return

        user_list = set(await self._get_user_discoveries(ctx.author.id))
        possible_results = set(recipes.values()) - user_list
        if not possible_results:
            embed = discord.Embed(
                title="You're done!",
                description="You've discovered every element available in the current recipe set. Great job! 🎉",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return

        choice = random.choice(list(possible_results))
        hint_text = f"Element starts with **{choice[0].upper()}** and is **{len(choice)}** characters long."
        embed = discord.Embed(title="Hint", description=hint_text, color=_random_color())
        embed.set_footer(text="Use this hint to try new combinations.")
        await ctx.send(embed=embed)

    @alchemy.command(name="forceimport")
    @commands.is_owner()
    async def force_import(self, ctx: commands.Context):
        """Force import recipes.json from the cog folder and post a summary to this channel."""
        recipes_path = Path(__file__).parent / "recipes.json"
        if not recipes_path.exists():
            embed = discord.Embed(
                title="recipes.json not found",
                description="No recipes.json file was found in the cog folder.",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return

        try:
            with recipes_path.open("r", encoding="utf-8") as f:
                mapping = json.load(f)
        except Exception:
            embed = discord.Embed(
                title="Failed to read recipes.json",
                description="The file could not be parsed as valid JSON.",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return

        if not isinstance(mapping, dict):
            embed = discord.Embed(
                title="Invalid format",
                description="recipes.json must contain a JSON object mapping keys to results.",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return

        recipes = await self._get_recipes()
        added = []
        skipped = []
        for k, v in mapping.items():
            if not isinstance(k, str) or "+" not in k:
                skipped.append(str(k))
                continue
            parts = [p.strip() for p in k.split("+") if p.strip()]
            if not parts:
                skipped.append(k)
                continue
            key = _key_for(*parts)
            # Do not overwrite existing recipes unless you want to
            if key in recipes:
                continue
            recipes[key] = _normalize(v)
            added.append(f"{' + '.join(_pretty_name(p) for p in parts)} → {_pretty_name(v)}")

        await self.config.recipes.set(recipes)
        await self.config.auto_imported.set(True)

        desc = ""
        if added:
            desc += "**Added recipes:**\n" + "\n".join(added[:50]) + ("\n\n" if len(added) > 0 else "")
        if skipped:
            desc += "**Skipped invalid keys:**\n" + ", ".join(skipped[:50])
        if not desc:
            desc = "No new recipes were added."

        embed = discord.Embed(title="recipes.json import complete", description=desc, color=_random_color())
        await ctx.send(embed=embed)
