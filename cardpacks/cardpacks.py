import io
import random
from typing import Optional, Dict, List, Tuple
from collections import defaultdict, Counter
from urllib.parse import urlparse

import discord
from discord import ui
from redbot.core import commands, bank, checks, Config

DEFAULT = {"packs": {}, "inventories": {}}

INVENTORY_BANNER_URLS = [
    "https://files.catbox.moe/55yfxz.jpg",
]

PAGE_SIZE = 25
EMBED_FIELD_LIMIT = 24
PACKS_PER_EMBED_PAGE = 5
PACK_STACK_LIMIT = 6


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1].rstrip() + "…"


def _valid_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = str(url).strip()
    if not url or url.lower() in ("none", "null", "n/a"):
        return None
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return url
    return None


def _rarity_weights_map(packs: Dict[str, dict], pack_name: str) -> Dict[str, int]:
    pack = packs.get(pack_name, {})
    rw = pack.get("rarity_weights")
    if rw and isinstance(rw, dict):
        return {k: int(v) for k, v in rw.items()}
    counts: Dict[str, int] = {}
    for c in pack.get("cards", []):
        r = c.get("rarity", "common")
        counts[r] = counts.get(r, 0) + 1
    if not counts:
        return {}
    return {k: max(1, v) for k, v in counts.items()}


def _parse_card_line(body: str) -> dict:
    parts = [p.strip() for p in body.split("|")]
    name = parts[0] if parts else ""
    text_part = parts[1] if len(parts) > 1 else ""
    rarity = "common"
    chance = None
    image = ""

    for tail in parts[2:]:
        if "rarity:" in tail:
            rarity = tail.split("rarity:", 1)[1].split("chance:")[0].split("image:")[0].strip() or rarity
        if "chance:" in tail:
            raw = tail.split("chance:", 1)[1].split("image:")[0].strip()
            if raw.endswith("%"):
                raw = raw[:-1].strip()
            try:
                chance = float(raw)
            except ValueError:
                chance = None
        if "image:" in tail:
            image = tail.split("image:", 1)[1].strip()

    card = {"name": name, "text": text_part, "image": image, "rarity": rarity}
    if chance is not None:
        card["chance"] = chance
    return card


def _format_card_line(c: dict) -> str:
    segments = [c.get("name", ""), c.get("text", "")]
    meta = f"rarity: {c.get('rarity', 'common')}"
    if c.get("chance") is not None:
        meta += f" chance: {c.get('chance')}%"
    segments.append(meta)
    image = c.get("image")
    if image:
        segments.append(f"image: {image}")
    return "- " + " | ".join(segments)


def _parse_pack_export(text: str) -> Dict[str, dict]:
    packs_raw: Dict[str, dict] = {}
    current = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("==") and line.endswith("=="):
            pname = line.strip("=").strip()
            current = {"price": 0, "description": "", "pull_count": 5, "thumbnail": None, "cards": []}
            packs_raw[pname] = current
            continue
        if current is None:
            continue
        if line.startswith("price:"):
            try:
                current["price"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                current["price"] = 0
            continue
        if line.startswith("desc:"):
            current["description"] = line.split(":", 1)[1].strip()
            continue
        if line.startswith("pulls:"):
            try:
                current["pull_count"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                current["pull_count"] = 1
            continue
        if line.startswith("thumbnail:"):
            current["thumbnail"] = _valid_url(line.split(":", 1)[1].strip())
            continue
        if line.startswith("- "):
            current["cards"].append(_parse_card_line(line[2:].strip()))

    return packs_raw


async def _require_manager(interaction: discord.Interaction) -> bool:
    member = interaction.user
    guild = interaction.guild
    if guild is None or not isinstance(member, discord.Member):
        return False
    if member == guild.owner or member.guild_permissions.manage_guild:
        return True
    await interaction.response.send_message("You don't have permission to do that.", ephemeral=True)
    return False


class TimedView(ui.View):
    """Generic timed view that disables children and edits the message on timeout."""

    async def on_timeout(self):
        for child in self.children:
            try:
                child.disabled = True
            except Exception:
                pass
        msg = getattr(self, "message", None)
        if msg:
            try:
                await msg.edit(view=self)
            except Exception:
                pass


class ManagerView(TimedView):
    """A TimedView restricted to server owners/managers."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _require_manager(interaction)


class PaginatedSelectView(TimedView):
    """A select dropdown that pages through entries in chunks of PAGE_SIZE.
    Arrow buttons only appear when there's more than one page."""

    def __init__(self, entries: List[Tuple[str, Optional[str], str]], placeholder: str, on_select, *, timeout: int = 60, owner_id: Optional[int] = None):
        super().__init__(timeout=timeout)
        self.entries = entries
        self.placeholder = placeholder
        self.on_select = on_select
        self.owner_id = owner_id
        self.page = 0
        self._render()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.owner_id is not None and interaction.user.id != self.owner_id:
            await interaction.response.send_message("This isn't your menu to use.", ephemeral=True)
            return False
        return True

    @property
    def page_count(self) -> int:
        return max(1, -(-len(self.entries) // PAGE_SIZE))

    def _render(self):
        self.clear_items()
        start = self.page * PAGE_SIZE
        page_entries = self.entries[start:start + PAGE_SIZE]

        options = []
        for label, desc, value in page_entries:
            kwargs = {"label": _truncate(label, 100), "value": value}
            if desc:
                kwargs["description"] = _truncate(desc, 100)
            options.append(discord.SelectOption(**kwargs))

        select = ui.Select(placeholder=self.placeholder, min_values=1, max_values=1, options=options, row=0)

        async def _select_cb(interaction: discord.Interaction):
            await self.on_select(interaction, select.values[0])

        select.callback = _select_cb
        self.add_item(select)

        if len(self.entries) > PAGE_SIZE:
            prev_btn = ui.Button(label="◀", style=discord.ButtonStyle.secondary, disabled=self.page == 0, row=1)
            next_btn = ui.Button(label="▶", style=discord.ButtonStyle.secondary, disabled=self.page >= self.page_count - 1, row=1)

            async def _prev_cb(interaction: discord.Interaction):
                self.page = max(0, self.page - 1)
                self._render()
                await interaction.response.edit_message(view=self)

            async def _next_cb(interaction: discord.Interaction):
                self.page = min(self.page_count - 1, self.page + 1)
                self._render()
                await interaction.response.edit_message(view=self)

            prev_btn.callback = _prev_cb
            next_btn.callback = _next_cb
            self.add_item(prev_btn)
            self.add_item(next_btn)


class PaginatedManagerSelectView(PaginatedSelectView):
    """PaginatedSelectView restricted to server owners/managers."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _require_manager(interaction)


class InventoryView(TimedView):
    """Paginated inventory display: flips through pack-summary embed pages and
    offers a (separately paginated) dropdown to view any owned card's artwork."""

    def __init__(self, owner_id: int, pack_pages: List[discord.Embed], card_entries: List[Tuple[str, Optional[str], dict]], build_card_embed, *, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.pack_pages = pack_pages
        self.card_entries = card_entries
        self.build_card_embed = build_card_embed
        self.embed_page = 0
        self.select_page = 0
        self._render()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This isn't your inventory menu.", ephemeral=True)
            return False
        return True

    @property
    def select_page_count(self) -> int:
        return max(1, -(-len(self.card_entries) // PAGE_SIZE))

    def current_embed(self) -> discord.Embed:
        return self.pack_pages[self.embed_page]

    def _render(self):
        self.clear_items()

        if self.card_entries:
            start = self.select_page * PAGE_SIZE
            chunk = self.card_entries[start:start + PAGE_SIZE]
            options = []
            for i, (label, desc, _payload) in enumerate(chunk):
                kwargs = {"label": _truncate(label, 100), "value": str(start + i)}
                if desc:
                    kwargs["description"] = _truncate(desc, 100)
                options.append(discord.SelectOption(**kwargs))

            select = ui.Select(placeholder="View a card", min_values=1, max_values=1, options=options, row=0)

            async def _select_cb(interaction: discord.Interaction):
                idx = int(select.values[0])
                _, _, payload = self.card_entries[idx]
                embed = self.build_card_embed(payload)
                await interaction.response.send_message(embed=embed, ephemeral=True)

            select.callback = _select_cb
            self.add_item(select)

        if len(self.pack_pages) > 1:
            prev_btn = ui.Button(label="◀ Packs", style=discord.ButtonStyle.secondary, disabled=self.embed_page == 0, row=1)
            next_btn = ui.Button(label="Packs ▶", style=discord.ButtonStyle.secondary, disabled=self.embed_page >= len(self.pack_pages) - 1, row=1)

            async def _prev_cb(interaction: discord.Interaction):
                self.embed_page = max(0, self.embed_page - 1)
                self._render()
                await interaction.response.edit_message(embed=self.current_embed(), view=self)

            async def _next_cb(interaction: discord.Interaction):
                self.embed_page = min(len(self.pack_pages) - 1, self.embed_page + 1)
                self._render()
                await interaction.response.edit_message(embed=self.current_embed(), view=self)

            prev_btn.callback = _prev_cb
            next_btn.callback = _next_cb
            self.add_item(prev_btn)
            self.add_item(next_btn)

        if len(self.card_entries) > PAGE_SIZE:
            prev_sel = ui.Button(label="◀ Cards", style=discord.ButtonStyle.secondary, disabled=self.select_page == 0, row=2)
            next_sel = ui.Button(label="Cards ▶", style=discord.ButtonStyle.secondary, disabled=self.select_page >= self.select_page_count - 1, row=2)

            async def _prev_sel_cb(interaction: discord.Interaction):
                self.select_page = max(0, self.select_page - 1)
                self._render()
                await interaction.response.edit_message(view=self)

            async def _next_sel_cb(interaction: discord.Interaction):
                self.select_page = min(self.select_page_count - 1, self.select_page + 1)
                self._render()
                await interaction.response.edit_message(view=self)

            prev_sel.callback = _prev_sel_cb
            next_sel.callback = _next_sel_cb
            self.add_item(prev_sel)
            self.add_item(next_sel)


class PackCreateModal(ui.Modal, title="Create pack"):
    name = ui.TextInput(label="Pack name", max_length=100)
    price = ui.TextInput(label="Price (integer)", default="0", max_length=20)
    description = ui.TextInput(label="Short description", required=False, max_length=200)
    pull_count = ui.TextInput(label="Cards pulled on buy (integer, default 5)", default="5", max_length=3, required=False)
    thumbnail_url = ui.TextInput(label="Optional thumbnail URL (max 200 chars)", required=False, max_length=200)

    def __init__(self, cog: "CardPacks"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price_val = int(self.price.value)
        except ValueError:
            await interaction.response.send_message("Price must be an integer.", ephemeral=True)
            return

        try:
            pull_val = int(self.pull_count.value) if self.pull_count.value.strip() else 5
            if pull_val < 1:
                raise ValueError
        except Exception:
            await interaction.response.send_message("Cards pulled must be a positive integer.", ephemeral=True)
            return

        thumbnail = _valid_url(self.thumbnail_url.value)
        try:
            await self.cog._create_pack(interaction.guild, self.name.value, price_val, self.description.value, None, pull_val, thumbnail)
        except commands.BadArgument as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await interaction.response.send_message(f"Pack **{self.name.value}** created (pulls: {pull_val}).", ephemeral=True)


class EditPackModal(ui.Modal, title="Edit pack"):
    name = ui.TextInput(label="Pack name", max_length=100)
    price = ui.TextInput(label="Price (integer)", max_length=20)
    description = ui.TextInput(label="Short description", required=False, max_length=200)
    pull_count = ui.TextInput(label="Cards pulled on buy (integer)", max_length=3, required=False)
    thumbnail_url = ui.TextInput(label="Optional thumbnail URL (max 200 chars)", required=False, max_length=200)

    def __init__(self, cog: "CardPacks", original_pack_name: str, pack_data: dict):
        super().__init__()
        self.cog = cog
        self.original_pack_name = original_pack_name

        self.name.default = original_pack_name
        self.price.default = str(pack_data.get("price", 0))
        self.description.default = pack_data.get("description", "")
        self.pull_count.default = str(pack_data.get("pull_count", 5))
        self.thumbnail_url.default = pack_data.get("thumbnail") or ""

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.name.value.strip()
        try:
            price_val = int(self.price.value)
        except ValueError:
            await interaction.response.send_message("Price must be an integer.", ephemeral=True)
            return

        try:
            pull_val = int(self.pull_count.value) if self.pull_count.value.strip() else 5
            if pull_val < 1:
                raise ValueError
        except Exception:
            await interaction.response.send_message("Cards pulled must be a positive integer.", ephemeral=True)
            return

        thumbnail = _valid_url(self.thumbnail_url.value)
        try:
            await self.cog._edit_pack(interaction.guild, self.original_pack_name, new_name, price_val, self.description.value, pull_val, thumbnail)
        except commands.BadArgument as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await interaction.response.send_message(f"Pack **{self.original_pack_name}** updated to **{new_name}**.", ephemeral=True)


class CardAddModal(ui.Modal, title="Add card to pack"):
    name = ui.TextInput(label="Card name", max_length=100)
    text = ui.TextInput(label="Card text", style=discord.TextStyle.long, required=False)
    image_url = ui.TextInput(label="Image URL (optional)", required=False)
    rarity = ui.TextInput(label="Rarity (optional)", required=False)
    pull_chance = ui.TextInput(label="Pull chance % (e.g. 0.5)", required=False, max_length=20)

    def __init__(self, cog: "CardPacks", pack_name: str):
        super().__init__()
        self.cog = cog
        self.pack_name = pack_name

    async def on_submit(self, interaction: discord.Interaction):
        rarity_val = self.rarity.value.strip() or "common"
        chance_raw = self.pull_chance.value.strip()
        chance_val = None
        if chance_raw:
            try:
                chance_val = float(chance_raw)
            except ValueError:
                await interaction.response.send_message("Pull chance must be a number (percent).", ephemeral=True)
                return
            if chance_val < 0 or chance_val > 100:
                await interaction.response.send_message("Pull chance must be between 0 and 100.", ephemeral=True)
                return

        card = {"name": self.name.value, "text": self.text.value, "image": self.image_url.value, "rarity": rarity_val}
        if chance_val is not None:
            card["chance"] = chance_val

        try:
            await self.cog._add_card_to_pack(interaction.guild, self.pack_name, card)
        except commands.BadArgument as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        added_msg = f"Added card **{card['name']}** (rarity: {rarity_val}"
        if chance_val is not None:
            added_msg += f"; chance: {chance_val}%"
        added_msg += f") to **{self.pack_name}**."
        await interaction.response.send_message(added_msg, ephemeral=True)


class EditCardModal(ui.Modal, title="Edit card"):
    name = ui.TextInput(label="Card name", max_length=100)
    text = ui.TextInput(label="Card text", style=discord.TextStyle.long, required=False)
    image_url = ui.TextInput(label="Image URL (optional)", required=False)
    rarity = ui.TextInput(label="Rarity (optional)", required=False)
    pull_chance = ui.TextInput(label="Pull chance % (e.g. 0.5)", required=False, max_length=20)

    def __init__(self, cog: "CardPacks", pack_name: str, card_index: int, card_data: dict):
        super().__init__()
        self.cog = cog
        self.pack_name = pack_name
        self.card_index = card_index
        self.name.default = card_data.get("name", "")
        self.text.default = card_data.get("text", "")
        self.image_url.default = card_data.get("image", "")
        self.rarity.default = card_data.get("rarity", "common")
        self.pull_chance.default = str(card_data.get("chance")) if card_data.get("chance") is not None else ""

    async def on_submit(self, interaction: discord.Interaction):
        chance_raw = self.pull_chance.value.strip()
        chance_val = None
        if chance_raw:
            try:
                chance_val = float(chance_raw)
            except ValueError:
                await interaction.response.send_message("Pull chance must be a number (percent).", ephemeral=True)
                return
            if chance_val < 0 or chance_val > 100:
                await interaction.response.send_message("Pull chance must be between 0 and 100.", ephemeral=True)
                return

        card = {"name": self.name.value, "text": self.text.value, "image": self.image_url.value, "rarity": self.rarity.value.strip() or "common"}
        if chance_val is not None:
            card["chance"] = chance_val
        try:
            await self.cog._edit_card_in_pack(interaction.guild, self.pack_name, self.card_index, card)
        except commands.BadArgument as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await interaction.response.send_message(f"Card **{card['name']}** updated in **{self.pack_name}**.", ephemeral=True)


class PurgeModal(ui.Modal, title="Purge inventories"):
    who = ui.TextInput(label="User mention, ID, or exact name", required=False, max_length=200)

    def __init__(self, cog: "CardPacks"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This command can only be used in a guild.", ephemeral=True)
            return

        who_raw = self.who.value.strip()
        if not who_raw:
            try:
                await self.cog._purge_all_inventories(guild)
            except Exception as e:
                await interaction.response.send_message(f"Failed to purge inventories: {e}", ephemeral=True)
                return
            await interaction.response.send_message("All inventories in this server have been reset.", ephemeral=True)
            return

        member = None
        if who_raw.startswith("<@") and who_raw.endswith(">"):
            try:
                mention_id = int(who_raw.strip("<@!>"))
                member = guild.get_member(mention_id)
            except Exception:
                member = None
        else:
            try:
                member_id = int(who_raw)
                member = guild.get_member(member_id)
            except Exception:
                member = None

        if not member:
            try:
                member = guild.get_member_named(who_raw)
            except Exception:
                member = None

        if not member:
            lowered = who_raw.lower()
            for m in guild.members:
                if (m.display_name or "").lower() == lowered or (m.name or "").lower() == lowered:
                    member = m
                    break

        if not member:
            await interaction.response.send_message("Could not resolve that user in this guild. Use a mention, ID, or exact username/display name.", ephemeral=True)
            return

        try:
            await self.cog._purge_inventory_for_user(guild, member)
        except Exception as e:
            await interaction.response.send_message(f"Failed to purge inventory: {e}", ephemeral=True)
            return

        await interaction.response.send_message(f"Inventory for {member.display_name} has been reset.", ephemeral=True)


class ImportModal(ui.Modal, title="Import packs (paste export text)"):
    data = ui.TextInput(label="Export text", style=discord.TextStyle.long, placeholder="Paste the text you get from Export packs", required=True)

    def __init__(self, cog: "CardPacks"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        parsed = _parse_pack_export(self.data.value)
        if not parsed:
            await interaction.response.send_message("No packs found in that text.", ephemeral=True)
            return
        try:
            created, updated = await self.cog._apply_imported_packs(interaction.guild, parsed)
        except Exception as e:
            await interaction.response.send_message(f"Import failed: {e}", ephemeral=True)
            return
        await interaction.response.send_message(f"Import complete. Packs created: {created}, packs updated: {updated}", ephemeral=True)


class EditPackButton(ui.Button):
    def __init__(self, cog: "CardPacks", pack_name: str):
        super().__init__(label="Edit pack", style=discord.ButtonStyle.primary)
        self.cog = cog
        self.pack_name = pack_name

    async def callback(self, interaction: discord.Interaction):
        pack = await self.cog._get_pack(interaction.guild, self.pack_name)
        if not pack:
            await interaction.response.send_message("Pack not found.", ephemeral=True)
            return
        await interaction.response.send_modal(EditPackModal(self.cog, self.pack_name, pack))


class DeletePackButton(ui.Button):
    def __init__(self, cog: "CardPacks", pack_name: str):
        super().__init__(label="Delete pack", style=discord.ButtonStyle.danger)
        self.cog = cog
        self.pack_name = pack_name

    async def callback(self, interaction: discord.Interaction):
        view = ManagerView(timeout=60)
        view.add_item(ConfirmDeletePackButton(self.cog, self.pack_name))
        view.add_item(CancelSimpleButton())
        await interaction.response.send_message(f"Are you sure you want to DELETE pack **{self.pack_name}**? This cannot be undone.", view=view, ephemeral=True)


class ConfirmDeletePackButton(ui.Button):
    def __init__(self, cog: "CardPacks", pack_name: str):
        super().__init__(label="Confirm delete", style=discord.ButtonStyle.danger)
        self.cog = cog
        self.pack_name = pack_name

    async def callback(self, interaction: discord.Interaction):
        try:
            await self.cog._delete_pack(interaction.guild, self.pack_name)
        except commands.BadArgument as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await interaction.response.send_message(f"Pack **{self.pack_name}** deleted.", ephemeral=True)


class ViewCardButton(ui.Button):
    def __init__(self, cog: "CardPacks", pack_name: str, card_index: int):
        super().__init__(label="View card", style=discord.ButtonStyle.secondary)
        self.cog = cog
        self.pack_name = pack_name
        self.card_index = card_index

    async def callback(self, interaction: discord.Interaction):
        pack = await self.cog._get_pack(interaction.guild, self.pack_name)
        cards = pack.get("cards", []) if pack else []
        if self.card_index < 0 or self.card_index >= len(cards):
            await interaction.response.send_message("Card not found.", ephemeral=True)
            return
        embed = self.cog._build_card_embed(self.pack_name, cards[self.card_index])
        await interaction.response.send_message(embed=embed, ephemeral=True)


class EditCardButton(ui.Button):
    def __init__(self, cog: "CardPacks", pack_name: str, card_index: int):
        super().__init__(label="Edit card", style=discord.ButtonStyle.primary)
        self.cog = cog
        self.pack_name = pack_name
        self.card_index = card_index

    async def callback(self, interaction: discord.Interaction):
        packs = await self.cog._get_all_packs(interaction.guild)
        pack = packs.get(self.pack_name)
        if not pack:
            await interaction.response.send_message("Pack not found.", ephemeral=True)
            return
        cards = pack.get("cards", [])
        if self.card_index < 0 or self.card_index >= len(cards):
            await interaction.response.send_message("Card not found.", ephemeral=True)
            return
        card = cards[self.card_index]
        await interaction.response.send_modal(EditCardModal(self.cog, self.pack_name, self.card_index, card))


class DeleteCardButton(ui.Button):
    def __init__(self, cog: "CardPacks", pack_name: str, card_index: int):
        super().__init__(label="Delete card", style=discord.ButtonStyle.danger)
        self.cog = cog
        self.pack_name = pack_name
        self.card_index = card_index

    async def callback(self, interaction: discord.Interaction):
        view = ManagerView(timeout=60)
        view.add_item(ConfirmDeleteCardButton(self.cog, self.pack_name, self.card_index))
        view.add_item(CancelSimpleButton())
        await interaction.response.send_message("Confirm deletion of this card?", view=view, ephemeral=True)


class ConfirmDeleteCardButton(ui.Button):
    def __init__(self, cog: "CardPacks", pack_name: str, card_index: int):
        super().__init__(label="Confirm delete", style=discord.ButtonStyle.danger)
        self.cog = cog
        self.pack_name = pack_name
        self.card_index = card_index

    async def callback(self, interaction: discord.Interaction):
        try:
            await self.cog._delete_card_from_pack(interaction.guild, self.pack_name, self.card_index)
        except commands.BadArgument as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await interaction.response.send_message("Card deleted.", ephemeral=True)


class CancelSimpleButton(ui.Button):
    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="Cancelled.", view=None)


class ConfirmBuyView(TimedView):
    BANNER_URLS = [
        "https://files.catbox.moe/nn9wpx.jpg",
        "https://files.catbox.moe/vyvmr2.jpg",
        "https://files.catbox.moe/143g4d.jpg",
        "https://files.catbox.moe/m9tx00.jpg",
        "https://files.catbox.moe/kozsri.jpg",
        "https://files.catbox.moe/xr5r0l.jpg",
        "https://files.catbox.moe/8wvnsf.jpg",
    ]

    def __init__(self, cog: "CardPacks", pack_name: str, price: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.pack_name = pack_name
        self.price = price

    def _pull_cards(self, cards: List[dict], rarity_map: Dict[str, int], pull_count: int) -> List[dict]:
        pulled = []
        for _ in range(max(1, pull_count)):
            cards_with_chance = [c for c in cards if c.get("chance") is not None]
            if cards_with_chance:
                weights = [float(c.get("chance", 0.0)) for c in cards]
                chosen = random.choices(cards, weights=weights, k=1)[0] if sum(weights) > 0 else random.choice(cards)
            elif rarity_map:
                rarities = list(rarity_map.keys())
                weights = [rarity_map[r] for r in rarities]
                chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]
                candidates = [c for c in cards if c.get("rarity", "common") == chosen_rarity]
                chosen = random.choice(candidates) if candidates else random.choice(cards)
            else:
                chosen = random.choice(cards)
            pulled.append(dict(chosen))
        return pulled

    async def _build_reveal_embed(self, interaction: discord.Interaction, pulled: List[dict], pack: dict) -> discord.Embed:
        banner = random.choice(self.BANNER_URLS) if self.BANNER_URLS else None
        embed = discord.Embed(
            title=f"{interaction.user.display_name} opened {self.pack_name}!",
            description=f"A shiny new pack has been opened by **{interaction.user.display_name}**.",
            color=discord.Color.random(),
        )
        if banner:
            embed.set_image(url=banner)

        thumbnail = _valid_url(pack.get("thumbnail"))
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        embed.add_field(name="Result", value=f"Pulled {len(pulled)} card(s) from **{self.pack_name}**", inline=False)

        for idx, c in enumerate(pulled, start=1):
            name = c.get("name", "Unknown")
            rarity = c.get("rarity", "common")
            text = c.get("text", "")
            chance_info = f" | Chance: {c.get('chance')}%" if c.get("chance") is not None else ""
            lines = []
            if text:
                lines.append(text.splitlines()[0])
            lines.append(f"Rarity: **{rarity}**{chance_info}")
            img = c.get("image")
            if img:
                lines.append(img)
            embed.add_field(name=f"{idx}. {name}", value="\n".join(lines), inline=False)

        currency = await bank.get_currency_name(interaction.guild)
        embed.set_footer(text=f"Bought for {self.price} {currency}")
        embed.timestamp = discord.utils.utcnow()
        return embed

    @ui.button(label="Confirm", style=discord.ButtonStyle.green, custom_id="cardpacks_confirm_buy")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        try:
            await bank.withdraw_credits(interaction.user, self.price)
        except Exception as e:
            await interaction.response.send_message(f"Purchase failed: {e}", ephemeral=True)
            return

        pack = await self.cog._get_pack(interaction.guild, self.pack_name)
        cards = pack.get("cards", []) if pack else []
        if not cards:
            try:
                await bank.deposit_credits(interaction.user, self.price)
            except Exception:
                pass
            await interaction.response.send_message(
                f"Pack **{self.pack_name}** contained no cards. Refunding.", ephemeral=True
            )
            return

        packs_all = await self.cog._get_all_packs(interaction.guild)
        rarity_map = _rarity_weights_map(packs_all, self.pack_name)
        pull_count = int(pack.get("pull_count", 5))
        pulled = self._pull_cards(cards, rarity_map, pull_count)

        for card in pulled:
            await self.cog._add_card_to_user(interaction.guild, interaction.user, card, source_pack=self.pack_name)

        embed = await self._build_reveal_embed(interaction, pulled, pack)

        try:
            await interaction.response.send_message(embed=embed, ephemeral=False)
        except discord.HTTPException:
            await interaction.response.send_message(
                f"Pulled {len(pulled)} card(s) from **{self.pack_name}**! (couldn't post the full reveal embed)",
                ephemeral=True,
            )

    @ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cardpacks_cancel_buy")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Purchase cancelled.", ephemeral=True)


class ManageView(ManagerView):
    def __init__(self, cog: "CardPacks"):
        super().__init__(timeout=60)
        self.cog = cog

    @ui.button(label="Create pack", style=discord.ButtonStyle.primary, custom_id="cardpacks_create_pack", row=0)
    async def create_pack(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(PackCreateModal(self.cog))

    @ui.button(label="List packs", style=discord.ButtonStyle.secondary, custom_id="cardpacks_list_packs", row=0)
    async def list_packs(self, interaction: discord.Interaction, button: ui.Button):
        packs = await self.cog._get_all_packs(interaction.guild)
        if not packs:
            await interaction.response.send_message("No packs configured.", ephemeral=True)
            return

        embed = discord.Embed(title="Configured Packs", color=discord.Color.blue())
        embed.description = f"Total packs: **{len(packs)}**"

        for pdata in packs.values():
            thumb = _valid_url(pdata.get("thumbnail"))
            if thumb:
                embed.set_thumbnail(url=thumb)
                break

        items = list(packs.items())
        shown = items[:EMBED_FIELD_LIMIT]
        for name, data in shown:
            price = data.get("price", 0)
            desc = data.get("description", "") or "No description"
            card_count = len(data.get("cards", []))
            pulls = data.get("pull_count", 5)
            value = f"**Price:** {price}\n**Cards:** {card_count}\n**Pulls:** {pulls}\n{desc}"
            embed.add_field(name=name, value=value, inline=False)

        remaining = len(items) - len(shown)
        if remaining > 0:
            embed.add_field(name="More packs", value=f"...and {remaining} more pack(s)", inline=False)

        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Add card to pack", style=discord.ButtonStyle.success, custom_id="cardpacks_add_card", row=0)
    async def add_card(self, interaction: discord.Interaction, button: ui.Button):
        packs = await self.cog._get_all_packs(interaction.guild)
        if not packs:
            await interaction.response.send_message("No packs available to add cards to.", ephemeral=True)
            return

        async def on_pick(inter: discord.Interaction, pack_name: str):
            await inter.response.send_modal(CardAddModal(self.cog, pack_name))

        entries = [(name, f"{len(data.get('cards', []))} cards", name) for name, data in packs.items()]
        view = PaginatedManagerSelectView(entries, "Choose pack to add a card to", on_pick)
        await interaction.response.send_message("Choose pack to add a card to", view=view, ephemeral=True)

    @ui.button(label="Export packs", style=discord.ButtonStyle.secondary, custom_id="cardpacks_export_packs", row=0)
    async def export_packs(self, interaction: discord.Interaction, button: ui.Button):
        packs = await self.cog._get_all_packs(interaction.guild)
        if not packs:
            await interaction.response.send_message("No packs configured.", ephemeral=True)
            return

        lines = []
        for name, data in packs.items():
            lines.append(f"== {name} ==")
            lines.append(f"price: {data.get('price', 0)}")
            lines.append(f"desc: {data.get('description', '')}")
            lines.append(f"pulls: {data.get('pull_count', 5)}")
            thumbnail = _valid_url(data.get("thumbnail"))
            if thumbnail:
                lines.append(f"thumbnail: {thumbnail}")
            lines.append("cards:")
            for c in data.get("cards", []):
                lines.append(_format_card_line(c))

        payload = "\n".join(lines)
        file = discord.File(io.StringIO(payload), filename="cardpacks_export.txt")
        try:
            await interaction.response.send_message("Exported packs file:", file=file, ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("Could not send file, here's the export:\n>>> \n" + payload + "\n>>>", ephemeral=True)

    @ui.button(label="Edit/Delete pack", style=discord.ButtonStyle.primary, custom_id="cardpacks_edit_pack", row=1)
    async def edit_pack(self, interaction: discord.Interaction, button: ui.Button):
        packs = await self.cog._get_all_packs(interaction.guild)
        if not packs:
            await interaction.response.send_message("No packs configured.", ephemeral=True)
            return

        async def on_pick(inter: discord.Interaction, pack_name: str):
            pack = await self.cog._get_pack(inter.guild, pack_name)
            if not pack:
                await inter.response.send_message("Pack not found.", ephemeral=True)
                return
            view = ManagerView(timeout=60)
            view.add_item(EditPackButton(self.cog, pack_name))
            view.add_item(DeletePackButton(self.cog, pack_name))
            await inter.response.send_message(f"Manage pack **{pack_name}**", view=view, ephemeral=True)

        entries = [(name, f"Price: {data.get('price', 0)}", name) for name, data in packs.items()]
        view = PaginatedManagerSelectView(entries, "Select pack to edit/delete", on_pick)
        await interaction.response.send_message("Select pack to edit or delete", view=view, ephemeral=True)

    @ui.button(label="Edit/Delete card", style=discord.ButtonStyle.primary, custom_id="cardpacks_edit_card", row=1)
    async def edit_card(self, interaction: discord.Interaction, button: ui.Button):
        packs = await self.cog._get_all_packs(interaction.guild)
        if not packs:
            await interaction.response.send_message("No packs configured.", ephemeral=True)
            return

        async def on_pack_pick(inter: discord.Interaction, pack_name: str):
            pack = await self.cog._get_pack(inter.guild, pack_name)
            cards = pack.get("cards", []) if pack else []
            if not cards:
                await inter.response.send_message("This pack has no cards.", ephemeral=True)
                return

            async def on_card_pick(inter2: discord.Interaction, value: str):
                idx = int(value)
                if idx < 0 or idx >= len(cards):
                    await inter2.response.send_message("Card not found.", ephemeral=True)
                    return
                card = cards[idx]
                view2 = ManagerView(timeout=60)
                view2.add_item(ViewCardButton(self.cog, pack_name, idx))
                view2.add_item(EditCardButton(self.cog, pack_name, idx))
                view2.add_item(DeleteCardButton(self.cog, pack_name, idx))
                await inter2.response.send_message(f"Manage card **{card.get('name')}** in **{pack_name}**", view=view2, ephemeral=True)

            card_entries = [(c.get("name", f"card-{i}"), c.get("rarity", "common"), str(i)) for i, c in enumerate(cards)]
            card_view = PaginatedManagerSelectView(card_entries, "Select card to edit/delete", on_card_pick)
            await inter.response.send_message("Select card to edit/delete", view=card_view, ephemeral=True)

        pack_entries = [(name, f"{len(data.get('cards', []))} cards", name) for name, data in packs.items()]
        view = PaginatedManagerSelectView(pack_entries, "Select pack to choose a card from", on_pack_pick)
        await interaction.response.send_message("Pick a pack to select a card from", view=view, ephemeral=True)

    @ui.button(label="Import packs", style=discord.ButtonStyle.primary, custom_id="cardpacks_import_packs", row=1)
    async def import_packs(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Please upload the export text file (must be a .txt attachment). I'll wait 60 seconds for your message in this channel.",
            ephemeral=True,
        )

        def _check(msg: discord.Message):
            return msg.author.id == interaction.user.id and msg.channel.id == interaction.channel_id

        try:
            msg: discord.Message = await self.cog.bot.wait_for("message", timeout=60.0, check=_check)
        except Exception:
            await interaction.followup.send("No message received. Import cancelled.", ephemeral=True)
            return

        if not msg.attachments:
            await interaction.followup.send("Import requires a .txt file attachment. Pasted text is not accepted. Import cancelled.", ephemeral=True)
            return

        att = msg.attachments[0]
        filename = (att.filename or "").lower()
        if not filename.endswith(".txt"):
            await interaction.followup.send("Attachment must be a .txt file. Import cancelled.", ephemeral=True)
            return

        try:
            data = await att.read()
            try:
                raw_text = data.decode("utf-8")
            except Exception:
                raw_text = data.decode("latin-1")
        except Exception as e:
            await interaction.followup.send(f"Failed to read attachment: {e}", ephemeral=True)
            return

        if not raw_text or not raw_text.strip():
            await interaction.followup.send("Attachment was empty. Import cancelled.", ephemeral=True)
            return

        parsed = _parse_pack_export(raw_text)
        if not parsed:
            await interaction.followup.send("No packs found in that file.", ephemeral=True)
            return

        try:
            created, updated = await self.cog._apply_imported_packs(interaction.guild, parsed)
        except Exception as e:
            await interaction.followup.send(f"Import failed: {e}", ephemeral=True)
            return

        await interaction.followup.send(f"Import complete. Packs created: {created}, packs updated: {updated}", ephemeral=True)

    @ui.button(label="Purge", style=discord.ButtonStyle.danger, custom_id="cardpacks_purge", row=1)
    async def purge(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(PurgeModal(self.cog))


class CardPacks(commands.Cog):
    """Card packs cog with inventories, rarities, and timed views"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890123)
        self.config.register_guild(**DEFAULT)

    # NOTE: do not call bot.add_view(...) here, that registers persistent views which bypass timeouts.

    async def _get_all_packs(self, guild: Optional[discord.Guild]) -> Dict[str, dict]:
        if not guild:
            return {}
        return await self.config.guild(guild).packs()

    async def _get_pack(self, guild: Optional[discord.Guild], name: str) -> Optional[dict]:
        packs = await self._get_all_packs(guild)
        return packs.get(name)

    async def _create_pack(
        self,
        guild: discord.Guild,
        name: str,
        price: int,
        description: str = "",
        rarity_weights: Optional[dict] = None,
        pull_count: int = 1,
        thumbnail: Optional[str] = None,
    ):
        async with self.config.guild(guild).packs() as packs:
            if name in packs:
                raise commands.BadArgument("Pack already exists")
            packs[name] = {
                "price": price,
                "description": description,
                "cards": [],
                "rarity_weights": rarity_weights or {},
                "pull_count": int(pull_count),
                "thumbnail": _valid_url(thumbnail),
            }

    async def _edit_pack(self, guild: discord.Guild, original_name: str, new_name: str, price: int, description: str, pull_count: int, thumbnail: Optional[str]):
        async with self.config.guild(guild).packs() as packs:
            if original_name not in packs:
                raise commands.BadArgument("Pack not found")
            if new_name != original_name and new_name in packs:
                raise commands.BadArgument("A pack with the new name already exists")
            pack = packs.pop(original_name)
            pack["price"] = price
            pack["description"] = description
            pack["pull_count"] = int(pull_count)
            pack["thumbnail"] = _valid_url(thumbnail)
            packs[new_name] = pack

    async def _delete_pack(self, guild: discord.Guild, name: str):
        async with self.config.guild(guild).packs() as packs:
            if name not in packs:
                raise commands.BadArgument("Pack not found")
            packs.pop(name)

    async def _add_card_to_pack(self, guild: discord.Guild, pack_name: str, card: dict):
        async with self.config.guild(guild).packs() as packs:
            if pack_name not in packs:
                raise commands.BadArgument("Pack not found")
            packs[pack_name].setdefault("cards", []).append(card)

    async def _edit_card_in_pack(self, guild: discord.Guild, pack_name: str, index: int, new_card: dict):
        async with self.config.guild(guild).packs() as packs:
            if pack_name not in packs:
                raise commands.BadArgument("Pack not found")
            cards = packs[pack_name].get("cards", [])
            if index < 0 or index >= len(cards):
                raise commands.BadArgument("Card index out of range")
            cards[index] = new_card
            packs[pack_name]["cards"] = cards

    async def _delete_card_from_pack(self, guild: discord.Guild, pack_name: str, index: int):
        async with self.config.guild(guild).packs() as packs:
            if pack_name not in packs:
                raise commands.BadArgument("Pack not found")
            cards = packs[pack_name].get("cards", [])
            if index < 0 or index >= len(cards):
                raise commands.BadArgument("Card index out of range")
            cards.pop(index)
            packs[pack_name]["cards"] = cards

    async def _apply_imported_packs(self, guild: discord.Guild, packs_raw: Dict[str, dict]) -> Tuple[int, int]:
        created = 0
        updated = 0
        async with self.config.guild(guild).packs() as packs:
            for pname, pdata in packs_raw.items():
                existing_weights = packs.get(pname, {}).get("rarity_weights", {})
                entry = {
                    "price": pdata.get("price", 0),
                    "description": pdata.get("description", ""),
                    "cards": pdata.get("cards", []),
                    "rarity_weights": existing_weights,
                    "pull_count": int(pdata.get("pull_count", 1)),
                    "thumbnail": _valid_url(pdata.get("thumbnail")),
                }
                if pname in packs:
                    updated += 1
                else:
                    created += 1
                packs[pname] = entry
        return created, updated

    async def _get_user_inventory(self, guild: discord.Guild, user: discord.abc.User) -> List[dict]:
        inv = await self.config.guild(guild).inventories()
        return inv.get(str(guild.id), {}).get(str(user.id), [])

    async def _set_user_inventory(self, guild: discord.Guild, user: discord.abc.User, cards: List[dict]):
        async with self.config.guild(guild).inventories() as inv:
            guild_inv = inv.setdefault(str(guild.id), {})
            guild_inv[str(user.id)] = cards

    async def _add_card_to_user(self, guild: discord.Guild, user: discord.abc.User, card: dict, source_pack: Optional[str] = None):
        async with self.config.guild(guild).inventories() as inv:
            guild_inv = inv.setdefault(str(guild.id), {})
            cur = guild_inv.setdefault(str(user.id), [])
            store_card = dict(card)
            if source_pack:
                store_card["source_pack"] = source_pack
            store_card.setdefault("name", "")
            store_card.setdefault("rarity", "common")
            store_card.setdefault("image", "")
            cur.append(store_card)

    def _card_identity(self, card: dict) -> Tuple[str, str, str]:
        name = (card.get("name") or "").strip()
        rarity = (card.get("rarity") or "common").strip()
        image = (card.get("image") or "").strip()
        return (name, rarity, image)

    def _build_card_embed(self, pack_name: str, card: dict) -> discord.Embed:
        name = card.get("name", "Unknown")
        rarity = card.get("rarity", "common")
        text = card.get("text", "")
        chance = card.get("chance")

        embed = discord.Embed(title=name, description=text or None, color=discord.Color.gold())
        embed.add_field(name="Rarity", value=rarity)
        if chance is not None:
            embed.add_field(name="Pull chance", value=f"{chance}%")
        embed.set_footer(text=f"From pack: {pack_name}")

        image = _valid_url(card.get("image"))
        if image:
            embed.set_image(url=image)
        return embed

    async def _send_card_browser(self, target, pack_name: str, pack_data: dict, *, as_interaction_response: bool = False):
        cards = pack_data.get("cards", [])
        if not cards:
            msg = "This pack has no cards."
            if as_interaction_response:
                await target.response.send_message(msg, ephemeral=True)
            else:
                await target.send(msg)
            return

        async def on_pick(interaction: discord.Interaction, value: str):
            idx = int(value)
            if idx < 0 or idx >= len(cards):
                await interaction.response.send_message("Card not found.", ephemeral=True)
                return
            embed = self._build_card_embed(pack_name, cards[idx])
            await interaction.response.send_message(embed=embed, ephemeral=True)

        entries = [(c.get("name", f"card-{i}"), c.get("rarity", "common"), str(i)) for i, c in enumerate(cards)]
        view = PaginatedSelectView(entries, "Select a card to view", on_pick)

        if as_interaction_response:
            await target.response.send_message(f"Cards in **{pack_name}**", view=view, ephemeral=True)
        else:
            msg = await target.send(f"Cards in **{pack_name}**", view=view)
            view.message = msg

    async def _aggregate_inventory(self, guild: discord.Guild, user: discord.abc.User) -> Dict[Tuple[str, str, str], dict]:
        raw = await self._get_user_inventory(guild, user)
        packs = await self._get_all_packs(guild)

        card_to_packs = defaultdict(Counter)
        for pack_name, pdata in packs.items():
            for c in pdata.get("cards", []):
                ident = self._card_identity(c)
                card_to_packs[ident][pack_name] += 1

        agg: Dict[Tuple[str, str, str], dict] = {}
        for card in raw:
            ident = self._card_identity(card)
            entry = agg.get(ident)
            if not entry:
                entry = {"count": 0, "card": card, "packs": Counter()}
                agg[ident] = entry
            entry["count"] += 1

            sp = card.get("source_pack")
            if sp:
                entry["packs"][sp] += 1
            else:
                packs_found = card_to_packs.get(ident)
                if packs_found:
                    likely_pack = packs_found.most_common(1)[0][0]
                    entry["packs"][likely_pack] += 1
                else:
                    entry["packs"]["Unknown pack"] += 1

        return agg

    async def _purge_all_inventories(self, guild: discord.Guild):
        async with self.config.guild(guild).inventories() as inv:
            inv.pop(str(guild.id), None)

    async def _purge_inventory_for_user(self, guild: discord.Guild, user: discord.abc.User):
        await self._set_user_inventory(guild, user, [])

    @commands.group(invoke_without_command=True)
    async def cardpacks(self, ctx: commands.Context):
        """Cardpacks main command"""
        await ctx.send_help(ctx.command)

    @cardpacks.command(name="buy")
    async def buy(self, ctx: commands.Context):
        """Buy a pack via dropdown"""
        packs = await self._get_all_packs(ctx.guild)
        if not packs:
            await ctx.send("No packs are configured on this server.")
            return

        async def on_pick(interaction: discord.Interaction, pack_name: str):
            pack = await self._get_pack(interaction.guild, pack_name)
            if not pack:
                await interaction.response.send_message("Pack not found.", ephemeral=True)
                return
            price = int(pack.get("price", 0))
            can = await bank.can_spend(interaction.user, price)
            currency = await bank.get_currency_name(interaction.guild)
            if not can:
                await interaction.response.send_message(f"You need {price} {currency} to buy this pack.", ephemeral=True)
                return
            view = ConfirmBuyView(self, pack_name, price)
            await interaction.response.send_message(
                f"Confirm purchase of **{pack_name}** for **{price} {currency}**?",
                view=view,
                ephemeral=True,
            )

        entries = []
        for name, data in packs.items():
            desc = (data.get("description") or "").strip()
            price = data.get("price", 0)
            combined = f"{desc} — {price}" if desc else f"Price: {price}"
            entries.append((name, _truncate(combined, 100), name))

        view = PaginatedSelectView(entries, "Choose a pack to buy", on_pick)
        msg = await ctx.send("Select a pack to buy", view=view)
        view.message = msg

    @cardpacks.command(name="view")
    async def view_cards(self, ctx: commands.Context, *, pack_name: Optional[str] = None):
        """Browse a pack's cards, showing each card's artwork."""
        packs = await self._get_all_packs(ctx.guild)
        if not packs:
            await ctx.send("No packs are configured on this server.")
            return

        if pack_name:
            pack = packs.get(pack_name)
            if not pack:
                await ctx.send(f"No pack named **{pack_name}** was found.")
                return
            await self._send_card_browser(ctx, pack_name, pack)
            return

        async def on_pick(interaction: discord.Interaction, value: str):
            pdata = packs.get(value)
            await self._send_card_browser(interaction, value, pdata, as_interaction_response=True)

        entries = [(name, f"{len(data.get('cards', []))} cards", name) for name, data in packs.items()]
        view = PaginatedSelectView(entries, "Select a pack to view", on_pick)
        msg = await ctx.send("Select a pack to browse its cards", view=view)
        view.message = msg

    @cardpacks.group(name="manage", invoke_without_command=True)
    @checks.guildowner_or_permissions(manage_guild=True)
    async def manage(self, ctx: commands.Context):
        """Manage packs (create, add cards). Admin only."""
        if ctx.invoked_subcommand is None:
            view = ManageView(self)
            msg = await ctx.send("Cardpacks manager", view=view)
            view.message = msg

    def _build_inventory_embeds(self, target: discord.abc.User, agg: Dict[Tuple[str, str, str], dict], packs: Dict[str, dict], requested_by: discord.abc.User) -> List[discord.Embed]:
        total_items = sum(e["count"] for e in agg.values())
        unique_stacks = len(agg)

        by_pack = defaultdict(list)
        owned_unique_per_pack = defaultdict(set)
        for ident, entry in agg.items():
            pack_counts: Counter = entry["packs"]
            primary_pack = pack_counts.most_common(1)[0][0] if pack_counts else "Unknown pack"
            by_pack[primary_pack].append((ident, entry))
            for p_name in pack_counts.keys():
                owned_unique_per_pack[p_name].add(ident)

        pack_items = list(by_pack.items())
        chunks = [pack_items[i:i + PACKS_PER_EMBED_PAGE] for i in range(0, len(pack_items), PACKS_PER_EMBED_PAGE)] or [[]]

        try:
            avatar_url = target.avatar.url if getattr(target, "avatar", None) else target.display_avatar.url
        except Exception:
            avatar_url = target.display_avatar.url

        banner = random.choice(INVENTORY_BANNER_URLS) if INVENTORY_BANNER_URLS else None
        first_img = None
        for ident in agg.keys():
            img = _valid_url(ident[2])
            if img:
                first_img = img
                break

        total_pages = len(chunks)
        embeds = []
        for page_num, chunk in enumerate(chunks, start=1):
            embed = discord.Embed(title=f"{target.display_name}'s inventory", color=discord.Color.blurple())
            embed.set_author(name=target.display_name, icon_url=avatar_url)
            embed.add_field(name="Totals", value=f"Total cards: **{total_items}**\nUnique cards: **{unique_stacks}**", inline=False)

            for pack_name, items in chunk:
                if pack_name != "Unknown pack" and pack_name in packs:
                    total_cards = len(packs[pack_name].get("cards", []))
                else:
                    total_cards = None
                owned_count = len(owned_unique_per_pack.get(pack_name, set()))
                total_disp = str(total_cards) if total_cards is not None else "?"
                header = f"{pack_name} — {owned_count}/{total_disp}"

                lines = []
                items_sorted = sorted(items, key=lambda ie: (-ie[1]["count"], ie[0][1], ie[0][0]))
                shown = items_sorted[:PACK_STACK_LIMIT]
                for ident, entry in shown:
                    name, rarity, _image = ident
                    lines.append(f"**x{entry['count']}** • {name} ({rarity})")
                remaining = len(items_sorted) - len(shown)
                if remaining > 0:
                    lines.append(f"...and {remaining} more stacks")
                embed.add_field(name=header, value="\n".join(lines) or "No cards", inline=False)

            if banner:
                embed.set_image(url=banner)
            if first_img:
                try:
                    embed.set_thumbnail(url=first_img)
                except Exception:
                    pass

            footer = f"Requested by {requested_by.display_name}"
            if total_pages > 1:
                footer += f" • Page {page_num}/{total_pages}"
            embed.set_footer(text=footer)
            embed.timestamp = discord.utils.utcnow()
            embeds.append(embed)

        return embeds

    @cardpacks.command(name="inventory")
    async def inventory(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """View inventory, with a dropdown to look at any owned card's artwork."""
        if member is None:
            target = ctx.author
        else:
            is_admin = False
            if ctx.guild:
                is_admin = ctx.author == ctx.guild.owner or ctx.author.guild_permissions.manage_guild
            target = member if is_admin else ctx.author

        inv_raw = await self._get_user_inventory(ctx.guild, target)
        if not inv_raw:
            if target == ctx.author:
                await ctx.send("You have no cards.")
            else:
                await ctx.send(f"{target.display_name} has no cards.")
            return

        agg = await self._aggregate_inventory(ctx.guild, target)
        packs = await self._get_all_packs(ctx.guild)
        embeds = self._build_inventory_embeds(target, agg, packs, ctx.author)

        card_entries = []
        for ident, entry in agg.items():
            name, rarity, _image = ident
            primary_pack = entry["packs"].most_common(1)[0][0] if entry["packs"] else "Unknown pack"
            desc = f"x{entry['count']} • {rarity} • {primary_pack}"
            payload = {"card": entry["card"], "pack": primary_pack, "count": entry["count"]}
            card_entries.append((name or "Unnamed", desc, payload))

        def build_card_embed(payload: dict) -> discord.Embed:
            embed = self._build_card_embed(payload["pack"], payload["card"])
            embed.add_field(name="Owned", value=f"x{payload['count']}")
            return embed

        view = InventoryView(ctx.author.id, embeds, card_entries, build_card_embed)
        msg = await ctx.send(embed=embeds[0], view=view)
        view.message = msg


def setup(bot):
    bot.add_cog(CardPacks(bot))
