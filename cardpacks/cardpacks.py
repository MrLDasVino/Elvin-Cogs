from typing import Optional, Dict, List
import discord
from discord import ui
from redbot.core import commands, bank, checks, Config
from redbot.core.utils.mod import invoke_help_command

DEFAULT = {"packs": {}}


class BuySelect(ui.Select):
    def __init__(self, cog: "CardPacks", packs: Dict[str, dict]):
        options = []
        for name, data in packs.items():
            label = name
            desc = data.get("description", "")
            price = data.get("price", 0)
            options.append(discord.SelectOption(label=label, description=f"{desc} — {price}"))
        super().__init__(placeholder="Choose a pack to buy", min_values=1, max_values=1, options=options)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        pack_name = self.values[0]
        pack = await self.cog._get_pack(interaction.guild, pack_name)
        if not pack:
            await interaction.response.send_message("Pack not found.", ephemeral=True)
            return

        price = int(pack.get("price", 0))
        # check balance
        can = await bank.can_spend(interaction.user, price)
        currency = await bank.get_currency_name(interaction.guild)
        if not can:
            await interaction.response.send_message(f"You need {price} {currency} to buy this pack.", ephemeral=True)
            return

        # confirm purchase via button view
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

    @ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, button: ui.Button, interaction: discord.Interaction):
        try:
            await bank.withdraw_credits(interaction.user, self.price)
        except Exception as e:
            await interaction.response.edit_message(content=f"Purchase failed: {e}", view=None)
            return

        # give card(s) — here we just pick a random card from the pack
        pack = await self.cog._get_pack(interaction.guild, self.pack_name)
        cards = pack.get("cards", [])
        if not cards:
            msg = f"Pack **{self.pack_name}** contained no cards. Refunding."
            await bank.deposit_credits(interaction.user, self.price)
            await interaction.response.edit_message(content=msg, view=None)
            return

        import random

        card = random.choice(cards)
        # For now we just send the card info; persistence of user-owned cards is left as an exercise
        await interaction.response.edit_message(
            content=f"You bought **{self.pack_name}** and received **{card['name']}**\n{card.get('text','')}",
            view=None,
        )

    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, button: ui.Button, interaction: discord.Interaction):
        await interaction.response.edit_message(content="Purchase cancelled.", view=None)


class PackCreateModal(ui.Modal, title="Create pack"):
    name = ui.TextInput(label="Pack name", max_length=100)
    price = ui.TextInput(label="Price (integer)", default="0", max_length=20)
    description = ui.TextInput(label="Short description", required=False, max_length=200)

    def __init__(self, cog: "CardPacks"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price_val = int(self.price.value)
        except ValueError:
            await interaction.response.send_message("Price must be an integer.", ephemeral=True)
            return
        await self.cog._create_pack(interaction.guild, self.name.value, price_val, self.description.value)
        await interaction.response.send_message(f"Pack **{self.name.value}** created.", ephemeral=True)


class CardAddModal(ui.Modal, title="Add card to pack"):
    name = ui.TextInput(label="Card name", max_length=100)
    text = ui.TextInput(label="Card text", style=discord.TextStyle.long, required=False)
    image_url = ui.TextInput(label="Optional image URL", required=False)

    def __init__(self, cog: "CardPacks", pack_name: str):
        super().__init__()
        self.cog = cog
        self.pack_name = pack_name

    async def on_submit(self, interaction: discord.Interaction):
        card = {"name": self.name.value, "text": self.text.value, "image": self.image_url.value}
        await self.cog._add_card_to_pack(interaction.guild, self.pack_name, card)
        await interaction.response.send_message(f"Added card **{card['name']}** to **{self.pack_name}**.", ephemeral=True)


class ManageView(ui.View):
    def __init__(self, cog: "CardPacks"):
        super().__init__(timeout=None)
        self.cog = cog

    @ui.button(label="Create pack", style=discord.ButtonStyle.primary, custom_id="create_pack")
    async def create_pack(self, button: ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(PackCreateModal(self.cog))

    @ui.button(label="List packs", style=discord.ButtonStyle.secondary, custom_id="list_packs")
    async def list_packs(self, button: ui.Button, interaction: discord.Interaction):
        packs = await self.cog._get_all_packs(interaction.guild)
        if not packs:
            await interaction.response.send_message("No packs configured.", ephemeral=True)
            return
        lines = []
        for name, data in packs.items():
            lines.append(f"**{name}** — {data.get('description','')} — {data.get('price',0)} — {len(data.get('cards',[]))} cards")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @ui.button(label="Add card to pack", style=discord.ButtonStyle.success, custom_id="add_card")
    async def add_card(self, button: ui.Button, interaction: discord.Interaction):
        packs = await self.cog._get_all_packs(interaction.guild)
        if not packs:
            await interaction.response.send_message("No packs available to add cards to.", ephemeral=True)
            return
        # present a select to choose pack
        sel = PackSelect(self.cog, packs)
        view = ui.View()
        view.add_item(sel)
        await interaction.response.send_message("Choose pack to add a card to", view=view, ephemeral=True)


class PackSelect(ui.Select):
    def __init__(self, cog: "CardPacks", packs: Dict[str, dict]):
        options = []
        for name in packs.keys():
            options.append(discord.SelectOption(label=name))
        super().__init__(placeholder="Select pack", min_values=1, max_values=1, options=options)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        pack_name = self.values[0]
        await interaction.response.send_modal(CardAddModal(self.cog, pack_name))


class CardPacks(commands.Cog):
    """Card packs with buy/manage UI"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.config.register_guild(**DEFAULT)

    # helper storage operations
    async def _get_all_packs(self, guild: discord.Guild) -> Dict[str, dict]:
        data = await self.config.guild(guild).all()
        return data.get("packs", {})

    async def _get_pack(self, guild: discord.Guild, name: str) -> Optional[dict]:
        packs = await self._get_all_packs(guild)
        return packs.get(name)

    async def _create_pack(self, guild: discord.Guild, name: str, price: int, description: str = ""):
        packs = await self._get_all_packs(guild)
        if name in packs:
            raise commands.BadArgument("Pack already exists")
        packs[name] = {"price": price, "description": description, "cards": []}
        await self.config.guild(guild).packs.set(packs)

    async def _add_card_to_pack(self, guild: discord.Guild, pack_name: str, card: dict):
        packs = await self._get_all_packs(guild)
        if pack_name not in packs:
            raise commands.BadArgument("Pack not found")
        packs[pack_name].setdefault("cards", []).append(card)
        await self.config.guild(guild).packs.set(packs)

    # top-level group
    @commands.group()
    async def cardpacks(self, ctx: commands.Context):
        """Cardpacks main command"""
        if ctx.invoked_subcommand is None:
            await invoke_help_command(ctx)

    # buy subcommand
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

    # manage subcommand (guildowner or manage_guild)
    @cardpacks.group(name="manage")
    @checks.guildowner_or_permissions(manage_guild=True)
    async def manage(self, ctx: commands.Context):
        """Manage packs (create, add cards)"""
        if ctx.invoked_subcommand is None:
            view = ManageView(self)
            await ctx.send("Cardpacks manager", view=view)

    @manage.command(name="export")
    @checks.guildowner_or_permissions(manage_guild=True)
    async def export(self, ctx: commands.Context):
        """Export packs data (debug/admin)"""
        packs = await self._get_all_packs(ctx.guild)
        if not packs:
            await ctx.send("No packs configured.")
            return
        # simple text dump; admins can copy-paste
        lines = []
        for name, data in packs.items():
            lines.append(f"== {name} ==\nprice: {data.get('price')}\ndesc: {data.get('description')}\ncards:")
            for c in data.get("cards", []):
                lines.append(f"- {c.get('name')} | {c.get('text')}")
        await ctx.send("```\n" + "\n".join(lines) + "\n```")

    # simple help fallback
    @cardpacks.command(name="help")
    async def cardpacks_help(self, ctx: commands.Context):
        """Show help"""
        await invoke_help_command(ctx)


def setup(bot):
    bot.add_cog(CardPacks(bot))
