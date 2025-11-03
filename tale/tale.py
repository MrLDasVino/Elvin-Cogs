import io
import os
import asyncio
from typing import Dict, Optional

import discord
from discord import app_commands
from redbot.core import commands

COG_FOLDER = os.path.dirname(__file__)
STORAGE_PATH = os.path.join(COG_FOLDER, "adventures.txt")

EXAMPLE_TEXT = """# Extended example adventure file for the Tale cog
# Notes:
# - Multiple adventures separated by a line with exactly: ---
# - Each adventure has metadata lines, then a screens section separated from metadata by ===
# - Metadata required: id, title, description
# - Optional metadata: thumbnail
# - Each screen block starts with: screen: screen-id
# - Optional per-screen field: banner: <image-url>
# - The narrative text of a screen is given with one or more text: lines
# - Options are written as: <emoji> -> <target-screen-id> | <Option label>
# - Target screen ids must exist somewhere in the same adventure
# - A screen with id start is required and is the entry point
# - Lines beginning with # are comments and ignored by the parser
#
# Example contains:
# - a tutorial-style beginning explaining parsed fields
# - branching choices, a trap route, a safe route, a simple "flag" mechanic shown as comment
# - several endings and a looped path demonstrating return to earlier screens
#
--- 
id: tutorial-castle
title: The Small Castle
description: A gentle tutorial adventure showing format and branching.
thumbnail: https://i.imgur.com/thumbnail_example.png
===
# start screen - entrance to the castle
screen: start
banner: https://i.imgur.com/banner_castle_gate.png
text: You stand before the rusted gates of a small castle. A tired guard eyes you.
text: He grunts and asks what you seek.
🙂 -> talk_guard | Speak politely to the guard
⚔️ -> fight_guard | Draw your sword and attack
🏃 -> leave | Leave and go to the nearby village
===
# If you talk, you may get inside peacefully
screen: talk_guard
banner: https://i.imgur.com/banner_guard.png
text: The guard relaxes when you speak politely. He asks if you have coin or a message.
text: You can offer a coin, show a letter, or ask for permission.
💰 -> give_coin | Offer the guard a coin
✉️ -> show_letter | Show the guard a (fictitious) letter of passage
❓ -> ask_permission | Ask for permission without giving anything
===
screen: give_coin
text: The guard pockets the coin and lets you pass. You enter the courtyard.
🏰 -> courtyard | Continue into the courtyard
===
screen: show_letter
text: The guard squints. He recognizes the seal and bows -- you are allowed in.
🏰 -> courtyard | Continue into the courtyard
===
screen: ask_permission
text: The guard shrugs, unimpressed. He refuses entry unless you wait for the captain.
🔁 -> start | Go back and choose another approach
===
# If you fight, things go badly
screen: fight_guard
banner: https://i.imgur.com/banner_sword.png
text: Attacking the guard draws alarm. More guards arrive. You are pushed out and wounded.
💀 -> bad_ending | You succumb to your wounds
🏃 -> leave | Try to flee to safety
===
screen: leave
text: You head to the village. The story ends for now; perhaps you'll try again another day.
🔚 -> peaceful_ending | The adventure ends peacefully in the village
===
screen: courtyard
banner: https://i.imgur.com/banner_courtyard.png
text: The courtyard is quiet. To the left is the chapel; to the right, a door with a strange lock.
⛪ -> chapel | Explore the chapel
🔐 -> locked_door | Try the locked door
===
screen: chapel
text: Inside the chapel is a small altar and a single candle. A folded note sits on the altar.
📝 -> read_note | Read the note
🔁 -> courtyard | Return to the courtyard
===
screen: read_note
text: The note reads: "The key is kept where the sun does not reach."
🔁 -> chapel | Think and return to the chapel (this is flavor)
===
screen: locked_door
text: The door has a puzzle lock. Below it is a faded inscription about shadows.
🕯️ -> use_candle | Use a candle to cast a shadow and try to reveal a key
🔁 -> courtyard | Return to the courtyard and search elsewhere
===
screen: use_candle
text: You place a candle and notice a seam in the wall where the shadow falls. Inside is a small iron key.
🔑 -> have_key | Take the key
🔁 -> locked_door | Inspect the door again
===
screen: have_key
text: You have obtained the iron key. (Note: this example shows a concept of obtaining an item; persistent inventory is not implemented in this format but can be simulated by branching to screens that require key.)
🔐 -> open_with_key | Use the key to open the locked door
🔁 -> courtyard | Explore elsewhere with key in hand
===
screen: open_with_key
text: The key turns with a satisfying click. The door opens to a small treasure room.
💎 -> treasure | Take the treasure
🔁 -> courtyard | Leave the treasure and return
===
screen: treasure
text: You've found a small hoard of gems. You're richer now. THE END
🔚 -> good_ending | The adventure ends with riches
===
screen: bad_ending
text: You were defeated at the gate. THE END
🔚 -> bad_ending_final | A short bad ending
===
screen: peaceful_ending
text: You live a quiet life in the village and tell tales of the small castle. THE END
🔚 -> peaceful_ending_final | A calm ending
===
screen: good_ending
text: Wealth and fame follow you. THE END
🔚 -> good_ending_final | A triumphant ending
===
screen: bad_ending_final
text: Your adventure is over. Better luck next time.
===
screen: peaceful_ending_final
text: You settle into peace. THE END
===
screen: good_ending_final
text: The kingdom sings of your name. THE END
===
---
# Second example adventure showing a short puzzle and loop
id: forest-loop
title: The Twisting Wood
description: A short, looping forest adventure that demonstrates returning to earlier screens.
===
screen: start
banner: https://i.imgur.com/forest_start.png
text: You enter a forest where paths twist oddly. Three signs point in different directions.
⬅️ -> left_path | Take the left path
➡️ -> right_path | Take the right path
🔄 -> center_path | Take the center path
===
screen: left_path
text: The left path ends at a dead end, but you find a map pointing to a hidden glade.
🗺️ -> glade | Follow the map to the glade
🔁 -> start | Return to the fork
===
screen: right_path
text: The right path loops back and you see familiar trees.
🔁 -> start | Return to the fork
===
screen: center_path
text: The center path slopes down to a stream with stepping stones.
💧 -> stream | Cross the stream
🔁 -> start | Go back up to the fork
===
screen: stream
text: The stones are slick, but you make it across and find a comforting cottage.
🏠 -> cottage | Knock on the door
🔁 -> center_path | Return to the center path
===
screen: cottage
text: An old woodcutter offers you tea and a clue about a hidden glade.
🗝️ -> clue | He points to a hollow oak where the glade sleeps
🔁 -> stream | Return to the stream
===
screen: glade
text: The hidden glade is peaceful. You rest and the adventure ends contentedly. THE END
🔚 -> glade_end | Restful ending
===
screen: glade_end
text: You leave the glade with calm memories. THE END
===
"""


class ParseError(Exception):
    pass

def parse_adventures_from_text(text: str) -> Dict[str, dict]:
    """
    Robust parser for the plain-text adventure format.
    - Splits adventures on lines that contain only '---' (ignoring surrounding whitespace)
    - Accepts either an explicit '===' separator between metadata and screens or will
      infer the split by finding the first 'screen:' header if '===' is missing
    - Ignores comment lines starting with '#'
    - Requires metadata fields: id, title, description
    - Requires a screen with id 'start'
    """
    # Normalize line endings and split
    lines = [ln.rstrip("\r") for ln in text.splitlines()]

    # Split into adventure blocks where a line stripped equals '---'
    blocks = []
    current = []
    for ln in lines:
        if ln.strip() == '---':
            if current:
                blocks.append("\n".join(current))
                current = []
            else:
                current = []
            continue
        current.append(ln)
    if current:
        blocks.append("\n".join(current))

    adventures: Dict[str, dict] = {}
    for block in blocks:
        raw_lines = [l for l in block.splitlines()]

        # Find explicit '===' separator if present
        sep_idx = None
        for i, l in enumerate(raw_lines):
            if l.strip() == '===':
                sep_idx = i
                break

        if sep_idx is not None:
            meta_raw = raw_lines[:sep_idx]
            screens_lines = raw_lines[sep_idx + 1 :]
        else:
            # Fallback: find the first 'screen:' line and treat everything before it as metadata
            first_screen_idx = None
            for i, l in enumerate(raw_lines):
                if l.strip().lower().startswith("screen:"):
                    first_screen_idx = i
                    break
            if first_screen_idx is None:
                raise ParseError("Missing screens separator === for an adventure block.")
            meta_raw = raw_lines[:first_screen_idx]
            screens_lines = raw_lines[first_screen_idx:]

        # Parse metadata (ignore comments/blank lines)
        meta_lines = [l for l in meta_raw if l.strip() and not l.strip().startswith("#")]
        meta = {}
        for ln in meta_lines:
            if ":" not in ln:
                raise ParseError(f"Invalid metadata line: {ln}")
            k, v = ln.split(":", 1)
            meta[k.strip().lower()] = v.strip()

        if "id" not in meta or "title" not in meta or "description" not in meta:
            raise ParseError("Adventure metadata must include id, title, description.")

        # Split screens by lines equal to '===' if present inside screens_lines
        screen_blocks = []
        cur_screen = []
        for ln in screens_lines:
            if ln.strip() == '===':
                if cur_screen:
                    screen_blocks.append("\n".join(cur_screen))
                    cur_screen = []
                else:
                    cur_screen = []
                continue
            cur_screen.append(ln)
        if cur_screen:
            screen_blocks.append("\n".join(cur_screen))

        screens = {}
        for sblock in screen_blocks:
            # Remove comments and blank lines inside a screen block
            s_lines = [l for l in sblock.splitlines() if l.strip() and not l.strip().startswith("#")]
            if not s_lines:
                continue
            # First line must be 'screen: id'
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
                low = ln.lstrip().lower()
                if low.startswith("banner:"):
                    banner = ln.split(":", 1)[1].strip()
                    continue
                if low.startswith("text:"):
                    text_lines.append(ln.split(":", 1)[1].strip())
                    continue
                if "->" in ln:
                    left, right = ln.split("->", 1)
                    emoji = left.strip()
                    if "|" not in right:
                        raise ParseError(f"Invalid option format, missing '|': {ln}")
                    target, label = right.split("|", 1)
                    options.append({"emoji": emoji, "target": target.strip(), "label": label.strip()})
                    continue
                # Any other non-comment line treated as narrative continuation
                text_lines.append(ln)
            screens[sid] = {"id": sid, "banner": banner, "text": "\n".join(text_lines).strip(), "options": options}

        if "start" not in screens:
            raise ParseError("Each adventure must include a screen with id 'start'.")

        adv = {
            "id": meta["id"],
            "title": meta["title"],
            "description": meta["description"],
            "thumbnail": meta.get("thumbnail"),
            "screens": screens,
        }
        adventures[meta["id"]] = adv

    return adventures




def adventures_to_text(adventures: Dict[str, dict]) -> str:
    parts = []
    for adv in adventures.values():
        meta = [f"id: {adv['id']}", f"title: {adv.get('title','')}", f"description: {adv.get('description','')}"]
        if adv.get("thumbnail"):
            meta.append(f"thumbnail: {adv['thumbnail']}")
        part = "\n".join(meta) + "\n===\n"
        screen_parts = []
        for screen in adv["screens"].values():
            sp = [f"screen: {screen['id']}"]
            if screen.get("banner"):
                sp.append(f"banner: {screen['banner']}")
            if screen.get("text"):
                for line in screen["text"].splitlines():
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
        super().__init__(timeout=60)
        self.cog = cog
        self.message: Optional[discord.Message] = None

    async def on_timeout(self):
        # disable all children and edit the original message to update view
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="Example", style=discord.ButtonStyle.secondary, custom_id="tale_example")
    async def example(self, interaction: discord.Interaction, button: discord.ui.Button):
        buf = io.BytesIO(EXAMPLE_TEXT.encode("utf-8"))
        fp = discord.File(fp=buf, filename="tale_example.txt")
        await interaction.response.send_message("Example format file attached.", file=fp, ephemeral=True)

    @discord.ui.button(label="Export", style=discord.ButtonStyle.secondary, custom_id="tale_export")
    async def export(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = self.cog.adventures
        if not data:
            await interaction.response.send_message("No adventures to export.", ephemeral=True)
            return
        content = adventures_to_text(data)
        buf = io.BytesIO(content.encode("utf-8"))
        fp = discord.File(fp=buf, filename="adventures.txt")
        await interaction.response.send_message("Exported adventures file attached.", file=fp, ephemeral=True)

    @discord.ui.button(label="Import", style=discord.ButtonStyle.primary, custom_id="tale_import")
    async def import_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Please upload a single .txt file as an attachment to this message within 60 seconds.",
            ephemeral=True,
        )

        def check(m: discord.Message):
            return m.author.id == interaction.user.id and m.attachments and m.channel.id == interaction.channel_id

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

        select_view = discord.ui.View(timeout=60)
        select = DeleteSelect(self.cog, options)
        select_view.add_item(select)
        await interaction.response.send_message("Choose an adventure to delete:", view=select_view, ephemeral=True)
        try:
            # set message reference so the view can edit on timeout
            msg = await interaction.original_response()
            select_view.message = msg
        except Exception:
            pass

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
        embed = discord.Embed(title=adv["title"], description=adv["description"], color=discord.Color.random())
        if adv.get("thumbnail"):
            embed.set_thumbnail(url=adv["thumbnail"])
        view = AdventureSessionView(self.cog, adv, current_screen_id="start")
        await interaction.response.send_message(embed=embed, view=view)
        try:
            msg = await interaction.original_response()
            view.message = msg
        except Exception:
            pass

class AdventureChoiceButton(discord.ui.Button):
    def __init__(self, emoji: str, label: str, target: str, cog, adv):
        super().__init__(style=discord.ButtonStyle.secondary, label=label or None, emoji=emoji or None)
        self.target = target
        self.cog = cog
        self.adv = adv

    async def callback(self, interaction: discord.Interaction):
        view: AdventureSessionView = self.view  # type: ignore
        await view.goto_screen(interaction, self.target)

class StopButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="End", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="Session ended.", embed=None, view=None)

class AdventureSessionView(discord.ui.View):
    def __init__(self, cog, adventure: dict, current_screen_id: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.adventure = adventure
        self.current = current_screen_id
        self.message: Optional[discord.Message] = None
        self.refresh_children_for_current()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    def refresh_children_for_current(self):
        self.clear_items()
        screen = self.adventure["screens"].get(self.current)
        if not screen:
            return
        if screen.get("options"):
            for opt in screen["options"]:
                emoji = opt.get("emoji")
                label = opt.get("label") or ""
                target = opt.get("target")
                btn = AdventureChoiceButton(emoji=emoji, label=label, target=target, cog=self.cog, adv=self.adventure)
                self.add_item(btn)
        self.add_item(StopButton())

    async def goto_screen(self, interaction: discord.Interaction, screen_id: str):
        screen = self.adventure["screens"].get(screen_id)
        if not screen:
            await interaction.response.send_message("Target screen not found; the adventure data might be invalid.", ephemeral=True)
            return
        self.current = screen_id
        self.refresh_children_for_current()
        embed = discord.Embed(title=f"{self.adventure['title']} — {screen_id}", color=discord.Color.random())
        if screen.get("banner"):
            embed.set_image(url=screen["banner"])
        if screen.get("text"):
            embed.description = screen["text"]
        await interaction.response.edit_message(embed=embed, view=self)

# ----------------- Cog -----------------
class TaleCog(commands.Cog):
    """Choose-your-own-adventure cog."""

    def __init__(self, bot):
        self.bot = bot
        self.adventures: Dict[str, dict] = {}
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
            self.adventures = {}

    async def _save_to_disk(self):
        content = adventures_to_text(self.adventures)
        with open(STORAGE_PATH, "w", encoding="utf-8") as f:
            f.write(content)

    @commands.group()
    @commands.guild_only()
    async def tale(self, ctx: commands.Context):
        """Main group for the Tale cog."""
        if ctx.invoked_subcommand is None:
            # show help for this command (only once)
            await ctx.send_help(ctx.command)
            return

    @tale.command()
    @commands.has_guild_permissions(administrator=True)
    async def manage(self, ctx: commands.Context):
        """Manage adventures: import, export, example, delete. Administrator only."""
        view = ManageView(self)
        msg = await ctx.send("Tale management", view=view)
        view.message = msg

    @tale.command()
    async def start(self, ctx: commands.Context):
        """Start an adventure."""
        if not self.adventures:
            await ctx.send("No adventures are currently loaded. Use `tale manage` to import some.")
            return
        view = discord.ui.View(timeout=60)
        select = StartSelect(self)
        view.add_item(select)
        msg = await ctx.send("Choose an adventure to start:", view=view)
        # store message so view can be edited on timeout
        view.message = msg
