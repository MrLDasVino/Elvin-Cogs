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


class ConfirmBuyView(ui.View):
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
        chosen_card = None
        if rarity_map:
            rarities = list(rarity_map.keys())
            weights = [rarity_map[r] for r in rarities]
            chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]
            rarity_candidates = [c for c in cards if c.get("rarity", "common") == chosen_rarity]
            if rarity_candidates:
                chosen_card = random.choice(rarity_candidates)
        if not chosen_card:
            chosen_card = random.choice(cards)
        await self.cog._add_card_to_user(interaction.guild, interaction.user, chosen_card)
        embed = discord.Embed(title=f"You received: {chosen_card.get('name')}", description=chosen_card.get("text", ""))
        if chosen_card.get("image"):
            embed.set_image(url=chosen_card["image"])
        rarity = chosen_card.get("rarity")
        if rarity:
            embed.set_footer(text=f"Rarity: {rarity}")
        await interaction.response.edit_message(content=None, embed=embed, view=None)

    @ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cardpacks_cancel_buy")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content="Purchase cancelled.", view=None)


class PackCreateModal(ui.Modal, title="Create pack"):
    name = ui.TextInput(label="Pack name", max_length=100)
    price = ui.TextInput(label="Price (integer)", default="0", max_length=20)
    description = ui.TextInput(label="Short description", required=False, max_length=200)
    rarity_weights = ui.TextInput(label="Rarity weights", required=False)

    def __init__(self, cog: "CardPacks"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price_val = int(self.price.value)
        except ValueError:
            await interaction.response.send_message("Price must be an integer.", ephemeral=True)
            return
        rw_text = self.rarity_weights.value.strip()
        rw_map = None
        if rw_text:
            try:
                pairs = [p.strip() for p in rw_text.split(",") if p.strip()]
                rw_map = {}
                for pair in pairs:
                    k, v = pair.split(":")
                    rw_map[k.strip()] = int(v.strip())
            except Exception:
                await interaction.response.send_message("Rarity weights format invalid. Use like common:70,rare:25", ephemeral=True)
                return
        try:
            await self.cog._create_pack(interaction.guild, self.name.value, price_val, self.description.value, rw_map)
        except commands.BadArgument as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await interaction.response.send_message(f"Pack **{self.name.value}** created.", ephemeral=True)


class CardAddModal(ui.Modal, title="Add card to pack"):
    name = ui.TextInput(label="Card name", max_length=100)
    text = ui.TextInput(label="Card text", style=discord.TextStyle.long, required=False)
    image_url = ui.TextInput(label="Optional image URL", required=False)
    rarity = ui.TextInput(label="Rarity (optional)", required=False)

    def __init__(self, cog: "CardPacks", pack_name: str):
        super().__init__()
        self.cog = cog
        self.pack_name = pack_name

    async def on_submit(self, interaction: discord.Interaction):
        rarity_val = self.rarity.value.strip() or "common"
        card = {"name": self.name.value, "text": self.text.value, "image": self.image_url.value, "rarity": rarity_val}
        try:
            await self.cog._add_card_to_pack(interaction.guild, self.pack_name, card)
        except commands.BadArgument as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await interaction.response.send_message(f"Added card **{card['name']}** (rarity: {rarity_val}) to **{self.pack_name}**.", ephemeral=True)


class ManageView(ui.View):
    def __init__(self, cog: "CardPacks"):
        super().__init__(timeout=None)
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
            lines.append(f"**{name}** — {data.get('description','')} — {data.get('price',0)} — {len(data.get('cards',[]))} cards")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @ui.button(label="Add card to pack", style=discord.ButtonStyle.success, custom_id="cardpacks_add_card")
    async def add_card(self, interaction: discord.Interaction, button: ui.Button):
        packs = await self.cog._get_all_packs(interaction.guild)
        if not packs:
            await interaction.response.send_message("No packs available to add cards to.", ephemeral=True)
            return
        sel = PackSelect(self.cog, packs)
        view = ui.View()
        view.add_item(sel)
        await interaction.response.send_message("Choose pack to add a card to", view=view, ephemeral=True)

    @ui.button(label="Export packs", style=discord.ButtonStyle.secondary, custom_id="cardpacks_export_packs")
    async def export_packs(self, interaction: discord.Interaction, button: ui.Button):
        packs = await self.cog._get_all_packs(interaction.guild)
        if not packs:
            await interaction.response.send_message("No packs configured.", ephemeral=True)
            return
        lines = []
        for name, data in packs.items():
            lines.append(f"== {name} ==\nprice: {data.get('price')}\ndesc: {data.get('description')}\ncards:")
            for c in data.get("cards", []):
                lines.append(f"- {c.get('name')} | {c.get('text')} | rarity:{c.get('rarity','common')}")
        await interaction.response.send_message("```\n" + "\n".join(lines) + "\n```", ephemeral=True)


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


class CardPacks(commands.Cog):
    """Card packs cog with inventories, rarities, and persistent manage view"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890123)
        self.config.register_guild(**DEFAULT)
        try:
            bot.add_view(ManageView(self))
        except Exception:
            pass

    async def _get_all_packs(self, guild: Optional[discord.Guild]) -> Dict[str, dict]:
        if not guild:
            return {}
        data = await self.config.guild(guild).all()
        return data.get("packs", {})

    async def _get_pack(self, guild: Optional[discord.Guild], name: str) -> Optional[dict]:
        packs = await self._get_all_packs(guild)
        return packs.get(name)

    async def _create_pack(self, guild: discord.Guild, name: str, price: int, description: str = "", rarity_weights: Optional[dict] = None):
        packs = await self._get_all_packs(guild)
        if name in packs:
            raise commands.BadArgument("Pack already exists")
        packs[name] = {"price": price, "description": description, "cards": [], "rarity_weights": rarity_weights or {}}
        await self.config.guild(guild).packs.set(packs)

    async def _add_card_to_pack(self, guild: discord.Guild, pack_name: str, card: dict):
        packs = await self._get_all_packs(guild)
        if pack_name not in packs:
            raise commands.BadArgument("Pack not found")
        packs[pack_name].setdefault("cards", []).append(card)
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
        if ctx.invoked_subcommand is None:
            if hasattr(ctx, "send_help"):
                await ctx.send_help()
            else:
                await ctx.send("Use the help command for details on cardpacks subcommands.")

    @cardpacks.command(name="buy")
    async def buy(self, ctx: commands.Context):
        """Buy a pack via dropdown"""
        packs = await self._get_all_packs(ctx.guild)
        if not packs:
            await ctx.send("No packs are configured on this server.")
            return
        view = ui.View(timeout=60)
        view.add_item(BuySelect(self, packs))
        await ctx.send("Select a pack to buy", view=view)

    @cardpacks.group(name="manage")
    @checks.guildowner_or_permissions(manage_guild=True)
    async def manage(self, ctx: commands.Context):
        """Manage packs (create, add cards). Admin only."""
        if ctx.invoked_subcommand is None:
            view = ManageView(self)
            await ctx.send("Cardpacks manager", view=view)

    @commands.command(name="inventory")
    @checks.guildowner_or_permissions(manage_guild=True)
    async def inv_get(self, ctx: commands.Context, member: discord.Member):
        """Admin command to view a member's inventory (top-level command, not under manage)"""
        inv = await self._get_user_inventory(ctx.guild, member)
        if not inv:
            await ctx.send(f"{member.display_name} has no cards.")
            return
        lines = [f"- {c.get('name')} (rarity: {c.get('rarity','common')})" for c in inv]
        await ctx.send(f"Inventory for {member.display_name}:\n" + "\n".join(lines))

    @cardpacks.command(name="myinv")
    async def my_inventory(self, ctx: commands.Context):
        """View your own card inventory"""
        inv = await self._get_user_inventory(ctx.guild, ctx.author)
        if not inv:
            await ctx.send("You have no cards.")
            return
        lines = [f"- {c.get('name')} (rarity: {c.get('rarity','common')})" for c in inv]
        await ctx.send("Your inventory:\n" + "\n".join(lines))


def setup(bot):
    bot.add_cog(CardPacks(bot))
