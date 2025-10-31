import random
from typing import Optional, Dict, List, Tuple
from collections import defaultdict, Counter

import discord
from discord import ui
from redbot.core import commands, bank, checks, Config

DEFAULT = {"packs": {}, "inventories": {}}

# Module-level inventory banner URLs so inventory embed can access them reliably
INVENTORY_BANNER_URLS = [
    "https://files.catbox.moe/55yfxz.jpg",
]


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


class TimedView(ui.View):
    """Generic timed view that disables children and edits the original message on timeout."""

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


class BuySelect(ui.Select):
    def __init__(self, cog: "CardPacks", packs: Dict[str, dict]):
        options = []
        for name, data in packs.items():
            label = name
            desc = data.get("description", "")
            price = data.get("price", 0)
            options.append(
                discord.SelectOption(label=label, description=f"{desc} - {price}", value=name)
            )
        super().__init__(placeholder="Choose a pack to buy", min_values=1, max_values=1, options=options)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        pack_name = self.values[0]
        pack = await self.cog._get_pack(interaction.guild, pack_name)
        if not pack:
            await interaction.response.send_message("Pack not found.", ephemeral=True)
            return
        price = int(pack.get("price", 0))
        can = await bank.can_spend(interaction.user, price)
        currency = await bank.get_currency_name(interaction.guild)
        if not can:
            await interaction.response.send_message(f"You need {price} {currency} to buy this pack.", ephemeral=True)
            return

        view = ConfirmBuyView(self.cog, pack_name, price)
        await interaction.response.send_message(
            f"Confirm purchase of **{pack_name}** for **{price} {currency}**?",
            view=view,
            ephemeral=True,
        )


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

    @ui.button(label="Confirm", style=discord.ButtonStyle.green, custom_id="cardpacks_confirm_buy")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        # Try withdraw; if it fails, tell the user privately
        try:
            await bank.withdraw_credits(interaction.user, self.price)
        except Exception as e:
            await interaction.response.send_message(f"Purchase failed: {e}", ephemeral=True)
            return

        pack = await self.cog._get_pack(interaction.guild, self.pack_name)
        cards = pack.get("cards", []) if pack else []
        if not cards:
            msg = f"Pack **{self.pack_name}** contained no cards. Refunding."
            try:
                await bank.deposit_credits(interaction.user, self.price)
            except Exception:
                pass
            await interaction.response.send_message(msg, ephemeral=True)
            return

        packs_all = await self.cog._get_all_packs(interaction.guild)
        rarity_map = _rarity_weights_map(packs_all, self.pack_name)

        pull_count = int(pack.get("pull_count", 5))
        pulled: List[dict] = []
        for _ in range(max(1, pull_count)):
            chosen_card = None

            # If any card defines an explicit 'chance' value, use per-card chances
            cards_with_chance = [c for c in cards if c.get("chance") is not None]
            if cards_with_chance:
                weights = [float(c.get("chance", 0.0)) for c in cards]
                if sum(weights) > 0:
                    chosen_card = random.choices(cards, weights=weights, k=1)[0]
                else:
                    chosen_card = random.choice(cards)
            else:
                # rarity-based selection
                if rarity_map:
                    rarities = list(rarity_map.keys())
                    weights = [rarity_map[r] for r in rarities]
                    chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]
                    rarity_candidates = [c for c in cards if c.get("rarity", "common") == chosen_rarity]
                    if rarity_candidates:
                        chosen_card = random.choice(rarity_candidates)
                if not chosen_card:
                    chosen_card = random.choice(cards)

            # clone chosen_card to avoid mutating pack definitions
            chosen_copy = dict(chosen_card)
            pulled.append(chosen_copy)
            # store source_pack for exact attribution
            await self.cog._add_card_to_user(interaction.guild, interaction.user, chosen_copy, source_pack=self.pack_name)

        # Build a visually appealing embed for public display
        banner = random.choice(self.BANNER_URLS) if self.BANNER_URLS else None
        embed = discord.Embed(
            title=f"{interaction.user.display_name} opened {self.pack_name}!",
            description=f"A shiny new pack has been opened by **{interaction.user.display_name}**.",
            color=discord.Color.random(),
        )
        # Banner image (large visual across the top)
        if banner:
            embed.set_image(url=banner)

        # Optional pack thumbnail (small image next to title)
        thumbnail = pack.get("thumbnail")
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        # Flavor text — short, celebratory line
        embed.add_field(name="Result", value=f"Pulled {len(pulled)} card(s) from **{self.pack_name}**", inline=False)

        # For each pulled card, add a compact field (name + rarity + short text)
        for idx, c in enumerate(pulled, start=1):
            name = c.get("name", "Unknown")
            rarity = c.get("rarity", "common")
            text = c.get("text", "")
            chance_info = f" | Chance: {c.get('chance')}%" if c.get("chance") is not None else ""
            value_lines = []
            if text:
                # Keep it brief to avoid overly large embeds; include main text first line
                first_line = text.splitlines()[0]
                value_lines.append(first_line)
            value_lines.append(f"Rarity: **{rarity}**{chance_info}")
            img = c.get("image")
            if img:
                value_lines.append(img)
            embed.add_field(name=f"{idx}. {name}", value="\n".join(value_lines), inline=False)

        # Footer and timestamp for polish
        embed.set_footer(text=f"Bought for {self.price} {await bank.get_currency_name(interaction.guild)}")
        embed.timestamp = discord.utils.utcnow()

        # Send publicly to the channel so everyone sees it
        try:
            await interaction.response.send_message(content=None, embed=embed, ephemeral=False)
        except Exception:
            # If sending public message fails (rare), fall back to ephemeral message for the buyer
            await interaction.response.send_message("Could not post the public reveal; here are your pulls:", embed=embed, ephemeral=True)

    @ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cardpacks_cancel_buy")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Purchase cancelled.", ephemeral=True)


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

        thumbnail = self.thumbnail_url.value.strip() or None
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

        # set defaults
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

        thumbnail = self.thumbnail_url.value.strip() or None
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
        # defaults
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


class PackSelect(ui.Select):
    def __init__(self, cog: "CardPacks", packs: Dict[str, dict]):
        options = []
        for name in packs.keys():
            options.append(discord.SelectOption(label=name, value=name))
        super().__init__(placeholder="Select pack", min_values=1, max_values=1, options=options)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        pack_name = self.values[0]
        await interaction.response.send_modal(CardAddModal(self.cog, pack_name))


class PackManageSelect(ui.Select):
    """Select a pack to manage (edit/delete)."""

    def __init__(self, cog: "CardPacks", packs: Dict[str, dict]):
        options = []
        for name in packs.keys():
            options.append(discord.SelectOption(label=name, value=name))
        super().__init__(placeholder="Select pack to edit/delete", min_values=1, max_values=1, options=options)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        pack_name = self.values[0]
        pack = await self.cog._get_pack(interaction.guild, pack_name)
        if not pack:
            await interaction.response.send_message("Pack not found.", ephemeral=True)
            return
        view = TimedView(timeout=60)
        view.add_item(EditPackButton(self.cog, pack_name))
        view.add_item(DeletePackButton(self.cog, pack_name))
        await interaction.response.send_message(f"Manage pack **{pack_name}**", view=view, ephemeral=True)


class CardInPackSelect(ui.Select):
    """Select a card within a pack to edit/delete."""

    def __init__(self, cog: "CardPacks", pack_name: str, cards: List[dict]):
        options = []
        for idx, c in enumerate(cards):
            label = c.get("name", f"card-{idx}")
            desc = c.get("rarity", "common")
            options.append(discord.SelectOption(label=label, description=desc, value=str(idx)))
        super().__init__(placeholder="Select card to edit/delete", min_values=1, max_values=1, options=options)
        self.cog = cog
        self.pack_name = pack_name
        self.cards = cards

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        card = self.cards[idx]
        view = TimedView(timeout=60)
        view.add_item(EditCardButton(self.cog, self.pack_name, idx))
        view.add_item(DeleteCardButton(self.cog, self.pack_name, idx))
        await interaction.response.send_message(f"Manage card **{card.get('name')}** in **{self.pack_name}**", view=view, ephemeral=True)


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
        # confirm deletion inline with buttons
        view = TimedView(timeout=60)
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
        view = TimedView(timeout=60)
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


# --- Purge modal and button (admin only via ManageView protection) ---
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
        # mention like <@123> or <@!123>
        if who_raw.startswith("<@") and who_raw.endswith(">"):
            try:
                mention_id = int(who_raw.strip("<@!>"))
                member = guild.get_member(mention_id)
            except Exception:
                member = None
        else:
            # try raw ID
            try:
                member_id = int(who_raw)
                member = guild.get_member(member_id)
            except Exception:
                member = None

        # try get_member_named (username#discriminator or username)
        if not member:
            try:
                member = guild.get_member_named(who_raw)
            except Exception:
                member = None

        # fallback: exact match on display_name or name (case-insensitive)
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
        raw = self.data.value
        try:
            created, updated = await self._parse_and_apply(interaction.guild, raw)
        except Exception as e:
            await interaction.response.send_message(f"Import failed: {e}", ephemeral=True)
            return
        await interaction.response.send_message(f"Import complete. Packs created: {created}, packs updated: {updated}", ephemeral=True)

    async def _parse_and_apply(self, guild: discord.Guild, text: str) -> Tuple[int, int]:
        """
        Simple parser for the export format:
        == Pack Name ==
        price: N
        desc: text
        pulls: N
        thumbnail: url
        cards:
        - Name | text | rarity: rarename [ chance: X ]
        """
        packs_raw = {}
        current = None

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("==") and line.endswith("=="):
                # new pack header
                pname = line.strip("=").strip()
                current = {"price": 0, "description": "", "pull_count": 5, "thumbnail": None, "cards": []}
                packs_raw[pname] = current
                continue
            if current is None:
                continue
            # pack meta
            if line.startswith("price:"):
                try:
                    current["price"] = int(line.split(":", 1)[1].strip())
                except Exception:
                    current["price"] = 0
                continue
            if line.startswith("desc:"):
                current["description"] = line.split(":", 1)[1].strip()
                continue
            if line.startswith("pulls:"):
                try:
                    current["pull_count"] = int(line.split(":", 1)[1].strip())
                except Exception:
                    current["pull_count"] = 1
                continue
            if line.startswith("thumbnail:"):
                val = line.split(":", 1)[1].strip()
                current["thumbnail"] = val if val else None
                continue
            if line.startswith("- "):
                # card line: "- Name | text | rarity: rarity [ chance: X ]"
                body = line[2:].strip()
                parts = [p.strip() for p in body.split("|")]
                name = parts[0] if len(parts) > 0 else ""
                text_part = parts[1] if len(parts) > 1 else ""
                rarity = "common"
                chance = None
                # parse trailing "rarity: ..." and optional "chance: ...", which may appear in parts[2] or at end
                if len(parts) > 2:
                    tail = parts[2]
                    # tail can contain "rarity: xyz chance: 0.5"
                    for token in tail.split():
                        if token.startswith("rarity:"):
                            rarity = tail.split("rarity:", 1)[1].split()[0].strip()
                        # don't rely on tokenization for chance; use simple find
                    if "rarity:" in tail:
                        try:
                            rarity = tail.split("rarity:", 1)[1].split()[0].strip()
                        except Exception:
                            pass
                    if "chance:" in tail:
                        try:
                            raw = tail.split("chance:", 1)[1].strip()
                            if raw.endswith("%"):
                                raw = raw[:-1].strip()
                            val = float(raw)
                            # store numeric percent as-is (e.g. "0.5" -> 0.5 ; "50" -> 50)
                            chance = val
                        except Exception:
                            chance = None
                card = {"name": name, "text": text_part, "image": "", "rarity": rarity}
                if chance is not None:
                    card["chance"] = chance
                current["cards"].append(card)

        # apply to Config: create packs if not exists, or replace existing pack data (cards will be replaced)
        existing = await self.cog._get_all_packs(guild)
        created = 0
        updated = 0
        for pname, pdata in packs_raw.items():
            if pname in existing:
                # update existing pack (overwrite metadata and cards)
                try:
                    await self.cog._edit_pack(guild, pname, pname, pdata.get("price", 0), pdata.get("description", ""), pdata.get("pull_count", 1), pdata.get("thumbnail"))
                    # after edit, set cards
                    # reuse _delete_card_from_pack/_add_card? Simpler: fetch packs, set cards, save
                    packs = await self.cog._get_all_packs(guild)
                    packs[pname]["cards"] = pdata.get("cards", [])
                    await self.cog.config.guild(guild).packs.set(packs)
                    updated += 1
                except Exception:
                    # fallback: set directly
                    packs = await self.cog._get_all_packs(guild)
                    packs[pname] = {
                        "price": pdata.get("price", 0),
                        "description": pdata.get("description", ""),
                        "cards": pdata.get("cards", []),
                        "rarity_weights": {},
                        "pull_count": int(pdata.get("pull_count", 1)),
                        "thumbnail": pdata.get("thumbnail"),
                    }
                    await self.cog.config.guild(guild).packs.set(packs)
                    updated += 1
            else:
                # create
                await self.cog._create_pack(guild, pname, pdata.get("price", 0), pdata.get("description", ""), None, pdata.get("pull_count", 1), pdata.get("thumbnail"))
                # set cards
                packs = await self.cog._get_all_packs(guild)
                packs[pname]["cards"] = pdata.get("cards", [])
                await self.cog.config.guild(guild).packs.set(packs)
                created += 1

        return created, updated


class PurgeButton(ui.Button):
    def __init__(self, cog: "CardPacks"):
        super().__init__(label="Purge", style=discord.ButtonStyle.danger, custom_id="cardpacks_purge")
        self.cog = cog

    async def callback(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(PurgeModal(self.cog))


class ManageView(TimedView):
    def __init__(self, cog: "CardPacks"):
        super().__init__(timeout=60)
        self.cog = cog

    @ui.button(label="Create pack", style=discord.ButtonStyle.primary, custom_id="cardpacks_create_pack")
    async def create_pack(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(PackCreateModal(self.cog))

    @ui.button(label="List packs", style=discord.ButtonStyle.secondary, custom_id="cardpacks_list_packs")
    async def list_packs(self, interaction: discord.Interaction, button: ui.Button):
        packs = await self.cog._get_all_packs(interaction.guild)
        if not packs:
            await interaction.response.send_message("No packs configured.", ephemeral=True)
            return

        embed = discord.Embed(title="Configured Packs", color=discord.Color.blue())
        embed.description = f"Total packs: **{len(packs)}**"
        # try to pick a thumbnail from the first pack that has a valid URL
        for pdata in packs.values():
            thumb = pdata.get("thumbnail")
            if not thumb:
                continue
            thumb_str = str(thumb).strip()
            if not thumb_str:
                continue
            if thumb_str.lower().startswith("http://") or thumb_str.lower().startswith("https://"):
                try:
                    embed.set_thumbnail(url=thumb_str)
                except Exception:
                    pass
                break

        # Add one field per pack (compact summary)
        for name, data in packs.items():
            price = data.get("price", 0)
            desc = data.get("description", "") or "No description"
            card_count = len(data.get("cards", []))
            pulls = data.get("pull_count", 5)
            value = f"**Price:** {price}\n**Cards:** {card_count}\n**Pulls:** {pulls}\n{desc}"
            embed.add_field(name=name, value=value, inline=False)

        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        embed.timestamp = discord.utils.utcnow()

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Add card to pack", style=discord.ButtonStyle.success, custom_id="cardpacks_add_card")
    async def add_card(self, interaction: discord.Interaction, button: ui.Button):
        packs = await self.cog._get_all_packs(interaction.guild)
        if not packs:
            await interaction.response.send_message("No packs available to add cards to.", ephemeral=True)
            return
        sel = PackSelect(self.cog, packs)
        view = TimedView(timeout=60)
        view.add_item(sel)
        await interaction.response.send_message("Choose pack to add a card to", view=view, ephemeral=True)

    @ui.button(label="Edit/Delete pack", style=discord.ButtonStyle.primary, custom_id="cardpacks_edit_pack", row=1)
    async def edit_pack(self, interaction: discord.Interaction, button: ui.Button):
        packs = await self.cog._get_all_packs(interaction.guild)
        if not packs:
            await interaction.response.send_message("No packs configured.", ephemeral=True)
            return
        sel = PackManageSelect(self.cog, packs)
        view = TimedView(timeout=60)
        view.add_item(sel)
        await interaction.response.send_message("Select pack to edit or delete", view=view, ephemeral=True)

    @ui.button(label="Edit/Delete card", style=discord.ButtonStyle.primary, custom_id="cardpacks_edit_card", row=1)
    async def edit_card(self, interaction: discord.Interaction, button: ui.Button):
        packs = await self.cog._get_all_packs(interaction.guild)
        if not packs:
            await interaction.response.send_message("No packs configured.", ephemeral=True)
            return
        options = []
        for name, data in packs.items():
            options.append(discord.SelectOption(label=name, description=f"{len(data.get('cards', []))} cards", value=name))
        sel = ui.Select(placeholder="Select pack to choose a card from", min_values=1, max_values=1, options=options)

        async def sel_callback(inter: discord.Interaction):
            pack_name = sel.values[0]
            pack = await self.cog._get_pack(inter.guild, pack_name)
            cards = pack.get("cards", [])
            if not cards:
                await inter.response.send_message("This pack has no cards.", ephemeral=True)
                return
            card_sel = CardInPackSelect(self.cog, pack_name, cards)
            view2 = TimedView(timeout=60)
            view2.add_item(card_sel)
            await inter.response.send_message("Select card to edit/delete", view=view2, ephemeral=True)

        sel.callback = sel_callback
        view = TimedView(timeout=60)
        view.add_item(sel)
        await interaction.response.send_message("Pick a pack to select a card from", view=view, ephemeral=True)

    @ui.button(label="Export packs", style=discord.ButtonStyle.secondary, custom_id="cardpacks_export_packs")
    async def export_packs(self, interaction: discord.Interaction, button: ui.Button):
        packs = await self.cog._get_all_packs(interaction.guild)
        if not packs:
            await interaction.response.send_message("No packs configured.", ephemeral=True)
            return
        lines = []
        for name, data in packs.items():
            lines.append(f"== {name} ==\nprice: {data.get('price')}\ndesc: {data.get('description')}\npulls: {data.get('pull_count', 5)}\nthumbnail: {data.get('thumbnail')}\ncards:")
            for c in data.get("cards", []):
                if c.get("chance") is not None:
                    chance_part = f" chance: {c.get('chance')}%"
                else:
                    chance_part = ""
                lines.append(f"- {c.get('name')} | {c.get('text')} | rarity: {c.get('rarity','common')} {chance_part}")
        payload = "\n".join(lines)
        # send as text file attachment
        try:
            import io
            fp = io.StringIO(payload)
            fp.seek(0)
            file = discord.File(fp, filename="cardpacks_export.txt")
            await interaction.response.send_message("Exported packs file:", file=file, ephemeral=True)
        except Exception as e:
            # fallback to inline text if file sending fails
            await interaction.response.send_message("Could not send file, here's the export:\n>>> \n" + payload + "\n>>>", ephemeral=True)

    @ui.button(label="Import packs", style=discord.ButtonStyle.primary, custom_id="cardpacks_import_packs")
    async def import_packs(self, interaction: discord.Interaction, button: ui.Button):
        """Require a .txt attachment containing the export text."""
        await interaction.response.send_message(
            "Please upload the export text file (must be a .txt attachment). I'll wait 60 seconds for your message in this channel.",
            ephemeral=True,
        )

        def _check(msg: discord.Message):
            # Only accept a message from the invoking user in the same channel
            return msg.author.id == interaction.user.id and msg.channel.id == interaction.channel_id

        try:
            msg: discord.Message = await self.cog.bot.wait_for("message", timeout=60.0, check=_check)
        except Exception:
            await interaction.followup.send("No message received. Import cancelled.", ephemeral=True)
            return

        # Only accept messages with attachments; reject pasted text
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
            # decode with utf-8 fallback
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

        try:
            importer = ImportModal(self.cog)
            created, updated = await importer._parse_and_apply(interaction.guild, raw_text)
        except Exception as e:
            await interaction.followup.send(f"Import failed: {e}", ephemeral=True)
            return

        await interaction.followup.send(f"Import complete. Packs created: {created}, packs updated: {updated}", ephemeral=True)



    @ui.button(label="Purge", style=discord.ButtonStyle.danger, custom_id="cardpacks_purge")
    async def purge(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(PurgeModal(self.cog))


class CardPacks(commands.Cog):
    """Card packs cog with inventories, rarities, and timed views"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890123)
        self.config.register_guild(**DEFAULT)

    # IMPORTANT: do not call bot.add_view(...) here. That registers persistent views which bypass timeouts.

    async def _get_all_packs(self, guild: Optional[discord.Guild]) -> Dict[str, dict]:
        if not guild:
            return {}
        data = await self.config.guild(guild).all()
        return data.get("packs", {})

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
        packs = await self._get_all_packs(guild)
        if name in packs:
            raise commands.BadArgument("Pack already exists")
        packs[name] = {
            "price": price,
            "description": description,
            "cards": [],
            "rarity_weights": rarity_weights or {},
            "pull_count": int(pull_count),
            "thumbnail": thumbnail,
        }
        await self.config.guild(guild).packs.set(packs)

    async def _edit_pack(self, guild: discord.Guild, original_name: str, new_name: str, price: int, description: str, pull_count: int, thumbnail: Optional[str]):
        packs = await self._get_all_packs(guild)
        if original_name not in packs:
            raise commands.BadArgument("Pack not found")
        if new_name != original_name and new_name in packs:
            raise commands.BadArgument("A pack with the new name already exists")
        # move if renamed
        pack = packs.pop(original_name)
        pack["price"] = price
        pack["description"] = description
        pack["pull_count"] = int(pull_count)
        pack["thumbnail"] = thumbnail
        packs[new_name] = pack
        await self.config.guild(guild).packs.set(packs)

    async def _delete_pack(self, guild: discord.Guild, name: str):
        packs = await self._get_all_packs(guild)
        if name not in packs:
            raise commands.BadArgument("Pack not found")
        packs.pop(name)
        await self.config.guild(guild).packs.set(packs)

    async def _add_card_to_pack(self, guild: discord.Guild, pack_name: str, card: dict):
        packs = await self._get_all_packs(guild)
        if pack_name not in packs:
            raise commands.BadArgument("Pack not found")
        packs[pack_name].setdefault("cards", []).append(card)
        await self.config.guild(guild).packs.set(packs)

    async def _edit_card_in_pack(self, guild: discord.Guild, pack_name: str, index: int, new_card: dict):
        packs = await self._get_all_packs(guild)
        if pack_name not in packs:
            raise commands.BadArgument("Pack not found")
        cards = packs[pack_name].get("cards", [])
        if index < 0 or index >= len(cards):
            raise commands.BadArgument("Card index out of range")
        cards[index] = new_card
        packs[pack_name]["cards"] = cards
        await self.config.guild(guild).packs.set(packs)

    async def _delete_card_from_pack(self, guild: discord.Guild, pack_name: str, index: int):
        packs = await self._get_all_packs(guild)
        if pack_name not in packs:
            raise commands.BadArgument("Pack not found")
        cards = packs[pack_name].get("cards", [])
        if index < 0 or index >= len(cards):
            raise commands.BadArgument("Card index out of range")
        cards.pop(index)
        packs[pack_name]["cards"] = cards
        await self.config.guild(guild).packs.set(packs)

    async def _get_user_inventory(self, guild: discord.Guild, user: discord.abc.User) -> List[dict]:
        data = await self.config.guild(guild).all()
        inv = data.get("inventories", {})
        guild_inv = inv.get(str(guild.id), {})
        return guild_inv.get(str(user.id), [])

    async def _set_user_inventory(self, guild: discord.Guild, user: discord.abc.User, cards: List[dict]):
        data = await self.config.guild(guild).all()
        inv = data.get("inventories", {})
        guild_inv = inv.get(str(guild.id), {})
        guild_inv[str(user.id)] = cards
        inv[str(guild.id)] = guild_inv
        await self.config.guild(guild).inventories.set(inv)

    async def _add_card_to_user(self, guild: discord.Guild, user: discord.abc.User, card: dict, source_pack: Optional[str] = None):
        """
        Adds a card dict to a user's inventory.
        If source_pack provided, store it as 'source_pack' on the stored card for exact attribution.
        """
        cur = await self._get_user_inventory(guild, user)
        store_card = dict(card)  # shallow copy to avoid mutating original
        if source_pack:
            store_card["source_pack"] = source_pack
        # ensure required keys exist to make identity stable
        store_card.setdefault("name", "")
        store_card.setdefault("rarity", "common")
        store_card.setdefault("image", "")
        cur.append(store_card)
        await self._set_user_inventory(guild, user, cur)

    # identity used for stacking: name, rarity, image
    def _card_identity(self, card: dict) -> Tuple[str, str, str]:
        name = (card.get("name") or "").strip()
        rarity = (card.get("rarity") or "common").strip()
        image = (card.get("image") or "").strip()
        return (name, rarity, image)

    async def _aggregate_inventory(self, guild: discord.Guild, user: discord.abc.User) -> Dict[Tuple[str, str, str], dict]:
        """
        Aggregate a user's inventory into:
        (name, rarity, image) -> {"count": int, "card": sample_card, "packs": Counter}
        Packs attribution honors stored 'source_pack' when present, otherwise attempts to map by pack definitions.
        """
        raw = await self._get_user_inventory(guild, user)
        packs = await self._get_all_packs(guild)

        # Build a lookup of card identity -> pack names (counts) from pack definitions
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

            # if card has explicit stored source_pack, use that
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

    # --- purge helpers ---
    async def _purge_all_inventories(self, guild: discord.Guild):
        """Remove all stored inventories for this guild."""
        data = await self.config.guild(guild).all()
        inv = data.get("inventories", {}) or {}
        # Remove guild entry if present
        if str(guild.id) in inv:
            inv.pop(str(guild.id), None)
            await self.config.guild(guild).inventories.set(inv)

    async def _purge_inventory_for_user(self, guild: discord.Guild, user: discord.abc.User):
        """Reset a single user's inventory in this guild."""
        await self._set_user_inventory(guild, user, [])

    @commands.group(invoke_without_command=True)
    async def cardpacks(self, ctx: commands.Context):
        """Cardpacks main command"""
        invoked = ctx.message.content[len(ctx.clean_prefix):].strip()
        tokens = invoked.split()
        if len(tokens) == 1:
            await ctx.send_help()
            return

    @cardpacks.command(name="buy")
    async def buy(self, ctx: commands.Context):
        """Buy a pack via dropdown"""
        packs = await self._get_all_packs(ctx.guild)
        if not packs:
            await ctx.send("No packs are configured on this server.")
            return
        view = TimedView(timeout=60)
        view.add_item(BuySelect(self, packs))
        msg = await ctx.send("Select a pack to buy", view=view)
        view.message = msg

    @cardpacks.group(name="manage", invoke_without_command=True)
    @checks.guildowner_or_permissions(manage_guild=True)
    async def manage(self, ctx: commands.Context):
        """Manage packs (create, add cards). Admin only."""
        if ctx.invoked_subcommand is None:
            view = ManageView(self)
            msg = await ctx.send("Cardpacks manager", view=view)
            view.message = msg

    @cardpacks.command(name="inventory")
    async def inventory(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """View inventory. Admins may mention a member to view theirs; regular users see their own."""
        if member is None:
            target = ctx.author
        else:
            is_admin = False
            if ctx.guild:
                is_admin = ctx.author == ctx.guild.owner or ctx.author.guild_permissions.manage_guild
            if not is_admin:
                target = ctx.author
            else:
                target = member

        inv_raw = await self._get_user_inventory(ctx.guild, target)
        if not inv_raw:
            if target == ctx.author:
                await ctx.send("You have no cards.")
            else:
                await ctx.send(f"{target.display_name} has no cards.")
            return

        agg = await self._aggregate_inventory(ctx.guild, target)
        total_items = sum(e["count"] for e in agg.values())
        unique_stacks = len(agg)
        packs = await self._get_all_packs(ctx.guild)

        # Build embed
        title = f"{target.display_name}'s inventory"
        embed = discord.Embed(title=title, color=discord.Color.blurple())
        # author icon: support both v3 and v2 avatars
        try:
            avatar_url = target.avatar.url if getattr(target, "avatar", None) else target.display_avatar.url
        except Exception:
            avatar_url = target.display_avatar.url
        embed.set_author(name=target.display_name, icon_url=avatar_url)
        embed.add_field(name="Totals", value=f"Total cards: **{total_items}**\nUnique cards: **{unique_stacks}**", inline=False)

        # Group aggregated entries by primary pack (most common)
        by_pack = defaultdict(list)
        # We'll compute owned unique-cards per pack (set of idents)
        owned_unique_per_pack = defaultdict(set)

        for ident, entry in agg.items():
            pack_counts: Counter = entry["packs"]
            primary_pack = pack_counts.most_common(1)[0][0] if pack_counts else "Unknown pack"
            by_pack[primary_pack].append((ident, entry))
            # For each pack that contributed to this stack, mark the identity as owned for that pack
            for p_name in pack_counts.keys():
                owned_unique_per_pack[p_name].add(ident)

        # For presentation limits
        PACK_FIELD_LIMIT = 6

        # For each pack, compute total defined cards (unique card types in pack)
        for pack_name, items in by_pack.items():
            # determine total cards for this pack; unknown pack => total = None
            if pack_name != "Unknown pack" and pack_name in packs:
                total_cards = len(packs[pack_name].get("cards", []))
            else:
                total_cards = None

            owned_count = len(owned_unique_per_pack.get(pack_name, set()))
            total_disp = str(total_cards) if total_cards is not None else "?"
            header = f"{pack_name} — {owned_count}/{total_disp}"

            lines = []
            items_sorted = sorted(items, key=lambda ie: (-ie[1]["count"], ie[0][1], ie[0][0]))
            shown = items_sorted[:PACK_FIELD_LIMIT]
            for ident, entry in shown:
                name, rarity, image = ident
                count = entry["count"]
                image_part = f" • {image}" if image else ""
                lines.append(f"**x{count}** • {name} ({rarity}){image_part}")
            remaining = len(items_sorted) - len(shown)
            if remaining > 0:
                lines.append(f"...and {remaining} more stacks")
            value = "\n".join(lines) or "No cards"
            embed.add_field(name=header, value=value, inline=False)

        # optional banner for the inventory embed (use module-level constant)
        try:
            banner = random.choice(INVENTORY_BANNER_URLS) if INVENTORY_BANNER_URLS else None
            if banner:
                embed.set_image(url=banner)
        except Exception:
            pass

        # set a thumbnail from the first available card image
        first_img = None
        for ident, entry in agg.items():
            img = ident[2]
            if img:
                first_img = img
                break
        if first_img:
            first_img_str = str(first_img).strip()
            if first_img_str.lower().startswith("http://") or first_img_str.lower().startswith("https://"):
                try:
                    embed.set_thumbnail(url=first_img_str)
                except Exception:
                    pass

        embed.set_footer(text=f"Requested by {ctx.author.display_name}")
        embed.timestamp = discord.utils.utcnow()

        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(CardPacks(bot))
