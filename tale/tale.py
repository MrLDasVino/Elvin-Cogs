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
# - Narrative text of a screen is given with one or more text: lines
# - Options are written as: <emoji> -> <target-screen-id> | <Option label>
# - Option can include [requires: flag1, flag2] to gate it, and/or [consumes: id] to make it one-use
# - Target screen ids must exist somewhere in the same adventure
# - A screen with id start is required and is the entry point
# - Lines beginning with # are comments and ignored by the parser
#
# New mechanics in this example:
# - gives: flag1, flag2  -> grants session flags (simple inventory/state) when the screen is visited
# - Option gating: append [requires: flag1, flag2] to an option label to show it only if flags are present
# - One-time options: append [consumes: id] to make an option disappear after it's used in a session
# - Flags are per-session and not persisted between sessions
#
--- 
id: tutorial-castle
title: The Small Castle with State
description: A gentle tutorial adventure showing format, branching, and simple state flags (gives/requires) and one-use options (consumes).
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
💰 -> give_coin | Offer the guard a coin [consumes: gave_coin]
✉️ -> show_letter | Show the guard a (fictitious) letter of passage [consumes: gave_letter]
❓ -> ask_permission | Ask for permission without giving anything
===
screen: give_coin
text: The guard pockets the coin and lets you pass. You enter the courtyard.
gives: has_coin
🏰 -> courtyard | Continue into the courtyard
===
screen: show_letter
text: The guard squints. He recognizes the seal and bows -- you are allowed in.
gives: has_letter
🏰 -> courtyard | Continue into the courtyard
===
screen: ask_permission
text: The guard shrugs, unimpressed. He refuses entry unless you wait for the captain.
🔁 -> start | Go back and choose another approach
===

# courtyard with a locked door that requires a key or letter
screen: courtyard
banner: https://i.imgur.com/banner_courtyard.png
text: The courtyard is quiet. To the left is the chapel; to the right, a door with a strange lock.
⛪ -> chapel | Explore the chapel
🔐 -> locked_door | Try the locked door
🔁 -> start | Return to the gate
===

screen: chapel
text: Inside the chapel is a small altar and a single candle. A folded note sits on the altar.
text: The note hides a small iron key you can take.
📝 -> read_note | Read the note
🗝️ -> take_key | Take the hidden iron key [consumes: chapel_took_key]
🔁 -> courtyard | Return to the courtyard
===

screen: read_note
text: The note reads: "The key is kept where the sun does not reach."
🔁 -> chapel | Think and return to the chapel
===

# Taking the key grants the has_key flag; this unlocks options that require it later
screen: take_key
text: You find a small iron key tucked into the note's fold.
gives: has_key
🔁 -> chapel | Return to the chapel with the key
===

# The locked door option exists but will only be useful if you have a key or a letter
screen: locked_door
text: The door has a puzzle lock. It seems keyed to a half-sun sigil or a letter of passage.
# Option that requires the key flag (AND semantics)
🔑 -> open_with_key | Use the iron key to open the locked door [requires: has_key]
# Option that requires the letter flag
✉️ -> open_with_letter | Show your letter to the lockkeeper [requires: has_letter]
🔁 -> courtyard | Return to the courtyard
===

screen: open_with_key
text: The key turns with a satisfying click. The door opens to a small treasure room.
💎 -> treasure | Take the treasure [consumes: took_treasure]
🔁 -> courtyard | Leave the treasure and return
===

screen: open_with_letter
text: The guard inspects the (fictitious) letter and finds it convincing. You're allowed in as if by key.
💎 -> treasure | Take the treasure [consumes: took_treasure]
🔁 -> courtyard | Return to courtyard
===

screen: treasure
text: You've found a small hoard of gems. You're richer now. THE END
🔚 -> good_ending | The adventure ends with riches
===

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

screen: good_ending
text: Wealth and fame follow you. THE END
🔚 -> good_ending_final | A triumphant ending
===

screen: bad_ending
text: You were defeated at the gate. THE END
🔚 -> bad_ending_final | A short bad ending
===

screen: peaceful_ending
text: You live a quiet life in the village and tell tales of the small castle. THE END
🔚 -> peaceful_ending_final | A calm ending
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
# Short example showing requires for branching and backtracking
id: forest-loop
title: The Twisting Wood with Flags and Consumables
description: A short, looping forest adventure enhanced with gives/requires mechanics and one-use options via consumes.
===
screen: start
banner: https://i.imgur.com/forest_start.png
text: You enter a forest where paths twist oddly. Three signs point in different directions.
⬅️ -> left_path | Take the left path
➡️ -> right_path | Take the right path
🔄 -> center_path | Take the center path
===

screen: left_path
text: The left path ends at a dead end, but you find a map pointing to a hidden glade and a token hidden in moss.
text: You can take the token to use later.
🗺️ -> glade | Follow the map to the glade
🪙 -> take_token | Take the hidden token [consumes: forest_token_1]
🔁 -> start | Return to the fork
===

screen: take_token
text: You slip the small carved token into your pocket.
gives: has_token
🔁 -> left_path | Return with token in hand
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
text: An old woodcutter offers you tea and a clue about a hidden glade and a test for tokens.
text: He will exchange a map for a token.
# This option requires you have the token and consumes it when trading
🗝️ -> trade_token | Trade the token for a map [requires: has_token; consumes: has_token]
🔁 -> stream | Return to the stream
===

screen: trade_token
text: You hand over the token; the woodcutter gives you a map showing the hidden glade.
gives: has_map
🔁 -> cottage | Return with the map
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

    # Split into adventure blocks where a line stripped equals '---' (accept whitespace)
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

    # Remove any blocks that are only comments/blank lines (not real adventures)
    filtered_blocks = []
    for b in blocks:
        has_content = False
        for line in b.splitlines():
            if line.strip() and not line.strip().startswith("#"):
                has_content = True
                break
        if has_content:
            filtered_blocks.append(b)
    blocks = filtered_blocks

    adventures: Dict[str, dict] = {}
    for block in blocks:
        raw_lines = [l for l in block.splitlines()]

        # Find explicit '===' separator if present (accept surrounding whitespace)
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
            gives = []  # flags granted when entering this screen
            for ln in s_lines[1:]:
                low = ln.lstrip().lower()
                if low.startswith("banner:"):
                    banner = ln.split(":", 1)[1].strip()
                    continue
                if low.startswith("text:"):
                    text_lines.append(ln.split(":", 1)[1].strip())
                    continue
                # new: optional gives: flag1, flag2
                if low.startswith("gives:"):
                    raw = ln.split(":", 1)[1].strip()
                    gives = [f.strip() for f in raw.split(",") if f.strip()]
                    continue
                if "->" in ln:
                    left, right = ln.split("->", 1)
                    emoji = left.strip()
                    if "|" not in right:
                        raise ParseError(f"Invalid option format, missing '|': {ln}")
                    target_label_part = right.split("|", 1)
                    target = target_label_part[0].strip()
                    label_and_req = target_label_part[1].strip()
                    # parse optional trailing bracketed directives, e.g. [requires: a, b] or [consumes: id]
                    reqs = []
                    consumes = None
                    if "[" in label_and_req and label_and_req.rstrip().endswith("]"):
                        idx = label_and_req.rfind("[")
                        bracket = label_and_req[idx+1:-1].strip()
                        label_text = label_and_req[:idx].rstrip()
                        # allow multiple directives separated by ';'
                        parts = [p.strip() for p in bracket.split(";") if p.strip()]
                        for part in parts:
                            low = part.lower()
                            if low.startswith("requires:"):
                                rawreqs = part.split(":", 1)[1]
                                reqs = [r.strip() for r in rawreqs.split(",") if r.strip()]
                            elif low.startswith("consumes:"):
                                consumes = part.split(":", 1)[1].strip()
                            else:
                                # unknown directive — treat whole bracket as label fallback
                                label_text = label_and_req
                    else:
                        label_text = label_and_req
                    options.append({"emoji": emoji, "target": target, "label": label_text, "requires": reqs, "consumes": consumes})
                    continue
                # Any other non-comment line treated as narrative continuation
                text_lines.append(ln)
            screens[sid] = {
                "id": sid,
                "banner": banner,
                "text": "\n".join(text_lines).strip(),
                "options": options,
                "gives": gives,
            }

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
        # options is already a list of discord.SelectOption; ensure descriptions are <=100 chars
        safe_options = []
        for opt in options:
            desc = (opt.description or "")[:100]
            if opt.description and len(opt.description) > 100:
                # preserve a visual clue that it's truncated
                desc = desc.rstrip()[:-1] + "…"
            safe_options.append(discord.SelectOption(label=opt.label, description=desc, value=opt.value))
        super().__init__(placeholder="Select adventure to delete", min_values=1, max_values=1, options=safe_options)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        aid = self.values[0]
        adv = self.cog.adventures.get(aid)
        if not adv:
            await interaction.response.send_message("Adventure not found.", ephemeral=True)
            return

        try:
            # remove the adventure and persist to disk
            del self.cog.adventures[aid]
            await self.cog._save_to_disk()
        except Exception:
            await interaction.response.send_message("Failed to delete the adventure.", ephemeral=True)
            return

        # confirm deletion to the administrator
        await interaction.response.send_message(f"Deleted adventure: **{adv.get('title', aid)}**.", ephemeral=True)


class StartSelect(discord.ui.Select):
    def __init__(self, cog):
        opts = []
        for k, v in cog.adventures.items():
            raw_desc = v.get("description", "") or ""
            if len(raw_desc) > 100:
                desc = raw_desc[:99].rstrip() + "…"
            else:
                desc = raw_desc
            opts.append(discord.SelectOption(label=v.get("title", k), description=desc, value=k))
        super().__init__(placeholder="Choose an adventure...", min_values=1, max_values=1, options=opts)
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
        view = AdventureSessionView(self.cog, adv, current_screen_id="start", owner_id=interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)
        try:
            msg = await interaction.original_response()
            view.message = msg
        except Exception:
            pass


class StartView(discord.ui.View):
    def __init__(self, cog, timeout: Optional[float] = 180):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.message: Optional[discord.Message] = None

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
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
        # mark this option's consumes id as used for this session so it disappears
        consumes = getattr(self, "_consumes", None)
        if consumes:
            view.consumed.add(consumes)
        await view.goto_screen(interaction, self.target)

class StopButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="End", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="Session ended.", embed=None, view=None)

class AdventureSessionView(discord.ui.View):
    def __init__(self, cog, adventure: dict, current_screen_id: str, owner_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.adventure = adventure
        self.current = current_screen_id
        self.message: Optional[discord.Message] = None
        self.flags = set()
        self.consumed = set()        
        # id of the user who started this session; only they may interact
        self.owner_id = owner_id
        self.refresh_children_for_current()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # allow the owner and the bot itself to interact; deny others with an ephemeral message
        if interaction.user.id == self.owner_id or interaction.user.id == self.cog.bot.user.id:
            return True
        try:
            await interaction.response.send_message("Only the player who started this session may use these controls.", ephemeral=True)
        except Exception:
            pass
        return False

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
                # skip option if it has a consumes id already consumed this session
                consumes = opt.get("consumes")
                if consumes and consumes in self.consumed:
                    continue
                # skip option if it has a consumes id already consumed this session
                consumes = opt.get("consumes")
                if consumes and consumes in self.consumed:
                    continue
                # only show option if all required flags are present (AND semantics)
                reqs = opt.get("requires", []) or []
                if reqs and not all((r in self.flags) for r in reqs):
                    continue
                emoji = opt.get("emoji")
                label = opt.get("label") or ""
                # ensure label is at most 80 characters (Discord limit)
                if label:
                    if len(label) > 80:
                        label = label[:79].rstrip() + "…"
                else:
                    label = None
                target = opt.get("target")
                btn = AdventureChoiceButton(emoji=emoji, label=label, target=target, cog=self.cog, adv=self.adventure)
                btn._consumes = consumes                
                self.add_item(btn)

    async def goto_screen(self, interaction: discord.Interaction, screen_id: str):
        screen = self.adventure["screens"].get(screen_id)
        if not screen:
            await interaction.response.send_message("Target screen not found; the adventure data might be invalid.", ephemeral=True)
            return
        self.current = screen_id
        # apply any flags granted by arriving at this screen
        for f in screen.get("gives", []) or []:
            if f:
                self.flags.add(f)        
        self.refresh_children_for_current()
        embed = discord.Embed(title=self.adventure['title'], color=discord.Color.random())
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

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    async def tale(self, ctx: commands.Context):
        """Main group for the Tale cog."""
        if ctx.invoked_subcommand is None:
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
        view = StartView(self, timeout=180)
        select = StartSelect(self)
        view.add_item(select)
        msg = await ctx.send("Choose an adventure to start:", view=view)
        view.message = msg

