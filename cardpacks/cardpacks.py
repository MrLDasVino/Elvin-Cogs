import random
from typing import Optional, Dict, List
import discord
from discord import ui
from redbot.core import commands, bank, checks, Config

DEFAULT = {"packs": {}, "inventories": {}}


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
            options.append(discord.SelectOption(label=label, description=f"{desc} — {price}", value=name))
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
    def __init__(self, cog: "CardPacks", pack_name: str, price: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.pack_name = pack_name
        self.price = price

    @ui.button(label="Confirm", style=discord.ButtonStyle.green, custom_id="cardpacks_confirm_buy")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        try:
            await bank.withdraw_credits(interaction.user, self.price)
        except Exception as e:
            await interaction.response.edit_message(content=f"Purchase failed: {e}", view=None)
            return

        pack = await self.cog._get_pack(interaction.guild, self.pack_name)
        cards = pack.get("cards", [])
        if not cards:
            msg = f"Pack **{self.pack_name}** contained no cards. Refunding."
            await bank.deposit_credits(interaction.user, self.price)
            await interaction.response.edit_message(content=msg, view=None)
            return

        packs_all = await self.cog._get_all_packs(interaction.guild)
        rarity_map = _rarity_weights_map(packs_all, self.pack_name)

        pull_count = int(pack.get("pull_count", 1))
        pulled: List[dict] = []
        for _ in range(max(1, pull_count)):
            chosen_card = None

            # If any card defines an explicit 'chance' value, use per-card chances
            cards_with_chance = [c for c in cards if c.get("chance") is not None]
            if cards_with_chance:
                # Build weights using the numeric chance (percent) value; cards without chance get 0 weight
                weights = [float(c.get("chance", 0.0)) for c in cards]
                if sum(weights) > 0:
                    chosen_card = random.choices(cards, weights=weights, k=1)[0]
                else:
                    chosen_card = random.choice(cards)
            else:
                # existing rarity-based selection
                if rarity_map:
                    rarities = list(rarity_map.keys())
                    weights = [rarity_map[r] for r in rarities]
                    chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]
                    rarity_candidates = [c for c in cards if c.get("rarity", "common") == chosen_rarity]
                    if rarity_candidates:
                        chosen_card = random.choice(rarity_candidates)
                if not chosen_card:
                    chosen_card = random.choice(cards)

            pulled.append(chosen_card)
            await self.cog._add_card_to_user(interaction.guild, interaction.user, chosen_card)

        embed = discord.Embed(title=f"You opened: {self.pack_name}")
        description_lines = []
        for c in pulled:
            line = f"**{c.get('name')}**"
            r = c.get("rarity")
            if r:
                line += f" — {r}"
            txt = c.get("text")
            if txt:
                line += f"\n{txt}"
            if c.get("chance") is not None:
                line += f"\nChance: {c.get('chance')}%"
            description_lines.append(line)
        embed.description = "\n\n".join(description_lines)
        thumbnail = pack.get("thumbnail")
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        await interaction.response.edit_message(content=None, embed=embed, view=None)

    @ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cardpacks_cancel_buy")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content="Purchase cancelled.", view=None)


class PackCreateModal(ui.Modal, title="Create pack"):
    name = ui.TextInput(label="Pack name", max_length=100)
    price = ui.TextInput(label="Price (integer)", default="0", max_length=20)
    description = ui.TextInput(label="Short description", required=False, max_length=200)
    pull_count = ui.TextInput(label="Cards pulled on buy (integer, default 1)", default="1", max_length=3, required=False)
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
            pull_val = int(self.pull_count.value) if self.pull_count.value.strip() else 1
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
        self.pull_count.default = str(pack_data.get("pull_count", 1))
        self.thumbnail_url.default = pack_data.get("thumbnail") or ""

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.name.value.strip()
        try:
            price_val = int(self.price.value)
        except ValueError:
            await interaction.response.send_message("Price must be an integer.", ephemeral=True)
            return
        try:
            pull_val = int(self.pull_count.value) if self.pull_count.value.strip() else 1
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
        lines = []
        for name, data in packs.items():
            lines.append(f"**{name}** — {data.get('description','')} — {data.get('price',0)} — {len(data.get('cards',[]))} cards — pulls:{data.get('pull_count',1)}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

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

    @ui.button(label="Edit/Delete pack", style=discord.ButtonStyle.primary, custom_id="cardpacks_edit_pack")
    async def edit_pack(self, interaction: discord.Interaction, button: ui.Button):
        packs = await self.cog._get_all_packs(interaction.guild)
        if not packs:
            await interaction.response.send_message("No packs configured.", ephemeral=True)
            return
        sel = PackManageSelect(self.cog, packs)
        view = TimedView(timeout=60)
        view.add_item(sel)
        await interaction.response.send_message("Select pack to edit or delete", view=view, ephemeral=True)

    @ui.button(label="Edit/Delete card", style=discord.ButtonStyle.primary, custom_id="cardpacks_edit_card")
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
            lines.append(f"== {name} ==\nprice: {data.get('price')}\ndesc: {data.get('description')}\npulls: {data.get('pull_count',1)}\nthumbnail: {data.get('thumbnail')}\ncards:")
            for c in data.get("cards", []):
                chance_part = f" chance:{c.get('chance')}" if c.get("chance") is not None else ""
                lines.append(f"- {c.get('name')} | {c.get('text')} | rarity:{c.get('rarity','common')}{chance_part}")
        await interaction.response.send_message("```\n" + "\n".join(lines) + "\n```", ephemeral=True)


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

    async def _add_card_to_user(self, guild: discord.Guild, user: discord.abc.User, card: dict):
        cur = await self._get_user_inventory(guild, user)
        cur.append(card)
        await self._set_user_inventory(guild, user, cur)

    @commands.group(invoke_without_command=True)
    async def cardpacks(self, ctx: commands.Context):
        """Cardpacks main command"""
        invoked = ctx.message.content[len(ctx.clean_prefix) :].strip()
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

        inv = await self._get_user_inventory(ctx.guild, target)
        if not inv:
            if target == ctx.author:
                await ctx.send("You have no cards.")
            else:
                await ctx.send(f"{target.display_name} has no cards.")
            return
        lines = [f"- {c.get('name')} (rarity: {c.get('rarity','common')})" for c in inv]
        if target == ctx.author:
            await ctx.send("Your inventory:\n" + "\n".join(lines))
        else:
            await ctx.send(f"Inventory for {target.display_name}:\n" + "\n".join(lines))


def setup(bot):
    bot.add_cog(CardPacks(bot))
