import discord
from redbot.core import commands
from discord import app_commands
import os
import asyncio
import json
from typing import Dict, List, Optional, Tuple

COG_FOLDER = os.path.dirname(__file__)
STORAGE_PATH = os.path.join(COG_FOLDER, "adventures.txt")

# ------- Text import format description and example -------
EXAMPLE_TEXT = """# Example adventure file
# Multiple adventures separated by a line with exactly: ---
# Each adventure starts with metadata lines, then screens separated by ===
# Metadata fields:
# id: unique-id
# title: Human readable title
# description: Short description shown in selection embed
# thumbnail: thumbnail image url (optional)
#
# Screens section:
# Each screen starts with: screen: screen-id
# banner: banner-image-url (optional)
# text: The narrative text for this screen
# then one or more option lines in the form:
# emoji -> target-screen-id | Option label
#
# Example:
---
id: forest1
title: The Haunted Forest
description: Find your way out of the haunted forest.
thumbnail: https://i.imgur.com/xxx.png
===
screen: start
banner: https://i.imgur.com/banner.png
text: You wake up in a foggy forest. Two paths appear.
🙂 -> left | Take the left path
👉 -> right | Take the right path
===
screen: left
banner: https://i.imgur.com/left.png
text: The left path leads to a river. A boatman offers a ride.
🛶 -> boat | Take the boat
🧭 -> lost | Try to find another way
===
screen: right
banner: https://i.imgur.com/right.png
text: The right path leads deeper into the trees and a glowing cave.
🔥 -> cave | Enter the cave
🏃 -> run | Run away
===
screen: boat
text: The boat takes you to safety. THE END
===
screen: lost
text: You are lost forever. THE END
===
screen: cave
text: You find treasure. THE END
===
"""

# ----------------- Parser utilities -----------------
class ParseError(Exception):
    pass

def parse_adventures_from_text(text: str) -> Dict[str, dict]:
    """
    Parse the custom plain text adventure format and return a dict of adventures keyed by id.
    Raises ParseError on invalid format.
    """
    blocks = [b.strip() for b in text.split("\n---\n") if b.strip()]
    adventures = {}
    for block in blocks:
        lines = [l.rstrip() for l in block.splitlines() if l.strip() and not l.strip().startswith("#")]
        if not lines:
            continue

        # read metadata lines until a line === signifying screens start
        meta = {}
        screens_raw = []
        if "===" in lines:
            idx = lines.index("===")
            meta_lines = lines[:idx]
            screens_lines = lines[idx+1:]
        else:
            raise ParseError("Missing screens separator === for an adventure block.")

        for ln in meta_lines:
            if ":" not in ln:
                raise ParseError(f"Invalid metadata line: {ln}")
            k, v = ln.split(":", 1)
            meta[k.strip().lower()] = v.strip()

        if "id" not in meta or "title" not in meta or "description" not in meta:
            raise ParseError("Adventure metadata must include id, title, description.")

        # parse screens: screens are separated by lines starting with "===" inside screens_lines
        # We'll split by "===" occurrences — we already removed the first, so rejoin then split by "===".
        screens_text = "\n".join(screens_lines)
        screen_blocks = [s.strip() for s in screens_text.split("\n===\n") if s.strip()]
        screens = {}
        for sblock in screen_blocks:
            s_lines = [l for l in sblock.splitlines() if l.strip() and not l.strip().startswith("#")]
            if not s_lines:
                continue
            # first line should be: screen: screen-id
            if ":" not in s_lines[0]:
                raise ParseError(f"Missing screen header in block: {s_lines[0]}")
            k, v = s_lines[0].split(":", 1)
            if k.strip().lower() != "screen":
                raise ParseError(f"Expected 'screen' header, got: {k}")
            sid = v.strip()
            banner = None
            text_lines = []
            options = []
            for ln in s_lines[1:]:
                if ln.lower().startswith("banner:"):
                    banner = ln.split(":",1)[1].strip()
                    continue
                if ln.lower().startswith("text:"):
                    text_lines.append(ln.split(":",1)[1].strip())
                    continue
                # option line expected: emoji -> target | label
                if "->" in ln:
                    left, right = ln.split("->", 1)
                    emoji = left.strip()
                    if "|" not in right:
                        raise ParseError(f"Invalid option format, missing '|': {ln}")
                    target, label = right.split("|", 1)
                    options.append({
                        "emoji": emoji,
                        "target": target.strip(),
                        "label": label.strip()
                    })
                    continue
                # allow continuation of the text: lines that don't match above appended to text
                text_lines.append(ln)
            screens[sid] = {
                "id": sid,
                "banner": banner,
                "text": "\n".join(text_lines).strip(),
                "options": options
            }
        if "start" not in screens:
            # require a start screen
            raise ParseError("Each adventure must include a screen with id 'start'.")
        adv = {
            "id": meta["id"],
            "title": meta["title"],
            "description": meta["description"],
            "thumbnail": meta.get("thumbnail"),
            "screens": screens
        }
        adventures[meta["id"]] = adv
    return adventures

def adventures_to_text(adventures: Dict[str, dict]) -> str:
    parts = []
    for adv in adventures.values():
        meta = []
        meta.append(f"id: {adv['id']}")
        meta.append(f"title: {adv.get('title','')}")
        meta.append(f"description: {adv.get('description','')}")
        if adv.get("thumbnail"):
            meta.append(f"thumbnail: {adv['thumbnail']}")
        part = "\n".join(meta) + "\n===\n"
        screen_parts = []
        for screen in adv["screens"].values():
            sp = []
            sp.append(f"screen: {screen['id']}")
            if screen.get("banner"):
                sp.append(f"banner: {screen['banner']}")
            if screen.get("text"):
                # place all text on a single line prefixed with text:
                for line in screen['text'].splitlines():
                    sp.append(f"text: {line}")
            for opt in screen.get("options", []):
                sp.append(f"{opt['emoji']} -> {opt['target']} | {opt['label']}")
            screen_parts.append("\n".join(sp))
        part += "\n===\n".join(screen_parts)
        parts.append(part)
    return "\n---\n".join(parts)

# ----------------- Views -----------------
class ManageView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=120)
        self.cog = cog

    @discord.ui.button(label="Example", style=discord.ButtonStyle.secondary, custom_id="tale_example")
    async def example(self, interaction: discord.Interaction, button: discord.ui.Button):
        # send the example text file as a plain text attachment
        fp = discord.File(fp=EXAMPLE_TEXT.encode("utf-8"), filename="tale_example.txt")
        await interaction.response.send_message("Example format file attached.", file=fp, ephemeral=True)

    @discord.ui.button(label="Export", style=discord.ButtonStyle.secondary, custom_id="tale_export")
    async def export(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = self.cog.adventures
        if not data:
            await interaction.response.send_message("No adventures to export.", ephemeral=True)
            return
        content = adventures_to_text(data)
        fp = discord.File(fp=content.encode("utf-8"), filename="adventures.txt")
        await interaction.response.send_message("Exported adventures file attached.", file=fp, ephemeral=True)

    @discord.ui.button(label="Import", style=discord.ButtonStyle.primary, custom_id="tale_import")
    async def import_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Please upload a single .txt file as an attachment to this message within 60 seconds.",
            ephemeral=True
        )

        def check(m: discord.Message):
            return m.author.id == interaction.user.id and m.attachments

        try:
            msg = await self.cog.bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            await interaction.followup.send("Import timed out.", ephemeral=True)
            return

        attachment = msg.attachments[0]
        if not attachment.filename.lower().endswith(".txt"):
            await interaction.followup.send("Only .txt files are accepted.", ephemeral=True)
            return

        data = await attachment.read()
        try:
            text = data.decode("utf-8")
        except Exception:
            await interaction.followup.send("Failed to decode file as UTF-8 text.", ephemeral=True)
            return

        try:
            new = parse_adventures_from_text(text)
        except ParseError as e:
            await interaction.followup.send(f"Parse error: {e}", ephemeral=True)
            return

        # merge (overwrite adventures with same id)
        self.cog.adventures.update(new)
        await self.cog._save_to_disk()
        await interaction.followup.send(f"Imported {len(new)} adventure(s).", ephemeral=True)

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, custom_id="tale_delete")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.adventures:
            await interaction.response.send_message("No adventures to delete.", ephemeral=True)
            return

        options = [
            discord.SelectOption(label=v["title"], description=v["description"], value=k)
            for k, v in self.cog.adventures.items()
        ]

        select = DeleteSelect(self.cog, options)
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message("Choose an adventure to delete:", view=view, ephemeral=True)

class DeleteSelect(discord.ui.Select):
    def __init__(self, cog, options):
        super().__init__(placeholder="Select adventure to delete", min_values=1, max_values=1, options=options)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        aid = self.values[0]
        if aid in self.cog.adventures:
            del self.cog.adventures[aid]
            await self.cog._save_to_disk()
            await interaction.response.send_message(f"Deleted adventure `{aid}`.", ephemeral=True)
        else:
            await interaction.response.send_message("Adventure not found.", ephemeral=True)

class StartSelect(discord.ui.Select):
    def __init__(self, cog):
        options = [
            discord.SelectOption(label=v["title"], description=v["description"], value=k)
            for k, v in cog.adventures.items()
        ]
        super().__init__(placeholder="Choose an adventure...", min_values=1, max_values=1, options=options)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        aid = self.values[0]
        adv = self.cog.adventures.get(aid)
        if not adv:
            await interaction.response.send_message("Adventure not found.", ephemeral=True)
            return
        # send main embed for chosen adventure, then start at screen 'start'
        embed = discord.Embed(title=adv["title"], description=adv["description"], color=discord.Color.random())
        if adv.get("thumbnail"):
            embed.set_thumbnail(url=adv["thumbnail"])
        view = AdventureSessionView(self.cog, adv, current_screen_id="start")
        await interaction.response.send_message(embed=embed, view=view)

class AdventureChoiceButton(discord.ui.Button):
    def __init__(self, emoji: str, label: str, target: str, cog, adv):
        # Use secondary style; label is shown in tooltip (Discord shows custom label when no text)
        super().__init__(style=discord.ButtonStyle.secondary, label=label, emoji=emoji)
        self.target = target
        self.cog = cog
        self.adv = adv

    async def callback(self, interaction: discord.Interaction):
        view: AdventureSessionView = self.view  # type: ignore
        await view.goto_screen(interaction, self.target)

class AdventureSessionView(discord.ui.View):
    def __init__(self, cog, adventure: dict, current_screen_id: str):
        super().__init__(timeout=600)
        self.cog = cog
        self.adventure = adventure
        self.current = current_screen_id
        self.message: Optional[discord.Message] = None
        self.refresh_children_for_current()

    def refresh_children_for_current(self):
        # clear existing children and re-add based on current screen
        self.clear_items()
        screen = self.adventure["screens"].get(self.current)
        if not screen:
            return
        # add choice buttons
        if screen.get("options"):
            for opt in screen["options"]:
                emoji = opt.get("emoji") or None
                label = opt.get("label") or ""
                target = opt.get("target")
                btn = AdventureChoiceButton(emoji=emoji, label=label, target=target, cog=self.cog, adv=self.adventure)
                self.add_item(btn)
        # add a stop button
        self.add_item(StopButton())

    async def goto_screen(self, interaction: discord.Interaction, screen_id: str):
        screen = self.adventure["screens"].get(screen_id)
        if not screen:
            await interaction.response.send_message("Target screen not found; the adventure data might be invalid.", ephemeral=True)
            return
        self.current = screen_id
        # rebuild children for new screen
        self.refresh_children_for_current()
        embed = discord.Embed(title=f"{self.adventure['title']} — {screen_id}", color=discord.Color.random())
        if screen.get("banner"):
            embed.set_image(url=screen["banner"])
        if screen.get("text"):
            embed.description = screen["text"]
        await interaction.response.edit_message(embed=embed, view=self)

class StopButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="End", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        view: discord.ui.View = self.view  # type: ignore
        await interaction.response.edit_message(content="Session ended.", embed=None, view=None)

# ----------------- Cog -----------------
class TaleCog(commands.Cog):
    """Choose-your-own-adventure cog."""

    def __init__(self, bot):
        self.bot = bot
        # adventures: dict keyed by id
        self.adventures: Dict[str, dict] = {}
        # load on init
        try:
            self._load_from_disk()
        except Exception:
            self.adventures = {}

    def _load_from_disk(self):
        if not os.path.exists(STORAGE_PATH):
            self.adventures = {}
            return
        with open(STORAGE_PATH, "r", encoding="utf-8") as f:
            text = f.read()
        try:
            self.adventures = parse_adventures_from_text(text)
        except Exception:
            # if parsing fails, don't crash; keep empty
            self.adventures = {}

    async def _save_to_disk(self):
        # write current adventures in text format
        content = adventures_to_text(self.adventures)
        with open(STORAGE_PATH, "w", encoding="utf-8") as f:
            f.write(content)

    @commands.group()
    @commands.guild_only()
    async def tale(self, ctx: commands.Context):
        """Main group for the Tale cog."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help("tale")

    @tale.command()
    @commands.has_guild_permissions(administrator=True)
    async def manage(self, ctx: commands.Context):
        """Manage adventures: import, export, example, delete. Administrator only."""
        view = ManageView(self)
        await ctx.send("Tale management", view=view)

    @tale.command()
    async def start(self, ctx: commands.Context):
        """Start an adventure."""
        if not self.adventures:
            await ctx.send("No adventures are currently loaded. Use `tale manage` to import some.")
            return
        view = discord.ui.View()
        select = StartSelect(self)
        view.add_item(select)
        await ctx.send("Choose an adventure to start:", view=view)
