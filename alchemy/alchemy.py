import re
import json
import logging
import random
import asyncio
from pathlib import Path
from typing import Optional, Dict, List, Sequence

import discord
from discord import ui
from redbot.core import commands, Config
from redbot.core.bot import Red

log = logging.getLogger("red.alchemy")

DEFAULTS = {
    "recipes": {},
    "users": {},
    "auto_imported": False,
    "require_discovered": False,
    "auto_reimport_on_change": False,
    "auto_reimport_overwrite": False,
    "last_import_summary": "",
    "starter_elements": ["fire", "water", "earth", "air"],
}


# -------------------------
# Normalization / utilities
# -------------------------
def _normalize(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = name.strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace(" ", "_")
    return s.lower()


def _split_key_string(k: str) -> List[str]:
    if not isinstance(k, str):
        return []
    parts = re.split(r"[,+]|\s+", k)
    return [p for p in (p.strip() for p in parts) if p]


def _key_for(*parts: str) -> str:
    cleaned = [_normalize(p) for p in parts if p is not None and str(p).strip() != ""]
    return "+".join(sorted(cleaned))


def _pretty_name(name: str) -> str:
    if not isinstance(name, str) or name == "":
        return ""
    return name.replace("_", " ").title()


def _random_color() -> discord.Color:
    return discord.Color.from_rgb(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))


def chunk_items(items: Sequence[str], chunk_size: int = 30) -> List[str]:
    pages = []
    for i in range(0, len(items), chunk_size):
        page = "\n".join(items[i : i + chunk_size])
        pages.append(page)
    return pages


# -------------------------
# Paginator view (buttons) - FIXED interaction handling
# -------------------------
class PaginatorView(ui.View):
    """
    Button-based paginator for embeds or text pages.
    Only the original invoker (or bot owner) may control the paginator.

    Fixes:
    - Always acknowledge interactions by using interaction.response.edit_message(...)
      so Discord doesn't show "This interaction failed".
    - Button states are updated before editing so the view sent back is consistent.
    """

    def __init__(self, pages: List[str], author_id: int, title: Optional[str] = None, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.index = 0
        self.author_id = author_id
        self.title = title or ""
        self.message: Optional[discord.Message] = None
        # Ensure buttons exist (discord.py creates them from decorators)
        # Set initial states now
        self._update_button_states()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Allow the original invoker or the bot owner to control the paginator
        if interaction.user.id == self.author_id:
            return True
        try:
            app_info = await interaction.client.application_info()
            if app_info and app_info.owner and interaction.user.id == app_info.owner.id:
                return True
        except Exception:
            pass
        await interaction.response.send_message("You cannot control this paginator.", ephemeral=True)
        return False

    def _embed_for_page(self, idx: int) -> discord.Embed:
        content = self.pages[idx]
        embed = discord.Embed(title=self.title, description=content, color=_random_color())
        embed.set_footer(text=f"Page {idx + 1}/{len(self.pages)}")
        return embed

    async def start(self, ctx: commands.Context):
        """Send initial message and attach view."""
        # Ensure button states reflect current index before sending
        self._update_button_states()
        embed = self._embed_for_page(self.index)
        self.message = await ctx.send(embed=embed, view=self)
        return self.message

    def _update_button_states(self):
        # children order: prev, close, next (as defined below)
        # If there are no children yet (e.g., before decorators run), skip
        if not self.children:
            return
        if len(self.pages) <= 1:
            for child in self.children:
                child.disabled = True
            return
        prev_btn = self.children[0]
        next_btn = self.children[2]
        prev_btn.disabled = self.index == 0
        next_btn.disabled = self.index >= len(self.pages) - 1

    async def _edit_via_interaction(self, interaction: discord.Interaction):
        """
        Edit the message using interaction.response.edit_message so the interaction is acknowledged.
        If that fails (rare), fall back to editing the stored message directly.
        """
        self._update_button_states()
        embed = self._embed_for_page(self.index)
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            # If interaction response already used or fails, try to edit the stored message
            try:
                if self.message:
                    await self.message.edit(embed=embed, view=self)
                    # Acknowledge if possible (best-effort)
                    try:
                        await interaction.response.defer()
                    except Exception:
                        pass
            except Exception:
                # Last resort: ignore; nothing more we can do
                pass

    @ui.button(label="◀️ Prev", style=discord.ButtonStyle.secondary, custom_id="alchemy_prev")
    async def prev_button(self, button: ui.Button, interaction: discord.Interaction):
        if self.index > 0:
            self.index -= 1
        await self._edit_via_interaction(interaction)

    @ui.button(label="⏹️ Close", style=discord.ButtonStyle.danger, custom_id="alchemy_close")
    async def close_button(self, button: ui.Button, interaction: discord.Interaction):
        # disable all buttons and update view; acknowledge via edit_message
        for child in self.children:
            child.disabled = True
        await self._edit_via_interaction(interaction)
        self.stop()

    @ui.button(label="Next ▶️", style=discord.ButtonStyle.secondary, custom_id="alchemy_next")
    async def next_button(self, button: ui.Button, interaction: discord.Interaction):
        if self.index < len(self.pages) - 1:
            self.index += 1
        await self._edit_via_interaction(interaction)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass


# -------------------------
# Cog
# -------------------------
class Alchemy(commands.Cog):
    """Alchemy combination game."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xA1C3B4D5E6F70809)
        self.config.register_global(**DEFAULTS)
        self._watch_task: Optional[asyncio.Task] = None
        self._recipes_mtime: Optional[float] = None
        try:
            self.bot.loop.create_task(self._startup_tasks())
        except Exception:
            log.exception("Failed to schedule startup tasks for Alchemy cog.")

    # -------------------------
    # Startup tasks
    # -------------------------
    async def _startup_tasks(self):
        await self._maybe_auto_import()
        if await self.config.auto_reimport_on_change():
            self._start_watcher()

    # -------------------------
    # Auto-import (one-time)
    # -------------------------
    async def _maybe_auto_import(self):
        try:
            cfg = await self.config.all()
            if cfg.get("auto_imported", False):
                await self._record_recipes_mtime()
                return

            recipes_path = Path(__file__).parent / "recipes.json"
            if not recipes_path.exists():
                return

            try:
                with recipes_path.open("r", encoding="utf-8") as f:
                    mapping = json.load(f)
            except Exception as e:
                log.exception("Failed to parse recipes.json: %s", e)
                return

            if not isinstance(mapping, dict):
                log.error("recipes.json must be an object mapping keys to results.")
                return

            recipes = await self.config.recipes()
            added = []
            skipped = []
            for k, v in mapping.items():
                parts = _split_key_string(k)
                if not parts or not isinstance(v, str):
                    skipped.append(str(k))
                    continue
                key = _key_for(*parts)
                if key in recipes:
                    continue
                recipes[key] = _normalize(v)
                added.append(f"{'+'.join(parts)} -> {v}")

            await self.config.recipes.set(recipes)
            await self.config.auto_imported.set(True)
            await self._record_recipes_mtime()

            summary = f"Auto-imported recipes.json: added {len(added)} recipes, skipped {len(skipped)} invalid entries."
            if added:
                sample = "\n".join(added[:20])
                summary += f"\nSample added:\n{sample}"
            await self.config.last_import_summary.set(summary)
            log.info("Alchemy: %s", summary)
        except Exception:
            log.exception("Unexpected error during auto-import.")

    # -------------------------
    # File watcher for recipes.json
    # -------------------------
    def _start_watcher(self):
        if self._watch_task and not self._watch_task.done():
            return
        self._watch_task = self.bot.loop.create_task(self._watch_recipes_file())

    def _stop_watcher(self):
        if self._watch_task:
            self._watch_task.cancel()
            self._watch_task = None

    async def _record_recipes_mtime(self):
        try:
            recipes_path = Path(__file__).parent / "recipes.json"
            if recipes_path.exists():
                self._recipes_mtime = recipes_path.stat().st_mtime
            else:
                self._recipes_mtime = None
        except Exception:
            self._recipes_mtime = None

    async def _watch_recipes_file(self):
        recipes_path = Path(__file__).parent / "recipes.json"
        poll_interval = 8
        try:
            while True:
                try:
                    if recipes_path.exists():
                        mtime = recipes_path.stat().st_mtime
                        if self._recipes_mtime is None:
                            self._recipes_mtime = mtime
                        elif mtime != self._recipes_mtime:
                            await self._reimport_recipes_on_change(recipes_path)
                            self._recipes_mtime = mtime
                    else:
                        self._recipes_mtime = None
                except Exception:
                    log.exception("Error while watching recipes.json.")
                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            log.debug("Watcher cancelled.")
        except Exception:
            log.exception("Unexpected error in watcher.")

    async def _reimport_recipes_on_change(self, recipes_path: Path):
        try:
            with recipes_path.open("r", encoding="utf-8") as f:
                mapping = json.load(f)
        except Exception as e:
            await self.config.last_import_summary.set(f"Re-import failed: invalid JSON ({e}).")
            return

        if not isinstance(mapping, dict):
            msg = "Re-import failed: recipes.json must contain a JSON object mapping keys to results."
            await self.config.last_import_summary.set(msg)
            return

        overwrite = await self.config.auto_reimport_overwrite()
        recipes = await self._get_recipes()
        added = []
        overwritten = []
        skipped = []
        for k, v in mapping.items():
            parts = _split_key_string(k)
            if not parts or not isinstance(v, str):
                skipped.append(str(k))
                continue
            key = _key_for(*parts)
            if key in recipes:
                if overwrite:
                    recipes[key] = _normalize(v)
                    overwritten.append(f"{'+'.join(parts)} -> {v}")
                else:
                    continue
            else:
                recipes[key] = _normalize(v)
                added.append(f"{'+'.join(parts)} -> {v}")

        await self.config.recipes.set(recipes)
        summary_lines = [f"Auto re-import completed. Added: {len(added)}. Overwritten: {len(overwritten)}. Skipped invalid: {len(skipped)}."]
        if added:
            summary_lines.append("Added (sample):")
            summary_lines.extend(added[:20])
        if overwritten:
            summary_lines.append("Overwritten (sample):")
            summary_lines.extend(overwritten[:20])
        if skipped:
            summary_lines.append("Skipped invalid keys (sample):")
            summary_lines.extend(skipped[:20])
        summary = "\n".join(summary_lines)
        await self.config.last_import_summary.set(summary)
        log.info("Alchemy: %s", summary)

    # -------------------------
    # Internal helpers
    # -------------------------
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

    async def _base_ingredients_set(self) -> set:
        recipes = await self._get_recipes()
        bases = set()
        for k in recipes.keys():
            parts = k.split("+")
            for p in parts:
                bases.add(_normalize(p))
        return bases

    async def _get_starter_elements(self) -> set:
        raw = await self.config.starter_elements()
        if not isinstance(raw, list):
            return set()
        return {_normalize(x) for x in raw if isinstance(x, str) and x.strip()}

    async def _user_available_set(self, user_id: int) -> set:
        user_discoveries = set(await self._get_user_discoveries(user_id))
        starters = await self._get_starter_elements()
        return user_discoveries.union(starters)

    async def _require_discovered(self) -> bool:
        cfg = await self.config.all()
        return bool(cfg.get("require_discovered", False))

    # -------------------------
    # Helper to send paginated content using PaginatorView
    # -------------------------
    async def _send_paginated(self, ctx: commands.Context, pages: List[str], title: Optional[str] = None):
        if not pages:
            embed = discord.Embed(title=title or "No content", description="Nothing to show.", color=_random_color())
            await ctx.send(embed=embed)
            return
        if len(pages) == 1:
            embed = discord.Embed(title=title or "", description=pages[0], color=_random_color())
            await ctx.send(embed=embed)
            return
        view = PaginatorView(pages=pages, author_id=ctx.author.id, title=title or "")
        await view.start(ctx)

    # -------------------------
    # Commands
    # -------------------------
    @commands.group()
    async def alchemy(self, ctx: commands.Context):
        """Alchemy commands group."""
        pass

    @alchemy.command(name="combine")
    async def combine(self, ctx: commands.Context, left: str, right: str):
        left_n = _normalize(left)
        right_n = _normalize(right)

        if await self._require_discovered():
            available = await self._user_available_set(ctx.author.id)
            missing = [x for x in (left_n, right_n) if x not in available]
            if missing:
                pretty_missing = ", ".join(_pretty_name(m) for m in missing)
                embed = discord.Embed(
                    title="Cannot combine",
                    description=f"You cannot use **{pretty_missing}** as an ingredient yet.",
                    color=_random_color(),
                )
                embed.add_field(
                    name="How to unlock",
                    value="Discover elements by combining other items or ask an owner to add recipes. Use `[p]alchemy available` to see what you can use.",
                    inline=False,
                )
                embed.set_footer(text="Use [p]alchemy hint for a gentle nudge.")
                await ctx.send(embed=embed)
                return

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

    @alchemy.command(name="available")
    async def available(self, ctx: commands.Context):
        avail = sorted(list(await self._user_available_set(ctx.author.id)))
        if not avail:
            embed = discord.Embed(
                title="No available elements",
                description="You have no unlocked elements yet. Combine things with `[p]alchemy combine` or use `[p]alchemy hint` for ideas.",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return
        pretty = [f"• **{_pretty_name(e)}**" for e in avail]
        pages = chunk_items(pretty, 30)
        await self._send_paginated(ctx, pages, title="Available Ingredients")

    @alchemy.command(name="list")
    @commands.is_owner()
    async def list_elements(self, ctx: commands.Context):
        elements = sorted(list(await self._all_elements_set()))
        if not elements:
            embed = discord.Embed(
                title="No elements yet",
                description="No recipes are registered. Import recipes.json or add recipes.",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return
        pretty = [f"• **{_pretty_name(e)}**" for e in elements]
        pages = chunk_items(pretty, 30)
        await self._send_paginated(ctx, pages, title="Known Elements")

    @alchemy.command(name="my")
    async def my_discoveries(self, ctx: commands.Context):
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
        pages = chunk_items(pretty, 30)
        await self._send_paginated(ctx, pages, title=f"{ctx.author.display_name}'s Discoveries")

    @alchemy.command(name="leaderboard")
    async def leaderboard(self, ctx: commands.Context):
        users = await self.config.users()
        if not users:
            embed = discord.Embed(title="No discoveries yet", description="No one has discovered elements yet.", color=_random_color())
            await ctx.send(embed=embed)
            return
        scores = []
        for uid, lst in users.items():
            try:
                scores.append((int(uid), len(lst)))
            except Exception:
                continue
        scores.sort(key=lambda x: x[1], reverse=True)
        lines = []
        for i, (uid, count) in enumerate(scores, start=1):
            member = ctx.guild.get_member(uid) if ctx.guild else None
            name = member.display_name if member else f"User {uid}"
            lines.append(f"**{i}. {name}** — {count} elements")
        pages = chunk_items(lines, 30)
        await self._send_paginated(ctx, pages, title="Alchemy Leaderboard")

    # -------------------------
    # Owner-only management (combined addrecipe)
    # -------------------------
    @alchemy.command(name="addrecipe")
    @commands.is_owner()
    async def add_recipe(self, ctx: commands.Context, *args):
        if not args:
            embed = discord.Embed(
                title="Usage",
                description="Single: `[p]alchemy addrecipe a b result`\nBulk: `[p]alchemy addrecipe {\"a+b\":\"result\", ...}`",
                color=_random_color(),
            )
            await ctx.send(embed=embed)
            return

        if len(args) == 1 and args[0].strip().startswith("{"):
            json_text = args[0]
            try:
                mapping = json.loads(json_text)
            except Exception:
                embed = discord.Embed(title="Invalid JSON", description="Provide a valid JSON mapping.", color=_random_color())
                await ctx.send(embed=embed)
                return
            if not isinstance(mapping, dict):
                embed = discord.Embed(title="Invalid format", description="JSON must be an object mapping keys to results.", color=_random_color())
                await ctx.send(embed=embed)
                return

            recipes = await self._get_recipes()
            added = []
            skipped = []
            for k, v in mapping.items():
                parts = _split_key_string(k)
                if not parts or not isinstance(v, str):
                    skipped.append(str(k))
                    continue
                key = _key_for(*parts)
                if key in recipes:
                    continue
                recipes[key] = _normalize(v)
                added.append(f"{' + '.join(_pretty_name(p) for p in parts)} → {_pretty_name(v)}")
            await self.config.recipes.set(recipes)
            desc = ""
            if added:
                desc += "**Added recipes:**\n" + "\n".join(added) + "\n\n"
            if skipped:
                desc += "**Skipped invalid keys:**\n" + ", ".join(skipped)
            embed = discord.Embed(title="Bulk import complete", description=desc or "No valid recipes added.", color=_random_color())
            await ctx.send(embed=embed)
            return

        if len(args) < 3:
            embed = discord.Embed(title="Invalid usage", description="Single recipe requires: `[p]alchemy addrecipe a b result`", color=_random_color())
            await ctx.send(embed=embed)
            return

        a = args[0]
        b = args[1]
        result = " ".join(args[2:])
        key = _key_for(a, b)
        recipes = await self._get_recipes()
        if key in recipes:
            embed = discord.Embed(title="Recipe exists", description=f"A recipe for **{_pretty_name(a)} + {_pretty_name(b)}** already exists.", color=_random_color())
            await ctx.send(embed=embed)
            return
        recipes[key] = _normalize(result)
        await self.config.recipes.set(recipes)
        embed = discord.Embed(title="Recipe added", description=f"**{_pretty_name(a)}** + **{_pretty_name(b)}** → **{_pretty_name(result)}**", color=_random_color())
        await ctx.send(embed=embed)

    @alchemy.command(name="removerecipe")
    @commands.is_owner()
    async def remove_recipe(self, ctx: commands.Context, a: str, b: str):
        key = _key_for(a, b)
        removed = await self._remove_recipe_key(key)
        if not removed:
            embed = discord.Embed(title="Not found", description=f"No recipe for **{_pretty_name(a)} + {_pretty_name(b)}** was found.", color=_random_color())
            await ctx.send(embed=embed)
            return
        embed = discord.Embed(title="Recipe removed", description=f"Removed recipe for **{_pretty_name(a)} + {_pretty_name(b)}**.", color=_random_color())
        await ctx.send(embed=embed)

    @alchemy.command(name="recipes")
    @commands.is_owner()
    async def list_recipes(self, ctx: commands.Context):
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
        pages = chunk_items(lines, 30)
        await self._send_paginated(ctx, pages, title="Registered Recipes")

    @alchemy.command(name="importfile")
    @commands.is_owner()
    async def import_file(self, ctx: commands.Context):
        if not ctx.message.attachments:
            embed = discord.Embed(title="No file attached", description="Attach a JSON file with recipes and run this command again.", color=_random_color())
            await ctx.send(embed=embed)
            return
        att = ctx.message.attachments[0]
        data = await att.read()
        try:
            mapping = json.loads(data.decode())
        except Exception:
            embed = discord.Embed(title="Invalid JSON file", description="The attached file could not be parsed as JSON.", color=_random_color())
            await ctx.send(embed=embed)
            return
        if not isinstance(mapping, dict):
            embed = discord.Embed(title="Invalid format", description="recipes.json must contain a JSON object mapping keys to results.", color=_random_color())
            await ctx.send(embed=embed)
            return
        recipes = await self._get_recipes()
        added = []
        skipped = []
        for k, v in mapping.items():
            parts = _split_key_string(k)
            if not parts or not isinstance(v, str):
                skipped.append(str(k))
                continue
            key = _key_for(*parts)
            recipes[key] = _normalize(v)
            added.append(f"{' + '.join(_pretty_name(p) for p in parts)} → {_pretty_name(v)}")
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
        recipes = await self._get_recipes()
        pretty = json.dumps(recipes, indent=2)
        lines = pretty.splitlines()
        pages = chunk_items(lines, 30)
        await self._send_paginated(ctx, pages, title="Exported Recipes")

    @alchemy.command(name="hint")
    async def hint(self, ctx: commands.Context):
        recipes = await self._get_recipes()
        if not recipes:
            embed = discord.Embed(title="No recipes available", description="There are no recipes to hint from. Ask the owner to import recipes.", color=_random_color())
            await ctx.send(embed=embed)
            return
        user_list = set(await self._get_user_discoveries(ctx.author.id))
        possible_results = set(recipes.values()) - user_list
        if not possible_results:
            embed = discord.Embed(title="You're done!", description="You've discovered every element available in the current recipe set. Great job! 🎉", color=_random_color())
            await ctx.send(embed=embed)
            return
        choice = random.choice(list(possible_results))
        hint_text = f"Element starts with **{choice[0].upper()}** and is **{len(choice)}** characters long."
        embed = discord.Embed(title="Hint", description=hint_text, color=_random_color())
        embed.set_footer(text="Use this hint to try new combinations.")
        await ctx.send(embed=embed)

    # -------------------------
    # Starter elements management (owner)
    # -------------------------
    @alchemy.command(name="starters")
    @commands.is_owner()
    async def show_starters(self, ctx: commands.Context):
        starters = sorted(list(await self._get_starter_elements()))
        if not starters:
            embed = discord.Embed(title="No starter elements", description="Starter list is empty.", color=_random_color())
            await ctx.send(embed=embed)
            return
        pretty = [f"• **{_pretty_name(e)}**" for e in starters]
        pages = chunk_items(pretty, 30)
        await self._send_paginated(ctx, pages, title="Starter Elements")

    @alchemy.command(name="addstarter")
    @commands.is_owner()
    async def add_starter(self, ctx: commands.Context, *, element: str):
        if not element or not element.strip():
            await ctx.send("Provide an element name to add.")
            return
        normalized = _normalize(element)
        starters = await self._get_starter_elements()
        if normalized in starters:
            embed = discord.Embed(title="Already a starter", description=f"**{_pretty_name(normalized)}** is already a starter.", color=_random_color())
            await ctx.send(embed=embed)
            return
        starters.add(normalized)
        await self.config.starter_elements.set(sorted(list(starters)))
        embed = discord.Embed(title="Starter added", description=f"Added **{_pretty_name(normalized)}** to starter elements.", color=_random_color())
        await ctx.send(embed=embed)

    @alchemy.command(name="removestarter")
    @commands.is_owner()
    async def remove_starter(self, ctx: commands.Context, *, element: str):
        if not element or not element.strip():
            await ctx.send("Provide an element name to remove.")
            return
        normalized = _normalize(element)
        starters = await self._get_starter_elements()
        if normalized not in starters:
            embed = discord.Embed(title="Not a starter", description=f"**{_pretty_name(normalized)}** is not in the starter list.", color=_random_color())
            await ctx.send(embed=embed)
            return
        starters.remove(normalized)
        await self.config.starter_elements.set(sorted(list(starters)))
        embed = discord.Embed(title="Starter removed", description=f"Removed **{_pretty_name(normalized)}** from starter elements.", color=_random_color())
        await ctx.send(embed=embed)

    @alchemy.command(name="setstarters")
    @commands.is_owner()
    async def set_starters(self, ctx: commands.Context, *, elements: str):
        parts = _split_key_string(elements)
        normalized = [_normalize(p) for p in parts if p]
        await self.config.starter_elements.set(sorted(list(set(normalized))))
        pretty = [f"• **{_pretty_name(e)}**" for e in sorted(normalized)]
        pages = chunk_items(pretty or ["Starter list cleared."], 30)
        await self._send_paginated(ctx, pages, title="Starter elements updated")

    # -------------------------
    # Auto-reimport controls and status
    # -------------------------
    @alchemy.command(name="setautoreimport")
    @commands.is_owner()
    async def set_autoreimport(self, ctx: commands.Context, mode: str, overwrite: Optional[str] = None):
        mode = mode.lower().strip()
        if mode not in ("on", "off"):
            embed = discord.Embed(title="Invalid mode", description="Use `on` or `off`.", color=_random_color())
            await ctx.send(embed=embed)
            return
        enabled = mode == "on"
        await self.config.auto_reimport_on_change.set(enabled)
        if overwrite is not None:
            ow = overwrite.lower().strip() in ("true", "yes", "1", "y")
            await self.config.auto_reimport_overwrite.set(ow)
        if enabled:
            self._start_watcher()
        else:
            self._stop_watcher()
        embed = discord.Embed(title="Auto re-import updated", description=f"Auto re-import set to **{mode}**. Overwrite on re-import is **{await self.config.auto_reimport_overwrite()}**.", color=_random_color())
        await ctx.send(embed=embed)

    @alchemy.command(name="lastimport")
    @commands.is_owner()
    async def last_import(self, ctx: commands.Context):
        summary = await self.config.last_import_summary()
        if not summary:
            embed = discord.Embed(title="No import summary", description="No imports have been recorded yet.", color=_random_color())
            await ctx.send(embed=embed)
            return
        lines = summary.splitlines()
        pages = chunk_items(lines, 30)
        await self._send_paginated(ctx, pages, title="Last import summary")

    # -------------------------
    # Cleanup
    # -------------------------
    def cog_unload(self):
        self._stop_watcher()
