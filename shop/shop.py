import asyncio
import discord
from typing import Dict

from redbot.core import commands, Config, checks, bank
from discord.ui import View, button, Button, Modal, TextInput, Select


class Shop(commands.Cog):
    """A fully async shop cog with buttons, modals, and Red’s bank integration."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210)
        default_guild = {
            "shops": {}
        }  # shop_name → {description, stock: {item: {price, amount, role_id?}}}
        default_user = {"inventory": {}}  # item_name → count
        self.config.register_guild(**default_guild)
        self.config.register_user(**default_user)

    # --------------------
    # ADMIN COMMANDS
    # --------------------

    @commands.group()
    @checks.admin()
    async def shop(self, ctx):
        """Shop administration commands."""
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @shop.command()
    async def manage(self, ctx):
        """Send a button to open the shop‐manage modal."""
        view = ManageView(self.config, ctx.guild.id)
        await view._populate()
        await ctx.send("Click below to create or edit your shop:", view=view)
        
    @shop.command()
    async def addstock(self, ctx, shop_name: str):
        """Add or restock an item via modal."""
        guild_conf = self.config.guild(ctx.guild)
        shops = await guild_conf.shops()
        if shop_name not in shops:
            return await ctx.send(f"❌ Shop `{shop_name}` doesn’t exist.")
        await ctx.send_modal(StockModal(self.config, ctx.guild.id, shop_name))

    @shop.command()
    async def addrole(
        self, ctx, shop_name: str, role: discord.Role, price: int
    ):
        """Add a Discord role as a purchasable stock item."""
        guild_conf = self.config.guild(ctx.guild)
        shops = await guild_conf.shops()
        if shop_name not in shops:
            return await ctx.send(f"❌ Shop `{shop_name}` not found.")
        stock = shops[shop_name]["stock"]
        stock[role.name] = {"price": price, "amount": 1, "role_id": role.id}
        shops[shop_name]["stock"] = stock
        await guild_conf.shops.set(shops)
        await ctx.send(f"✅ Role `{role.name}` added to `{shop_name}` for {price} credits.")

    @shop.command()
    async def give(
        self, ctx, member: discord.Member, item_name: str, amount: int = 1
    ):
        """Give an item to a user (inventory only, not roles)."""
        user_conf = self.config.user(member)
        inv = await user_conf.inventory()
        inv[item_name] = inv.get(item_name, 0) + amount
        await user_conf.inventory.set(inv)
        await ctx.send(f"✅ Gave {amount}× `{item_name}` to {member.mention}.")

    @shop.command()
    async def clearinv(self, ctx, member: discord.Member):
        """Clear a user's custom inventory (does not remove roles)."""
        await self.config.user(member).inventory.clear()
        await ctx.send(f"✅ Cleared inventory of {member.mention}.") 

    # --------------------
    # USER COMMANDS
    # --------------------

    @commands.command()
    async def buy(self, ctx):
        """Browse shops and buy items via buttons & modals."""
        shops = await self.config.guild(ctx.guild).shops()
        if not shops:
            return await ctx.send("❌ There are no shops to browse.")
        view = ShopSelectView(self.config, ctx.guild.id, ctx.author.id, mode="buy")
        await ctx.send("🛒 **Select a shop to buy from:**", view=view)

    @commands.command()
    async def gift(self, ctx):
        """Gift an item to another user."""
        shops = await self.config.guild(ctx.guild).shops()
        if not shops:
            return await ctx.send("❌ There are no shops to browse.")
        view = ShopSelectView(self.config, ctx.guild.id, ctx.author.id, mode="gift")
        await ctx.send("🎁 **Select a shop to gift from:**", view=view)

    @commands.command()
    async def redeem(self, ctx):
        """Redeem a voucher or special code via modal."""
        await ctx.send_modal(RedeemModal(self.config, ctx.author.id))        
        
# --------------------
# BUTTON‐LAUNCH VIEW
# --------------------
class ManageView(View):
    """Dropdown to pick a shop to edit, or click to create a new one."""

    def __init__(self, config: Config, guild_id: int):
        super().__init__(timeout=None)
        self.config = config
        self.guild_id = guild_id

    async def _populate(self):
        """Fill in the Select + New‐Shop button synchronously."""
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        options = [discord.SelectOption(label=n, value=n) for n in shops]
        if options:
            self.add_item(ShopSelect(options, self.config, self.guild_id))
        self.add_item(NewShopButton(self.config, self.guild_id))


class ShopSelect(Select):
    def __init__(self, options, config: Config, guild_id: int):
        super().__init__(
            placeholder="Select a shop to edit…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="shop_manage_select",
        )
        self.config = config
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        shop_name = self.values[0]
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        data = shops[shop_name]
        # open the modal with the existing values pre-filled
        await interaction.response.send_modal(
            ShopModal(
                self.config,
                self.guild_id,
                original_name=shop_name,
                description=data.get("description", ""),
                thumbnail=data.get("thumbnail", ""),
            )
        )


class NewShopButton(Button):
    def __init__(self, config: Config, guild_id: int):
        super().__init__(
            label="Create New Shop",
            style=discord.ButtonStyle.success,
            custom_id="shop_manage_new",
        )
        self.config = config
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        # empty fields for a brand-new shop
        await interaction.response.send_modal(
            ShopModal(self.config, self.guild_id)
        )    



# --------------------
# MODALS
# --------------------

class ShopModal(Modal, title="Create or Edit Shop"):
    shop_name = TextInput(
        label="Shop Name",
        placeholder="unique_id",
        required=True,
    )
    description = TextInput(
        label="Description (optional)",
        style=discord.TextStyle.long,
        required=False,
    )
    thumbnail = TextInput(
        label="Thumbnail URL (optional)",
        style=discord.TextStyle.short,
        required=False,
        placeholder="https://…jpg",
    )

    def __init__(
        self,
        config: Config,
        guild_id: int,
        *,
        original_name: str = None,
        description: str = "",
        thumbnail: str = "",
    ):
        super().__init__()
        self.config = config
        self.guild_id = guild_id
        # if original_name is set, we’re editing an existing shop
        self.original_name = original_name
        # prefill fields when editing
        if original_name:
            self.shop_name.default = original_name
            self.description.default = description
            self.thumbnail.default = thumbnail

    async def on_submit(self, interaction: discord.Interaction):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()

        new_name = self.shop_name.value.strip()
        desc = self.description.value.strip()
        thumb = self.thumbnail.value.strip()

        # if renaming, carry over existing stock
        stock = {}
        if self.original_name and self.original_name in shops:
            stock = shops[self.original_name].get("stock", {})
            # remove the old key if the name actually changed
            if new_name != self.original_name:
                shops.pop(self.original_name, None)

        # save the new/updated shop
        shops[new_name] = {
            "description": desc,
            "thumbnail": thumb,
            "stock": stock,
        }

        await guild_conf.shops.set(shops)

        await interaction.response.send_message(
            f"✅ Shop `{new_name}` created/updated.", ephemeral=True
        )


class StockModal(Modal, title="Add / Restock Item"):
    item = TextInput(label="Item Name", required=True)
    price = TextInput(label="Price (credits)", required=True)
    amount = TextInput(label="Amount to add", required=True)

    def __init__(self, config: Config, guild_id: int, shop_name: str):
        super().__init__()
        self.config = config
        self.guild_id = guild_id
        self.shop_name = shop_name

    async def on_submit(self, interaction: discord.Interaction):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        stock = shops[self.shop_name]["stock"]
        name = self.item.value
        old = stock.get(name, {"amount": 0})
        stock[name] = {
            "price": int(self.price.value),
            "amount": old.get("amount", 0) + int(self.amount.value),
        }
        shops[self.shop_name]["stock"] = stock
        await guild_conf.shops.set(shops)
        await interaction.response.send_message(
            f"✅ Restocked `{name}` (+{self.amount.value}).", ephemeral=True
        )


class RedeemModal(Modal, title="Redeem Code"):
    code = TextInput(label="Enter your code", required=True)

    def __init__(self, config: Config, user_id: int):
        super().__init__()
        self.config = config
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        # Placeholder for your voucher logic
        await interaction.response.send_message(
            "✅ Code redeemed (logic not implemented).", ephemeral=True
        )


class GiftModal(Modal, title="Gift Item"):
    recipient = TextInput(label="Recipient (mention or ID)", required=True)
    amount = TextInput(label="Amount", required=True)

    def __init__(
        self,
        config: Config,
        guild_id: int,
        gifting_user: int,
        shop_name: str,
        item_name: str,
        price: int,
    ):
        super().__init__()
        self.config = config
        self.guild_id = guild_id
        self.gifting_user = gifting_user
        self.shop_name = shop_name
        self.item_name = item_name
        self.price = price

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.gifting_user:
            return await interaction.response.send_message(
                "This gift dialog isn’t for you.", ephemeral=True
            )

        # Parse member
        raw = self.recipient.value.strip()
        member_id = int(raw.strip("<@!>")) if raw.startswith("<@") else int(raw)
        member = interaction.guild.get_member(member_id)
        if not member:
            return await interaction.response.send_message(
                "❌ Recipient not found.", ephemeral=True
            )

        amount = int(self.amount.value)
        total = self.price * amount
        bal = await bank.get_balance(interaction.user)
        if bal < total:
            return await interaction.response.send_message(
                "❌ Insufficient funds.", ephemeral=True
            )

        # Withdraw from gifter
        await bank.withdraw_credits(interaction.user, total_cost)

        # Add to recipient inventory
        user_conf = self.config.user(member)
        inv = await user_conf.inventory()
        inv[self.item_name] = inv.get(self.item_name, 0) + amount
        await user_conf.inventory.set(inv)

        # Assign role if applicable
        shops = await self.config.guild_from_id(self.guild_id).shops()
        entry = shops[self.shop_name]["stock"].get(self.item_name, {})
        if "role_id" in entry:
            role = interaction.guild.get_role(entry["role_id"])
            if role:
                await member.add_roles(role)

        # Decrement shop stock
        entry["amount"] -= amount
        shops[self.shop_name]["stock"][self.item_name] = entry
        await self.config.guild_from_id(self.guild_id).shops.set(shops)

        await interaction.response.send_message(
            f"✅ Gifted {amount}× `{self.item_name}` to {member.mention}.",
            ephemeral=True,
        )


# --------------------
# VIEWS & BUTTONS
# --------------------

class ShopSelectView(View):
    def __init__(
        self, config: Config, guild_id: int, user_id: int, mode: str = "buy"
    ):
        super().__init__(timeout=60)
        self.config = config
        self.guild_id = guild_id
        self.user_id = user_id
        self.mode = mode  # "buy" or "gift"
        asyncio.create_task(self._populate_shops())

    async def _populate_shops(self):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        for shop_name in shops:
            btn = Button(label=shop_name, style=discord.ButtonStyle.primary)
            btn.callback = self._make_shop_callback(shop_name)
            self.add_item(btn)
        cancel = Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel.callback = self._cancel
        self.add_item(cancel)

    def _make_shop_callback(self, shop_name: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                return await interaction.response.send_message(
                    "This menu isn’t for you.", ephemeral=True
                )
            await interaction.response.edit_message(
                content=f"**{shop_name}** – Select an item to {self.mode}:",
                view=ItemListView(
                    self.config, self.guild_id, self.user_id, self.mode, shop_name
                ),
            )
        return callback

    async def _cancel(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(
                "Not your menu.", ephemeral=True
            )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Cancelled.", view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class ItemListView(View):
    def __init__(
        self,
        config: Config,
        guild_id: int,
        user_id: int,
        mode: str,
        shop_name: str,
    ):
        super().__init__(timeout=60)
        self.config = config
        self.guild_id = guild_id
        self.user_id = user_id
        self.mode = mode
        self.shop_name = shop_name
        asyncio.create_task(self._populate_items())

    async def _populate_items(self):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        stock = shops[self.shop_name]["stock"]
        for item_name, entry in stock.items():
            label = f"{item_name} ({entry['price']}cr, 🗃️{entry['amount']})"
            btn = Button(label=label, style=discord.ButtonStyle.secondary)
            btn.callback = self._make_item_callback(item_name, entry["price"])
            self.add_item(btn)
        back = Button(label="Back", style=discord.ButtonStyle.success)
        back.callback = self._go_back
        self.add_item(back)
        cancel = Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel.callback = self._cancel
        self.add_item(cancel)

    def _make_item_callback(self, item_name: str, price: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                return await interaction.response.send_message(
                    "This menu isn’t for you.", ephemeral=True
                )
            if self.mode == "buy":
                await interaction.response.send_modal(
                    BuyModal(
                        self.config,
                        self.guild_id,
                        self.user_id,
                        self.shop_name,
                        item_name,
                        price,
                    )
                )
            else:  # gift
                await interaction.response.send_modal(
                    GiftModal(
                        self.config,
                        self.guild_id,
                        self.user_id,
                        self.shop_name,
                        item_name,
                        price,
                    )
                )
        return callback

    async def _go_back(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(
                "Not your menu.", ephemeral=True
            )
        await interaction.response.edit_message(
            content="Select a shop to browse:", 
            view=ShopSelectView(self.config, self.guild_id, self.user_id, self.mode)
        )

    async def _cancel(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(
                "Not your menu.", ephemeral=True
            )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Cancelled.", view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class BuyModal(Modal, title="Buy Item"):
    quantity = TextInput(label="Quantity", placeholder="1", required=True)

    def __init__(
        self,
        config: Config,
        guild_id: int,
        buyer_id: int,
        shop_name: str,
        item_name: str,
        price: int,
    ):
        super().__init__()
        self.config = config
        self.guild_id = guild_id
        self.buyer_id = buyer_id
        self.shop_name = shop_name
        self.item_name = item_name
        self.price = price

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.buyer_id:
            return await interaction.response.send_message(
                "This purchase isn’t for you.", ephemeral=True
            )

        qty = max(1, int(self.quantity.value))
        total_cost = self.price * qty
        bal = await bank.get_balance(interaction.user)
        if bal < total_cost:
            return await interaction.response.send_message(
                f"❌ You need {total_cost} credits but only have {bal}.",
                ephemeral=True,
            )

        # Deduct currency
        await bank.withdraw_credits(interaction.user, total_cost)

        # Update user inventory
        user_conf = self.config.user(interaction.user)
        inv = await user_conf.inventory()
        inv[self.item_name] = inv.get(self.item_name, 0) + qty
        await user_conf.inventory.set(inv)

        # Assign role if this item is a role
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        entry = shops[self.shop_name]["stock"].get(self.item_name, {})
        if entry.get("role_id"):
            role = interaction.guild.get_role(entry["role_id"])
            if role:
                await interaction.user.add_roles(role)

        # Decrement shop stock
        entry["amount"] -= qty
        shops[self.shop_name]["stock"][self.item_name] = entry
        await guild_conf.shops.set(shops)

        await interaction.response.send_message(
            f"✅ You bought {qty}× `{self.item_name}` for {total_cost} credits.",
            ephemeral=True,
        )

