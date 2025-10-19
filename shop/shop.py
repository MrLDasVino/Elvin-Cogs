import asyncio
import discord
from typing import Dict

from redbot.core import commands, Config, checks, bank
from discord.ui import View, button, Button, Modal, TextInput, Select


class Shop(commands.Cog):
    """A shop cog with buttons, modals, and Red’s bank integration."""

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

    @commands.group(invoke_without_command=True)    
    async def shop(self, ctx):
        """Shop commands."""
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @shop.command()
    @checks.admin()
    async def manage(self, ctx):
        """Send a button to open the shop‐manage modal."""
        view = ManageView(self.config, ctx.guild.id)
        await view._populate()
        await ctx.send("Click below to create or edit your shop:", view=view)
        
    @shop.command()
    @checks.admin()    
    async def addstock(self, ctx):
        """Pick a shop to restock, then open the restock modal."""
        guild_conf = self.config.guild(ctx.guild)
        shops = await guild_conf.shops()
        if not shops:
            return await ctx.send("❌ There are no shops to restock.")
   
        view = AddStockView(self.config, ctx.guild.id)
        await view.populate()                    
        msg = await ctx.send("Select a shop to restock:", view=view)
        view.message = msg      
        
    @shop.command()
    @checks.admin()
    async def removestock(self, ctx):
        """Remove an item from a shop."""
        guild_conf = self.config.guild(ctx.guild)
        shops = await guild_conf.shops()
        if not shops:
            return await ctx.send("❌ There are no shops to edit.")
        view = RemoveStockView(self.config, ctx.guild.id)
        await view.populate()
        msg = await ctx.send("Select a shop to remove stock from:", view=view)
        view.message = msg       


    @shop.command()
    @checks.admin()
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
    @checks.admin()
    async def clearinv(self, ctx, member: discord.Member):
        """Clear a user's custom inventory (does not remove roles)."""
        await self.config.user(member).inventory.clear()
        await ctx.send(f"✅ Cleared inventory of {member.mention}.") 

    # --------------------
    # USER COMMANDS
    # --------------------

    @shop.command()
    async def buy(self, ctx):
        """Browse shops via an embed + dropdown, then pick item & amount."""
        guild_conf = self.config.guild(ctx.guild)
        shops = await guild_conf.shops()
        if not shops:
            return await ctx.send("❌ There are no shops to browse.")

        embed = discord.Embed(
            title="🛒 Browse Shops",
            description="Select a shop from the dropdown below:",
            color=discord.Color.random()
        )
        view = ShopEmbedView(self.config, ctx.guild.id, ctx.author.id)
        await view.populate_shops(shops)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

    @shop.command()
    async def gift(self, ctx):
        """Gift an item to another user."""
        guild_conf = self.config.guild(ctx.guild)
        shops = await guild_conf.shops()
        if not shops:
            return await ctx.send("❌ There are no shops to browse.")

        embed = discord.Embed(
            title="🎁 Gift Items",
            description="Select a shop from the dropdown below:",
            color=discord.Color.random()
        )
        view = ShopEmbedView(self.config, ctx.guild.id, ctx.author.id, mode="gift")
        await view.populate_shops(shops)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        
    @shop.command(name="inventory")
    async def inventory(self, ctx, member: discord.Member = None):
        """Show the items you or another member have bought."""
        target = member or ctx.author
        user_conf = self.config.user(target)
        inv = await user_conf.inventory()
        if not inv:
            return await ctx.send(f"❌ {target.display_name} has no items.")

        embed = discord.Embed(
            title=f"{target.display_name}'s Inventory",
            color=discord.Color.random()
        )
        # show avatar next to the embed title
        if target.avatar:
            embed.set_author(name=target.display_name, icon_url=target.avatar.url)
        else:
            embed.set_author(name=target.display_name)

        # one field per item
        for item_name, count in inv.items():
            embed.add_field(
                name=f"🔸 {item_name}",
                value=f"Quantity: {count}",
                inline=False
            )

        await ctx.send(embed=embed)        
     
        
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
    item = TextInput(
        label="Item Name",
        placeholder="leave blank to add a role",
        required=False,
    )
    role = TextInput(
        label="Role (name, mention or ID)",
        placeholder="leave blank for item",
        required=False,
    )
    description = TextInput(
        label="Description (optional)",
        style=discord.TextStyle.long,
        required=False,
        placeholder="Short blurb about this item",
    )    
    price = TextInput(label="Price (credits)", required=True)
    amount = TextInput(
        label="Amount to add (blank = ∞)",
        required=False,
    )

    def __init__(self, config: Config, guild_id: int, shop_name: str):
        super().__init__()
        self.config = config
        self.guild_id = guild_id
        self.shop_name = shop_name

    async def on_submit(self, interaction: discord.Interaction):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        stock = shops[self.shop_name]["stock"]

        # Resolve item vs role by name/mention/ID
        raw_item = (self.item.value or "").strip()
        raw_role = (self.role.value or "").strip()
        if not raw_item and not raw_role:
            return await interaction.response.send_message(
                "❌ You must fill either Item Name or Role field.", ephemeral=True
            )
        if raw_item and raw_role:
            return await interaction.response.send_message(
                "❌ You can’t add both an item and a role at once.", ephemeral=True
            )

        if raw_role:
            role_obj = None
            # 1) Mention syntax
            if raw_role.startswith("<@&") and raw_role.endswith(">"):
                rid = int(raw_role[3:-1])
                role_obj = interaction.guild.get_role(rid)
            # 2) Raw ID
            elif raw_role.isdigit():
                role_obj = interaction.guild.get_role(int(raw_role))
            # 3) Exact name match (case-insensitive)
            else:
                matches = [
                    r for r in interaction.guild.roles
                    if r.name.lower() == raw_role.lower()
                ]
                if len(matches) == 1:
                    role_obj = matches[0]
                elif len(matches) > 1:
                    dupes = ", ".join(r.name for r in matches)
                    return await interaction.response.send_message(
                        f"❌ Ambiguous role name – matched: {dupes}", ephemeral=True
                    )
            if not role_obj:
                return await interaction.response.send_message(
                    f"❌ Role `{raw_role}` not found.", ephemeral=True
                )

            name = role_obj.name
            role_id = role_obj.id
        else:
            name = raw_item
            role_id = None

        # Price always required
        price = int(self.price.value)

        # Amount: blank = infinite, else int
        raw_amt = (self.amount.value or "").strip()
        if raw_amt == "":
            new_amount = None
        else:
            add_amt = int(raw_amt)
            old_amt = stock.get(name, {}).get("amount")
            if old_amt is None:
                new_amount = None
            else:
                new_amount = old_amt + add_amt
                
        raw_desc = (self.description.value or "").strip()
        old_entry = stock.get(name, {})
        final_desc = raw_desc or old_entry.get("description", "")                

        # Write stock entry
        entry = {"price": price, "amount": new_amount, "description": final_desc}
        if role_id:
            entry["role_id"] = role_id
        stock[name] = entry

        shops[self.shop_name]["stock"] = stock
        await guild_conf.shops.set(shops)
        await interaction.response.send_message(
            f"✅ {'Added' if raw_role else 'Restocked'} `{name}` "
            f"for {price} credits"
            f"{'' if new_amount is None else f', amount={new_amount}'}."
            , ephemeral=True
        )


class GiftModal(Modal, title="Gift Item"):
    recipient = TextInput(label="Recipient (name, mention or ID)", required=True)
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

        # Parse recipient by mention, ID, or exact name/nickname
        raw = self.recipient.value.strip()
        member = None

        # 1) Mention syntax
        if raw.startswith("<@") and raw.endswith(">"):
            member_id = int(raw.strip("<@!>"))
            member = interaction.guild.get_member(member_id)
        # 2) Raw ID
        elif raw.isdigit():
            member = interaction.guild.get_member(int(raw))
        # 3) Exact username or nickname (case-insensitive)
        else:
            lowered = raw.lower()
            matches = [
                m for m in interaction.guild.members
                if m.name.lower() == lowered or m.display_name.lower() == lowered
            ]
            if len(matches) == 1:
                member = matches[0]
            elif len(matches) > 1:
                dupes = ", ".join(m.name for m in matches)
                return await interaction.response.send_message(
                    f"❌ Ambiguous user name – matched: {dupes}", ephemeral=True
                )

        if not member:
            return await interaction.response.send_message(
                "❌ Recipient not found.", ephemeral=True
            )

        amount = int(self.amount.value)
        total_cost = self.price * amount
        bal = await bank.get_balance(interaction.user)
        if bal < total_cost:
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
        if entry.get("amount") is not None:
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


    async def populate_items(self):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        stock = shops[self.shop_name]["stock"]
        for item_name, entry in stock.items():
            amt = entry.get("amount")
            amt_display = "∞" if amt is None else str(amt)
            label = f"{item_name} ({entry['price']}cr, 🗃️{amt_display})"
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
        if entry.get("amount") is not None:
            entry["amount"] -= qty
        shops[self.shop_name]["stock"][self.item_name] = entry
        await guild_conf.shops.set(shops)

        await interaction.response.send_message(
            f"✅ You bought {qty}× `{self.item_name}` for {total_cost} credits.",
            ephemeral=True,
        )

class AddStockView(View):
    """View that shows a dropdown of shops to restock."""

    def __init__(self, config: Config, guild_id: int):
        super().__init__(timeout=60)
        self.config = config
        self.guild_id = guild_id
        
    async def on_timeout(self):
        # disable all buttons/dropdowns
        for child in self.children:
            child.disabled = True
        # edit the original message to show it timed out
        try:
            await self.message.edit(
                content="⌛ Restock session timed out.", view=self
            )
        except Exception:
            pass        

    async def populate(self):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        options = [
            discord.SelectOption(label=name, value=name)
            for name in shops.keys()
        ]
        # shop selector
        if options:
            self.add_item(
                AddStockSelect(options, self.config, self.guild_id)
            )
        # cancel button
        cancel = Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel.callback = self._cancel
        self.add_item(cancel)

    async def _cancel(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Cancelled.", view=self)


class AddStockSelect(Select):
    """Dropdown of existing shops—opens StockModal on selection."""

    def __init__(self, options, config: Config, guild_id: int):
        super().__init__(
            placeholder="Choose a shop…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="addstock_shop_select",
        )
        self.config = config
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        shop_name = self.values[0]
        # launch the existing StockModal with chosen shop
        await interaction.response.send_modal(
            StockModal(self.config, self.guild_id, shop_name)
        )

class ShopDropdownView(View):
    """View that shows a dropdown of shops to choose from."""
    def __init__(self, config: Config, guild_id: int, user_id: int, mode: str = "buy"):
        super().__init__(timeout=60)
        self.config = config
        self.guild_id = guild_id
        self.user_id = user_id
        self.mode = mode

    async def populate(self):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        options = [
            discord.SelectOption(label=name, value=name)
            for name in shops.keys()
        ]
        # add our dropdown
        self.add_item(
            ShopDropdownSelect(options, self.config, self.guild_id, self.user_id, self.mode)
        )
        # optional cancel button
        cancel = Button(label="Cancel", style=discord.ButtonStyle.danger)
        async def _cancel(interaction: discord.Interaction):
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(content="Cancelled.", view=self)
        cancel.callback = _cancel
        self.add_item(cancel)


class ShopDropdownSelect(Select):
    """Dropdown listing all shops; on select, shows the items view."""
    def __init__(
        self,
        options: list[discord.SelectOption],
        config: Config,
        guild_id: int,
        user_id: int,
        mode: str,
    ):
        super().__init__(
            placeholder="Choose a shop…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="shop_buy_dropdown",
        )
        self.config = config
        self.guild_id = guild_id
        self.user_id = user_id
        self.mode = mode

    async def callback(self, interaction: discord.Interaction):
        shop_name = self.values[0]
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(
                "This menu isn’t for you.", ephemeral=True
            )
        # switch to the ItemListView you already have
        view = ItemListView(
            self.config,
            self.guild_id,
            self.user_id,
            self.mode,
            shop_name,
        )
        await view.populate_items()

        await interaction.response.edit_message(
            content=f"**{shop_name}** – Select an item to {self.mode}:",
            view=view,
        )

class RemoveStockView(View):
    def __init__(self, config: Config, guild_id: int):
        super().__init__(timeout=60)
        self.config = config
        self.guild_id = guild_id
        
    async def on_timeout(self):
        # disable all buttons & selects
        for child in self.children:
            child.disabled = True
        # edit the original message so users know it expired
        try:
            await self.message.edit(
                content="⌛ Removal session timed out.", view=self
            )
        except Exception:
            pass        

    async def populate(self):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        options = [discord.SelectOption(label=n, value=n) for n in shops]
        if options:
            self.add_item(RemoveStockSelect(options, self.config, self.guild_id))
        cancel = Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel.callback = self._cancel
        self.add_item(cancel)

    async def _cancel(self, interaction: discord.Interaction):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="Cancelled.", view=self)


class RemoveStockSelect(Select):
    def __init__(self, options, config: Config, guild_id: int):
        super().__init__(
            placeholder="Choose a shop…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="remove_stock_shop_select",
        )
        self.config = config
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        shop_name = self.values[0]

        # 1. Instantiate and populate the item‐removal view
        view = RemoveItemView(self.config, self.guild_id, shop_name)
        await view.populate()

        # 2. Swap in the fully‐built view
        await interaction.response.edit_message(
            content=f"🗑️ **{shop_name}** – select an item to remove:",
            view=view,
        )


class RemoveItemView(View):
    def __init__(self, config: Config, guild_id: int, shop_name: str):
        super().__init__(timeout=60)
        self.config = config
        self.guild_id = guild_id
        self.shop_name = shop_name

    async def populate(self):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        stock = shops[self.shop_name]["stock"]
        options = [
            discord.SelectOption(label=item, value=item)
            for item in stock.keys()
        ]
        if options:
            self.add_item(
                RemoveItemSelect(options, self.config, self.guild_id, self.shop_name)
            )
        cancel = Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel.callback = self._cancel
        self.add_item(cancel)

    async def _cancel(self, interaction: discord.Interaction):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="Cancelled.", view=self)


class RemoveItemSelect(Select):
    def __init__(
        self, options, config: Config, guild_id: int, shop_name: str
    ):
        super().__init__(
            placeholder="Choose an item…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="remove_stock_item_select",
        )
        self.config = config
        self.guild_id = guild_id
        self.shop_name = shop_name

    async def callback(self, interaction: discord.Interaction):
        item_name = self.values[0]
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        stock = shops[self.shop_name]["stock"]

        if item_name in stock:
            stock.pop(item_name)
            shops[self.shop_name]["stock"] = stock
            await guild_conf.shops.set(shops)
            await interaction.response.send_message(
                f"✅ Removed `{item_name}` from **{self.shop_name}**.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"❌ Item `{item_name}` not found.", ephemeral=True
            )

        # disable buttons/select after action
        for c in self.view.children:
            c.disabled = True
        await interaction.message.edit(view=self.view)
        
class ShopEmbedView(View):
    """First dropdown: pick which shop to browse (buy vs gift)."""
    def __init__(self, config: Config, guild_id: int, user_id: int, mode: str = "buy"):
        super().__init__(timeout=60)
        self.config = config
        self.guild_id = guild_id
        self.user_id = user_id
        self.mode = mode
        
    async def on_timeout(self):
        # disable all buttons/selects
        for child in self.children:
            child.disabled = True
        # edit original message to indicate timeout
        try:
            await self.message.edit(content="⌛ Interaction timed out.", view=self)
        except Exception:
            pass        

    async def populate_shops(self, shops: Dict[str, dict]):
        options = [
            discord.SelectOption(label=name, value=name)
            for name in shops.keys()
        ]
        self.add_item(
            ShopEmbedSelect(
                options, self.config, self.guild_id, self.user_id, self.mode
            )
        )
        cancel = Button(label="Cancel", style=discord.ButtonStyle.danger)
        async def _cancel(inter: discord.Interaction):
            for c in self.children:
                c.disabled = True
            await inter.response.edit_message(content="Cancelled.", view=self)
        cancel.callback = _cancel
        self.add_item(cancel)

class ShopEmbedSelect(Select):
    """Dropdown of shops → edits to shop embed + item selector."""
    def __init__(
        self,
        options,
        config: Config,
        guild_id: int,
        user_id: int,
        mode: str = "buy",
    ):
        super().__init__(
            placeholder="Choose a shop…",
            min_values=1, max_values=1,
            options=options,
            custom_id="shop_embed_select"
        )
        self.config = config
        self.guild_id = guild_id
        self.user_id = user_id
        self.mode = mode

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This menu isn’t for you.", ephemeral=True)

        shop_name = self.values[0]
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops_data = await guild_conf.shops()
        shop = shops_data[shop_name]
        currency = await bank.get_currency_name(interaction.guild)

        # build shop embed w/ header info
        embed = discord.Embed(
            title=f"💰 {shop_name}",
            description=shop.get("description", "") or "No description.",
            color=discord.Color.random()
        )
        thumb = shop.get("thumbnail", "").strip()
        if thumb:
            embed.set_thumbnail(url=thumb)

        # ── Use one field per item ──
        stock = shop.get("stock", {})
        for item_name, entry in stock.items():
            price = entry.get("price", 0)
            amt = entry.get("amount")
            left = "∞" if amt is None else str(amt)
            desc = entry.get("description", "No description.")
            embed.add_field(
                name=f"🔶 {item_name} — {price} {currency}",
                value=f"{desc}\n🗃️ Stock: {left}",
                inline=False
            )

        # swap in Item dropdown view
        view = ItemEmbedView(
            self.config,
            self.guild_id,
            self.user_id,
            shop_name,
            currency,
            self.mode,
        )
        await view.populate_items()
        await interaction.response.edit_message(embed=embed, view=view)

class ItemEmbedView(View):
    """After shop select: dropdown of items → opens BuyModal."""
    def __init__(
        self,
        config: Config,
        guild_id: int,
        user_id: int,
        shop_name: str,
        currency: str,
        mode: str = "buy",
    ):
        super().__init__(timeout=60)
        self.config = config
        self.guild_id = guild_id
        self.user_id = user_id
        self.shop_name = shop_name
        self.currency = currency
        self.mode = mode
        
    async def on_timeout(self):
        # disable all buttons/selects
        for child in self.children:
            child.disabled = True
        # edit original message to indicate timeout
        try:
            await self.message.edit(view=self)
        except Exception:
            pass        

    async def populate_items(self):
        guild_conf = self.config.guild_from_id(self.guild_id)
        stock = (await guild_conf.shops())[self.shop_name]["stock"]
        options = []
        for item_name, entry in stock.items():
            amt = "∞" if entry.get("amount") is None else entry["amount"]
            label = f"{item_name} ({entry['price']} {self.currency}, {amt} left)"
            options.append(discord.SelectOption(label=label, value=item_name))
        self.add_item(
            ItemEmbedSelect(
                options,
                self.config,
                self.guild_id,
                self.user_id,
                self.shop_name,
                self.currency,
                self.mode,
            )
        )

        cancel = Button(label="Cancel", style=discord.ButtonStyle.danger)
        async def _cancel(inter: discord.Interaction):
            for c in self.children:
                c.disabled = True
            await inter.response.edit_message(content="Cancelled.", view=self)
        cancel.callback = _cancel
        self.add_item(cancel)

class ItemEmbedSelect(Select):
    """Dropdown of items → send Buy or Gift modal."""
    def __init__(
        self,
        options,
        config: Config,
        guild_id: int,
        user_id: int,
        shop_name: str,
        currency: str,
        mode: str = "buy",
    ):
        super().__init__(
            placeholder="Select an item to buy…",
            min_values=1, max_values=1,
            options=options,
            custom_id="item_embed_select"
        )
        self.config = config
        self.guild_id = guild_id
        self.user_id = user_id
        self.shop_name = shop_name
        self.currency = currency
        self.mode = mode        

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This menu isn’t for you.", ephemeral=True)

        item_name = self.values[0]
        # pull price from config
        guild_conf = self.config.guild_from_id(self.guild_id)
        entry = (await guild_conf.shops())[self.shop_name]["stock"][item_name]
        price = entry["price"]

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
        