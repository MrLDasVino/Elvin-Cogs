import asyncio
import discord
import datetime
from typing import Dict, Optional

from redbot.core import commands, Config, checks, bank
from discord.ui import View, button, Button, Modal, TextInput, Select

from .dashboard import DashboardIntegration

ITEMS_PER_PAGE = 10
ROLES_PER_PAGE = 25


async def _grant_owned_role(config: Config, user: discord.abc.User, guild_id: int, role_id: int, item_name: str):
    user_conf = config.user(user)
    owned = await user_conf.owned_roles()
    gid = str(guild_id)
    guild_roles = owned.get(gid, {})
    guild_roles[str(role_id)] = {"name": item_name, "equipped": True}
    owned[gid] = guild_roles
    await user_conf.owned_roles.set(owned)


async def _get_role_item_names(config: Config, guild: discord.Guild):
    guild_conf = config.guild(guild)
    shops = await guild_conf.shops()
    names = set()
    for shop_data in shops.values():
        stock = shop_data.get("stock", {})
        for item_name, entry in stock.items():
            if entry.get("role_id"):
                names.add(item_name)
    return names


async def _get_valid_owned_roles(config: Config, guild: discord.Guild, user_id: int):
    user_conf = config.user_from_id(user_id)
    owned = await user_conf.owned_roles()
    gid = str(guild.id)
    guild_roles = owned.get(gid, {})
    valid = {}
    pruned = False
    for role_id_str, data in guild_roles.items():
        role = guild.get_role(int(role_id_str))
        if role:
            valid[role_id_str] = data
        else:
            pruned = True
    if pruned:
        if valid:
            owned[gid] = valid
        else:
            owned.pop(gid, None)
        await user_conf.owned_roles.set(owned)
    result = []
    for role_id_str, data in valid.items():
        role = guild.get_role(int(role_id_str))
        result.append((role, data.get("equipped", False), data.get("name", role.name)))
    result.sort(key=lambda x: x[0].name.lower())
    return result


class Shop(DashboardIntegration, commands.Cog):
    """A shop cog with buttons, modals, and Red’s bank integration."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210)
        default_guild = {
            "shops": {},
            "log_channel": None,  # channel ID to post shop logs in (or None)
        }  # shop_name → {description, stock: {item: {price, amount, role_id?}}}
        default_user = {"inventory": {}, "owned_roles": {}}  # item_name → count / guild_id → role_id → {name, equipped}
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
        view = ManageView(self.config, ctx.guild.id, timeout=60)
        await view._populate()
        msg = await ctx.send("Click below to create or edit your shop:", view=view)
        view.message = msg
        
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
        embed = discord.Embed(
            title="⚠️ Remove Stock",
            description="Select a shop to remove an item from (THIS CANNOT BE UNDONE).",
            color=discord.Color.red()
        )
        view = RemoveStockView(self.config, ctx.guild.id)
        await view.populate()
        msg = await ctx.send(embed=embed, view=view)
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
        
    @shop.command(name="delete")
    @checks.admin()
    async def delete(self, ctx):
        """Delete a shop via dropdown selection."""
        guild_conf = self.config.guild(ctx.guild)
        shops = await guild_conf.shops()
        if not shops:
            return await ctx.send("❌ There are no shops to delete.")

        embed = discord.Embed(
            title="⚠️ Delete Shop",
            description="Select a shop to delete (THIS CANNOT BE UNDONE).",
            color=discord.Color.red()
        )
        view = DeleteShopView(self.config, ctx.guild.id, timeout=60)
        await view.populate()
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg 

    # --------------------
    # Logging configuration
    # --------------------

    @shop.group(name="log", invoke_without_command=True)
    @checks.admin()
    async def shop_log(self, ctx):
        """Manage shop logging channel."""
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @shop_log.command(name="set")
    @checks.admin()
    async def shop_log_set(self, ctx, channel: discord.TextChannel):
        """Set a channel to receive shop purchase/gift logs."""
        guild_conf = self.config.guild(ctx.guild)
        await guild_conf.log_channel.set(channel.id)
        await ctx.send(f"✅ Shop logs will be posted in {channel.mention}.")

    @shop_log.command(name="clear")
    @checks.admin()
    async def shop_log_clear(self, ctx):
        """Clear the shop log channel."""
        guild_conf = self.config.guild(ctx.guild)
        await guild_conf.log_channel.set(None)
        await ctx.send("✅ Shop logging cleared.")

    async def _send_shop_log(self, guild_id: int, embed: discord.Embed):
        """Send a log embed to the configured channel for guild_id if set."""
        guild_conf = self.config.guild_from_id(guild_id)
        ch_id = await guild_conf.log_channel()
        if not ch_id:
            return
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        channel = guild.get_channel(ch_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return
        try:
            await channel.send(embed=embed)
        except Exception:
            pass        

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
        view = ShopEmbedView(self.config, ctx.guild.id, ctx.author.id, cog=self)
        await view.populate_shops(shops)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

    @shop.command()
    async def gift(self, ctx):
        """Gift an item to another user."""
        guild_conf = self.config.guild(ctx.guild)
        raw = await guild_conf.shops()
        shops = {name: data for name, data in raw.items()
                 if data.get("giftable", True)}
        if not shops:
            return await ctx.send("❌ There are no giftable shops available.")

        embed = discord.Embed(
            title="🎁 Gift Items",
            description="Select a shop from the dropdown below:",
            color=discord.Color.random()
        )
        view = ShopEmbedView(self.config, ctx.guild.id, ctx.author.id, mode="gift", cog=self)
        await view.populate_shops(shops)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        
    @shop.command(name="inventory")
    async def inventory(self, ctx, member: discord.Member = None):
        """Show the items and equippable roles you or another member have bought."""
        target = member or ctx.author
        view = InventoryView(self.config, ctx.guild, target, ctx.author.id)
        embed = await view.build()
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

    @shop.command(name="equip")
    async def equip(self, ctx):
        """Equip or unequip roles you've bought from the shop."""
        roles = await _get_valid_owned_roles(self.config, ctx.guild, ctx.author.id)
        if not roles:
            return await ctx.send("❌ You don't own any equippable roles.")

        view = EquipRolesView(self.config, ctx.guild, ctx.author.id)
        await view.populate()
        msg = await ctx.send(
            "Select roles to equip or unequip below. Selecting an equipped role again unequips it.",
            view=view,
        )
        view.message = msg        
     
        
# --------------------
# INVENTORY / EQUIP VIEWS
# --------------------
class InventoryView(View):
    """Two-tab inventory embed (Items / Roles), each independently paginated, navigated with arrow buttons."""

    def __init__(
        self,
        config: Config,
        guild: discord.Guild,
        target: discord.Member,
        viewer_id: int,
        *,
        tab: str = "items",
        item_page: int = 0,
        role_page: int = 0,
        timeout: float = 60,
    ):
        super().__init__(timeout=timeout)
        self.config = config
        self.guild = guild
        self.target = target
        self.viewer_id = viewer_id
        self.tab = tab
        self.item_page = item_page
        self.role_page = role_page
        self.message: discord.Message | None = None

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    async def build(self):
        embed = discord.Embed(color=discord.Color.random())
        if self.target.avatar:
            embed.set_author(name=self.target.display_name, icon_url=self.target.avatar.url)
        else:
            embed.set_author(name=self.target.display_name)

        role_item_names = await _get_role_item_names(self.config, self.guild)

        if self.tab == "items":
            embed.title = f"{self.target.display_name}'s Inventory — Items"
            user_conf = self.config.user(self.target)
            inv = await user_conf.inventory()
            filtered = [
                (item_name, count) for item_name, count in inv.items()
                if item_name not in role_item_names
            ]
            total_pages = max(1, (len(filtered) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
            self.item_page = max(0, min(self.item_page, total_pages - 1))
            start = self.item_page * ITEMS_PER_PAGE
            page_entries = filtered[start:start + ITEMS_PER_PAGE]

            if not filtered:
                embed.description = "No items owned."
            else:
                for item_name, count in page_entries:
                    embed.add_field(
                        name=f"🔸 {item_name}",
                        value=f"Quantity: {count}",
                        inline=False,
                    )
                if total_pages > 1:
                    embed.set_footer(text=f"Page {self.item_page + 1}/{total_pages}")
        else:
            embed.title = f"{self.target.display_name}'s Inventory — Roles"
            roles = await _get_valid_owned_roles(self.config, self.guild, self.target.id)
            total_pages = max(1, (len(roles) + ROLES_PER_PAGE - 1) // ROLES_PER_PAGE)
            self.role_page = max(0, min(self.role_page, total_pages - 1))
            start = self.role_page * ROLES_PER_PAGE
            page_entries = roles[start:start + ROLES_PER_PAGE]

            if not roles:
                embed.description = "No roles owned."
            else:
                for role, equipped, name in page_entries:
                    status = "✅ Equipped" if equipped else "⬜ Not equipped"
                    embed.add_field(name=f"🔹 {role.name}", value=status, inline=False)
                if total_pages > 1:
                    embed.set_footer(text=f"Page {self.role_page + 1}/{total_pages}")

        self.clear_items()

        if self.tab == "items":
            prev_tab_btn = Button(label="◀", style=discord.ButtonStyle.secondary, disabled=True, row=0)
            next_tab_btn = Button(label="Roles ▶", style=discord.ButtonStyle.secondary, row=0)
        else:
            prev_tab_btn = Button(label="◀ Items", style=discord.ButtonStyle.secondary, row=0)
            next_tab_btn = Button(label="▶", style=discord.ButtonStyle.secondary, disabled=True, row=0)

        async def _to_items(inter: discord.Interaction):
            if inter.user.id != self.viewer_id:
                return await inter.response.send_message("Not your menu.", ephemeral=True)
            self.tab = "items"
            new_embed = await self.build()
            await inter.response.edit_message(embed=new_embed, view=self)

        async def _to_roles(inter: discord.Interaction):
            if inter.user.id != self.viewer_id:
                return await inter.response.send_message("Not your menu.", ephemeral=True)
            self.tab = "roles"
            new_embed = await self.build()
            await inter.response.edit_message(embed=new_embed, view=self)

        prev_tab_btn.callback = _to_items
        next_tab_btn.callback = _to_roles
        self.add_item(prev_tab_btn)
        self.add_item(next_tab_btn)

        if total_pages > 1:
            cur_page = self.item_page if self.tab == "items" else self.role_page
            prev_page_btn = Button(
                label="◀ Page", style=discord.ButtonStyle.primary, disabled=cur_page == 0, row=1
            )
            next_page_btn = Button(
                label="Page ▶",
                style=discord.ButtonStyle.primary,
                disabled=cur_page >= total_pages - 1,
                row=1,
            )

            async def _prev_page(inter: discord.Interaction):
                if inter.user.id != self.viewer_id:
                    return await inter.response.send_message("Not your menu.", ephemeral=True)
                if self.tab == "items":
                    self.item_page -= 1
                else:
                    self.role_page -= 1
                new_embed = await self.build()
                await inter.response.edit_message(embed=new_embed, view=self)

            async def _next_page(inter: discord.Interaction):
                if inter.user.id != self.viewer_id:
                    return await inter.response.send_message("Not your menu.", ephemeral=True)
                if self.tab == "items":
                    self.item_page += 1
                else:
                    self.role_page += 1
                new_embed = await self.build()
                await inter.response.edit_message(embed=new_embed, view=self)

            prev_page_btn.callback = _prev_page
            next_page_btn.callback = _next_page
            self.add_item(prev_page_btn)
            self.add_item(next_page_btn)

        return embed


class EquipRolesView(View):
    """Paginated multi-select for equipping/unequipping owned roles."""

    def __init__(
        self,
        config: Config,
        guild: discord.Guild,
        user_id: int,
        *,
        page: int = 0,
        timeout: float = 60,
    ):
        super().__init__(timeout=timeout)
        self.config = config
        self.guild = guild
        self.user_id = user_id
        self.page = page
        self.message: discord.Message | None = None

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(content="⌛ Equip session expired.", view=self)
            except Exception:
                pass

    async def populate(self):
        roles = await _get_valid_owned_roles(self.config, self.guild, self.user_id)
        total_pages = max(1, (len(roles) + ROLES_PER_PAGE - 1) // ROLES_PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * ROLES_PER_PAGE
        page_roles = roles[start:start + ROLES_PER_PAGE]

        if not page_roles:
            self.add_item(
                Button(label="No roles owned", style=discord.ButtonStyle.secondary, disabled=True)
            )
        else:
            options = [
                discord.SelectOption(label=role.name[:100], value=str(role.id), default=equipped)
                for role, equipped, name in page_roles
            ]
            self.add_item(EquipRolesSelect(options, self.config, self.guild, self.user_id))

        if len(roles) > ROLES_PER_PAGE:
            prev_btn = Button(label="◀", style=discord.ButtonStyle.secondary, disabled=self.page == 0)

            async def _prev(inter: discord.Interaction):
                if inter.user.id != self.user_id:
                    return await inter.response.send_message("Not your menu.", ephemeral=True)
                new_view = EquipRolesView(self.config, self.guild, self.user_id, page=self.page - 1)
                await new_view.populate()
                new_view.message = self.message
                await inter.response.edit_message(view=new_view)

            prev_btn.callback = _prev
            self.add_item(prev_btn)

            next_btn = Button(
                label="▶", style=discord.ButtonStyle.secondary, disabled=self.page >= total_pages - 1
            )

            async def _next(inter: discord.Interaction):
                if inter.user.id != self.user_id:
                    return await inter.response.send_message("Not your menu.", ephemeral=True)
                new_view = EquipRolesView(self.config, self.guild, self.user_id, page=self.page + 1)
                await new_view.populate()
                new_view.message = self.message
                await inter.response.edit_message(view=new_view)

            next_btn.callback = _next
            self.add_item(next_btn)

        done = Button(label="Done", style=discord.ButtonStyle.success)

        async def _done(inter: discord.Interaction):
            if inter.user.id != self.user_id:
                return await inter.response.send_message("Not your menu.", ephemeral=True)
            for c in self.children:
                c.disabled = True
            await inter.response.edit_message(view=self)

        done.callback = _done
        self.add_item(done)


class EquipRolesSelect(Select):
    def __init__(self, options, config: Config, guild: discord.Guild, user_id: int):
        super().__init__(
            placeholder="Select roles to equip/unequip…",
            min_values=0,
            max_values=len(options),
            options=options,
            custom_id="equip_roles_select",
        )
        self.config = config
        self.guild = guild
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This menu isn’t for you.", ephemeral=True)

        selected_ids = set(self.values)
        page_ids = {opt.value for opt in self.options}

        user_conf = self.config.user_from_id(self.user_id)
        owned = await user_conf.owned_roles()
        gid = str(self.guild.id)
        guild_roles = owned.get(gid, {})

        to_add = []
        to_remove = []
        for role_id_str in page_ids:
            data = guild_roles.get(role_id_str)
            if not data:
                continue
            role = self.guild.get_role(int(role_id_str))
            if not role:
                continue
            now_equipped = role_id_str in selected_ids
            was_equipped = data.get("equipped", False)
            if now_equipped and not was_equipped:
                to_add.append(role)
            elif was_equipped and not now_equipped:
                to_remove.append(role)
            data["equipped"] = now_equipped
            guild_roles[role_id_str] = data

        owned[gid] = guild_roles
        await user_conf.owned_roles.set(owned)

        try:
            if to_add:
                await interaction.user.add_roles(*to_add, reason="Shop role equip")
            if to_remove:
                await interaction.user.remove_roles(*to_remove, reason="Shop role unequip")
        except discord.Forbidden:
            return await interaction.response.send_message(
                "❌ I don't have permission to manage one or more of those roles.", ephemeral=True
            )

        for opt in self.options:
            opt.default = opt.value in selected_ids

        summary_parts = []
        if to_add:
            summary_parts.append("Equipped: " + ", ".join(r.mention for r in to_add))
        if to_remove:
            summary_parts.append("Unequipped: " + ", ".join(r.mention for r in to_remove))
        content = "\n".join(summary_parts) if summary_parts else "No changes."

        await interaction.response.edit_message(content=content, view=self.view)


# --------------------
# BUTTON‐LAUNCH VIEW
# --------------------
class ManageView(View):
    """Dropdown to pick a shop to edit, or click to create a new one."""

    def __init__(self, config: Config, guild_id: int, *, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.config = config
        self.guild_id = guild_id
        self.message: discord.Message | None = None

    async def _populate(self):
        """Fill in the Select + New‐Shop button synchronously."""
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        options = [discord.SelectOption(label=n, value=n) for n in shops]
        if options:
            self.add_item(ShopSelect(options, self.config, self.guild_id))
        self.add_item(NewShopButton(self.config, self.guild_id))
        
    async def on_timeout(self):
        # disable every component
        for child in self.children:
            child.disabled = True
        # update the original message to indicate expiration
        if self.message:
            try:
                await self.message.edit(
                    content="⌛ Manage session expired.",
                    view=self
                )
            except Exception:
                pass        


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
                giftable=data.get("giftable", True),
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
    giftable = TextInput(
        label="Giftable? (yes/no)",
        style=discord.TextStyle.short,
        required=True,
        placeholder="yes",
    )    

    def __init__(
        self,
        config: Config,
        guild_id: int,
        *,
        original_name: str = None,
        description: str = "",
        thumbnail: str = "",
        giftable: bool = True,
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
            self.giftable.default = "yes" if giftable else "no"            

    async def on_submit(self, interaction: discord.Interaction):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()

        new_name = self.shop_name.value.strip()
        desc = self.description.value.strip()
        thumb = self.thumbnail.value.strip()
        raw_gift = self.giftable.value.strip().lower()
        is_giftable = raw_gift in ("yes","y","true","1")        

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
            "giftable": is_giftable,
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
        placeholder="leave blank for item or supply role ID to preserve exact role",
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
        label="Amount to set (blank = ∞)",
        required=False,
    )

    def __init__(
        self,
        config: Config,
        guild_id: int,
        shop_name: str,
        *,
        existing_item_name: str | None = None,
        existing_entry: dict | None = None,
    ):
        super().__init__()
        self.config = config
        self.guild_id = guild_id
        self.shop_name = shop_name

        # Prefill when editing an existing entry
        if existing_item_name:
            self.item.default = existing_item_name
        if existing_entry:
            if existing_entry.get("role_id"):
                # prefer role ID so parsing is unambiguous
                self.role.default = str(existing_entry["role_id"])
            desc = existing_entry.get("description", "")
            if desc:
                self.description.default = desc
            if "price" in existing_entry:
                self.price.default = str(existing_entry["price"])
            # amount: None == infinite => leave blank; else show current amount
            if "amount" in existing_entry and existing_entry["amount"] is not None:
                self.amount.default = str(existing_entry["amount"])

    async def on_submit(self, interaction: discord.Interaction):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        stock = shops[self.shop_name].get("stock", {})

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

        role_id = None
        if raw_role:
            role_obj = None
            # 1) Mention syntax
            if raw_role.startswith("<@&") and raw_role.endswith(">"):
                try:
                    rid = int(raw_role[3:-1])
                    role_obj = interaction.guild.get_role(rid)
                except Exception:
                    role_obj = None
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

        # Price always required
        try:
            price = int(self.price.value)
        except Exception:
            return await interaction.response.send_message(
                "❌ Price must be an integer.", ephemeral=True
            )

        # Amount: blank = infinite, else set absolute amount
        raw_amt = (self.amount.value or "").strip()
        if raw_amt == "":
            final_amount = None
        else:
            try:
                final_amount = int(raw_amt)
            except Exception:
                return await interaction.response.send_message(
                    "❌ Amount must be an integer or blank for infinite.", ephemeral=True
                )

        raw_desc = (self.description.value or "").strip()
        old_entry = stock.get(name, {})
        final_desc = raw_desc or old_entry.get("description", "")

        # Write stock entry (overwrite existing)
        entry = {"price": price, "amount": final_amount, "description": final_desc}
        if role_id:
            entry["role_id"] = role_id
        stock[name] = entry

        shops[self.shop_name]["stock"] = stock
        await guild_conf.shops.set(shops)
        await interaction.response.send_message(
            f"✅ Saved `{name}` for {price} credits"
            f"{'' if final_amount is None else f', amount={final_amount}'}.",
            ephemeral=True,
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
        *,
        cog: Optional["Shop"] = None,        
    ):
        super().__init__()
        self.config = config
        self.guild_id = guild_id
        self.gifting_user = gifting_user
        self.shop_name = shop_name
        self.item_name = item_name
        self.price = price
        self.cog = cog

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
                await _grant_owned_role(self.config, member, self.guild_id, role.id, self.item_name)

        # Decrement shop stock
        if entry.get("amount") is not None:
            entry["amount"] -= amount
        shops[self.shop_name]["stock"][self.item_name] = entry
        await self.config.guild_from_id(self.guild_id).shops.set(shops)

        # Public notification so the recipient and channel know about the gift
        try:
            channel = interaction.channel
            # Prefer an embed for nicer formatting
            embed = discord.Embed(
                title="🎁 Gift Received",
                description=f"{member.mention} received **{amount}× {self.item_name}** from {interaction.user.mention}.",
                color=discord.Color.green()
            )
            # include shop and optional item description if available
            if entry.get("description"):
                embed.add_field(name="Item details", value=entry["description"], inline=False)
            embed.set_footer(text=f"From shop: {self.shop_name}")
            await channel.send(embed=embed)
        except Exception:
            # If public post fails (permissions, missing channel), ignore and continue
            pass

        # Ephemeral confirmation to gifter
        try:
            if self.cog:
                log_embed = discord.Embed(
                    title="🎁 Gift",
                    description=f"{interaction.user.mention} gifted **{amount}× {self.item_name}** to {member.mention}",
                    color=discord.Color.purple(),
                )
                log_embed.add_field(name="Gifter", value=f"{interaction.user} ({interaction.user.id})", inline=False)
                log_embed.add_field(name="Recipient", value=f"{member} ({member.id})", inline=False)
                log_embed.add_field(name="Shop", value=self.shop_name, inline=True)
                log_embed.add_field(name="Item", value=self.item_name, inline=True)
                log_embed.add_field(name="Quantity", value=str(amount), inline=True)
                log_embed.add_field(name="Total cost", value=str(total_cost), inline=True)
                entry = (await self.config.guild_from_id(self.guild_id).shops())[self.shop_name]["stock"].get(self.item_name, {})
                if entry.get("role_id"):
                    role = interaction.guild.get_role(entry["role_id"])
                    role_text = f"{role} ({entry['role_id']})" if role else str(entry["role_id"])
                    log_embed.add_field(name="Role granted", value=role_text, inline=False)
                if entry.get("amount") is not None:
                    log_embed.add_field(name="Remaining stock", value=str(entry["amount"]), inline=True)
                log_embed.set_footer(text=f"Guild ID: {interaction.guild.id}")
                log_embed.timestamp = datetime.datetime.utcnow()
                await self.cog._send_shop_log(self.guild_id, log_embed)
        except Exception:
            pass

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
                    self.config, self.guild_id, self.user_id, self.mode, shop_name, cog=self.cog
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
        *,
        cog: Optional["Shop"] = None,        
    ):
        super().__init__(timeout=60)
        self.config = config
        self.guild_id = guild_id
        self.user_id = user_id
        self.mode = mode
        self.shop_name = shop_name
        self.cog = cog


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
                        cog=self.cog,
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
                        cog=self.cog,
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
        *,
        cog: Optional["Shop"] = None,        
    ):
        super().__init__()
        self.config = config
        self.guild_id = guild_id
        self.buyer_id = buyer_id
        self.shop_name = shop_name
        self.item_name = item_name
        self.price = price
        self.cog = cog

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
                await _grant_owned_role(self.config, interaction.user, self.guild_id, role.id, self.item_name)

        # Decrement shop stock
        if entry.get("amount") is not None:
            entry["amount"] -= qty
        shops[self.shop_name]["stock"][self.item_name] = entry
        await guild_conf.shops.set(shops)

        # Build log embed and send to configured channel if possible
        try:
            if self.cog:
                log_embed = discord.Embed(
                    title="🛒 Purchase",
                    description=f"{interaction.user.mention} bought **{qty}× {self.item_name}**",
                    color=discord.Color.blue(),
                )
                log_embed.add_field(name="Buyer", value=f"{interaction.user} ({interaction.user.id})", inline=False)
                log_embed.add_field(name="Shop", value=self.shop_name, inline=True)
                log_embed.add_field(name="Item", value=self.item_name, inline=True)
                log_embed.add_field(name="Quantity", value=str(qty), inline=True)
                log_embed.add_field(name="Total cost", value=str(total_cost), inline=True)
                if entry.get("role_id"):
                    role = interaction.guild.get_role(entry["role_id"])
                    role_text = f"{role} ({entry['role_id']})" if role else str(entry["role_id"])
                    log_embed.add_field(name="Role granted", value=role_text, inline=False)
                if entry.get("amount") is not None:
                    log_embed.add_field(name="Remaining stock", value=str(entry["amount"]), inline=True)
                log_embed.set_footer(text=f"Guild ID: {interaction.guild.id}")
                log_embed.timestamp = datetime.datetime.utcnow()
                await self.cog._send_shop_log(self.guild_id, log_embed)
        except Exception:
            pass

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
        # present a second dropdown: choose existing item to edit or add new
        view = AddStockChooseItemView(self.config, self.guild_id, shop_name)
        await view.populate()
        # attach message reference so view can edit on timeout
        view.message = interaction.message
        await interaction.response.edit_message(
            content=f"Restocking **{shop_name}** — choose an item to edit or Add new:",
            view=view,
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
    def __init__(self, config: Config, guild_id: int, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.config = config
        self.guild_id = guild_id
        self.message: discord.Message | None = None
        
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

        embed = discord.Embed(
            title="⚠️ Delete Item",
            description=f"**{shop_name}** – select an item to remove (THIS CANNOT BE UNDONE)",
            color=discord.Color.red()
        )
        view = RemoveItemView(self.config, self.guild_id, shop_name, timeout=60)
        await view.populate()
        await interaction.response.edit_message(embed=embed, view=view)


class RemoveItemView(View):
    def __init__(self, config: Config, guild_id: int, shop_name: str, *, page: int = 0, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.config = config
        self.guild_id = guild_id
        self.shop_name = shop_name
        self.page = page

    async def populate(self):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        stock = shops[self.shop_name]["stock"]

        items = list(stock.keys())
        total_pages = max(1, (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * ITEMS_PER_PAGE
        page_items = items[start:start + ITEMS_PER_PAGE]

        options = [
            discord.SelectOption(label=item, value=item)
            for item in page_items
        ]
        if options:
            self.add_item(
                RemoveItemSelect(options, self.config, self.guild_id, self.shop_name)
            )

        if len(items) > ITEMS_PER_PAGE:
            prev_btn = Button(label="◀", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
            async def _prev(inter: discord.Interaction):
                new_view = RemoveItemView(self.config, self.guild_id, self.shop_name, page=self.page - 1)
                await new_view.populate()
                await inter.response.edit_message(view=new_view)
            prev_btn.callback = _prev
            self.add_item(prev_btn)

            next_btn = Button(label="▶", style=discord.ButtonStyle.secondary, disabled=self.page >= total_pages - 1)
            async def _next(inter: discord.Interaction):
                new_view = RemoveItemView(self.config, self.guild_id, self.shop_name, page=self.page + 1)
                await new_view.populate()
                await inter.response.edit_message(view=new_view)
            next_btn.callback = _next
            self.add_item(next_btn)

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
        # open confirmation modal instead of immediate delete
        await interaction.response.send_modal(
            DeleteItemConfirmationModal(
                self.config,
                self.guild_id,
                self.shop_name,
                self.values[0],
                interaction.message,
                self.view
            )
        )

class DeleteItemConfirmationModal(Modal, title="Confirm Item Deletion"):
    confirmation = TextInput(
        label="Type DELETE to confirm",
        placeholder="DELETE",
        style=discord.TextStyle.short,
        required=True
    )

    def __init__(
        self,
        config: Config,
        guild_id: int,
        shop_name: str,
        item_name: str,
        original_msg: discord.Message,
        parent_view: View
    ):
        super().__init__()
        self.config = config
        self.guild_id = guild_id
        self.shop_name = shop_name
        self.item_name = item_name
        self.original_msg = original_msg
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        # require exact DELETE
        if self.confirmation.value.strip().upper() != "DELETE":
            return await interaction.response.send_message(
                "❌ Deletion cancelled. You did not type DELETE.", ephemeral=True
            )

        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        stock = shops[self.shop_name]["stock"]
        # perform removal
        stock.pop(self.item_name, None)
        shops[self.shop_name]["stock"] = stock
        await guild_conf.shops.set(shops)

        # acknowledgment
        await interaction.response.send_message(
            f"✅ Removed `{self.item_name}` from **{self.shop_name}**.", ephemeral=True
        )

        # disable original view components
        for c in self.parent_view.children:
            c.disabled = True
        try:
            await self.original_msg.edit(view=self.parent_view)
        except Exception:
            pass
        
class ShopEmbedView(View):
    """First dropdown: pick which shop to browse (buy vs gift)."""
    def __init__(self, config: Config, guild_id: int, user_id: int, mode: str = "buy", *, cog: Optional["Shop"] = None):
        super().__init__(timeout=60)
        self.config = config
        self.guild_id = guild_id
        self.user_id = user_id
        self.mode = mode
        self.cog = cog
        
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
                options, self.config, self.guild_id, self.user_id, self.mode, cog=self.cog
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
        *,
        cog: Optional["Shop"] = None,        
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
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This menu isn’t for you.", ephemeral=True)

        shop_name = self.values[0]
        currency = await bank.get_currency_name(interaction.guild)

        view = ItemEmbedView(
            self.config,
            self.guild_id,
            self.user_id,
            shop_name,
            currency,
            self.mode,
            cog=self.cog,
        )
        embed = await view.build_embed()
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
        *,
        page: int = 0,
        cog: Optional["Shop"] = None,        
    ):
        super().__init__(timeout=60)
        self.config = config
        self.guild_id = guild_id
        self.user_id = user_id
        self.shop_name = shop_name
        self.currency = currency
        self.mode = mode
        self.page = page
        self.cog = cog
        
    async def on_timeout(self):
        # disable all buttons/selects
        for child in self.children:
            child.disabled = True
        # edit original message to indicate timeout
        try:
            await self.message.edit(view=self)
        except Exception:
            pass        

    async def _get_stock(self):
        guild_conf = self.config.guild_from_id(self.guild_id)
        return (await guild_conf.shops())[self.shop_name]["stock"]

    def _paginate(self, stock: dict):
        items = list(stock.items())
        total_pages = max(1, (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * ITEMS_PER_PAGE
        return items[start:start + ITEMS_PER_PAGE], len(items), total_pages

    async def build_embed(self):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shop = (await guild_conf.shops())[self.shop_name]
        stock = shop.get("stock", {})
        page_items, total_items, total_pages = self._paginate(stock)

        embed = discord.Embed(
            title=f"💰 {self.shop_name}",
            description=shop.get("description", "") or "No description.",
            color=discord.Color.random()
        )
        thumb = shop.get("thumbnail", "").strip()
        if thumb:
            embed.set_thumbnail(url=thumb)

        for item_name, entry in page_items:
            price = entry.get("price", 0)
            amt = entry.get("amount")
            left = "∞" if amt is None else str(amt)
            desc = entry.get("description", "No description.")
            embed.add_field(
                name=f"🔶 {item_name} — {price} {self.currency}",
                value=f"{desc}\n🗃️ Stock: {left}",
                inline=False
            )

        if total_items > ITEMS_PER_PAGE:
            embed.set_footer(text=f"Page {self.page + 1}/{total_pages}")

        return embed

    async def populate_items(self):
        stock = await self._get_stock()
        page_items, total_items, total_pages = self._paginate(stock)

        options = []
        for item_name, entry in page_items:
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
                cog=self.cog,
            )
        )

        if total_items > ITEMS_PER_PAGE:
            prev_btn = Button(label="◀", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
            async def _prev(inter: discord.Interaction):
                if inter.user.id != self.user_id:
                    return await inter.response.send_message("Not your menu.", ephemeral=True)
                new_view = ItemEmbedView(
                    self.config, self.guild_id, self.user_id, self.shop_name,
                    self.currency, self.mode, page=self.page - 1, cog=self.cog,
                )
                embed = await new_view.build_embed()
                await new_view.populate_items()
                await inter.response.edit_message(embed=embed, view=new_view)
            prev_btn.callback = _prev
            self.add_item(prev_btn)

            next_btn = Button(label="▶", style=discord.ButtonStyle.secondary, disabled=self.page >= total_pages - 1)
            async def _next(inter: discord.Interaction):
                if inter.user.id != self.user_id:
                    return await inter.response.send_message("Not your menu.", ephemeral=True)
                new_view = ItemEmbedView(
                    self.config, self.guild_id, self.user_id, self.shop_name,
                    self.currency, self.mode, page=self.page + 1, cog=self.cog,
                )
                embed = await new_view.build_embed()
                await new_view.populate_items()
                await inter.response.edit_message(embed=embed, view=new_view)
            next_btn.callback = _next
            self.add_item(next_btn)

        # Back button: return to the shop selection (ShopEmbedView)
        back = Button(label="Back", style=discord.ButtonStyle.success)
        async def _back(inter: discord.Interaction):
            if inter.user.id != self.user_id:
                return await inter.response.send_message("Not your menu.", ephemeral=True)
            guild_conf = self.config.guild_from_id(self.guild_id)
            shops = await guild_conf.shops()
            view = ShopEmbedView(self.config, self.guild_id, self.user_id, mode=self.mode, cog=self.cog)
            await view.populate_shops(shops)
            await inter.response.edit_message(
                embed=discord.Embed(
                    title="🛒 Browse Shops",
                    description="Select a shop from the dropdown below:",
                    color=discord.Color.random()
                ),
                view=view,
            )
        back.callback = _back
        self.add_item(back)

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
        *,
        cog: Optional["Shop"] = None,        
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
        self.cog = cog

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
                    cog=self.cog,
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
                    cog=self.cog,
                )
            )

class DeleteShopView(View):
    def __init__(self, config: Config, guild_id: int, *, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.config = config
        self.guild_id = guild_id
        self.message: discord.Message | None = None

    async def populate(self):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        options = [
            discord.SelectOption(label=name, value=name)
            for name in shops.keys()
        ]
        # Dropdown for shop selection
        self.add_item(DeleteShopSelect(options, self.config, self.guild_id))
        # Cancel button
        cancel = Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel.callback = self._cancel
        self.add_item(cancel)

    async def _cancel(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Cancelled.", view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content="⌛ Deletion session expired.",
                    view=self
                )
            except Exception:
                pass


class DeleteShopSelect(Select):
    def __init__(self, options, config: Config, guild_id: int):
        super().__init__(
            placeholder="Choose a shop…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="delete_shop_select",
        )
        self.config = config
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        shop_name = self.values[0]
        await interaction.response.send_modal(
            DeleteConfirmationModal(
                self.config,
                self.guild_id,
                shop_name,
                interaction.message,
                self.view
            )
        )

class DeleteConfirmationModal(Modal, title="Confirm Shop Deletion"):
    confirmation = TextInput(
        label="Type DELETE to confirm",
        placeholder="DELETE",
        style=discord.TextStyle.short,
        required=True
    )

    def __init__(
        self,
        config: Config,
        guild_id: int,
        shop_name: str,
        original_msg: discord.Message,
        parent_view: View
    ):
        super().__init__()
        self.config = config
        self.guild_id = guild_id
        self.shop_name = shop_name
        self.original_msg = original_msg
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        # guard against mistyped confirmation
        if self.confirmation.value.strip().upper() != "DELETE":
            return await interaction.response.send_message(
                "❌ Deletion cancelled. You did not type DELETE.", ephemeral=True
            )

        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        if self.shop_name in shops:
            shops.pop(self.shop_name)
            await guild_conf.shops.set(shops)
            await interaction.response.send_message(
                f"✅ Shop `{self.shop_name}` deleted.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ Shop `{self.shop_name}` not found.", ephemeral=True
            )

        # disable the original dropdown
        parent = self.original_msg
        view = self.parent_view
        for child in view.children:
            child.disabled = True
        try:
            await parent.edit(view=view)
        except Exception:
            pass       
            
class AddStockChooseItemView(View):
    """After selecting a shop: choose an existing item to edit, or use button to add new."""
    def __init__(self, config: Config, guild_id: int, shop_name: str, *, page: int = 0, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.config = config
        self.guild_id = guild_id
        self.shop_name = shop_name
        self.page = page
        self.message: discord.Message | None = None

    async def populate(self):
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        stock = shops.get(self.shop_name, {}).get("stock", {})

        items = list(stock.keys())
        total_pages = max(1, (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * ITEMS_PER_PAGE
        page_items = items[start:start + ITEMS_PER_PAGE]

        options = [discord.SelectOption(label=name, value=name) for name in page_items]
        if options:
            self.add_item(AddStockItemSelect(options, self.config, self.guild_id, self.shop_name))

        if len(items) > ITEMS_PER_PAGE:
            prev_btn = Button(label="◀", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
            async def _prev(inter: discord.Interaction):
                new_view = AddStockChooseItemView(self.config, self.guild_id, self.shop_name, page=self.page - 1)
                await new_view.populate()
                new_view.message = self.message
                await inter.response.edit_message(view=new_view)
            prev_btn.callback = _prev
            self.add_item(prev_btn)

            next_btn = Button(label="▶", style=discord.ButtonStyle.secondary, disabled=self.page >= total_pages - 1)
            async def _next(inter: discord.Interaction):
                new_view = AddStockChooseItemView(self.config, self.guild_id, self.shop_name, page=self.page + 1)
                await new_view.populate()
                new_view.message = self.message
                await inter.response.edit_message(view=new_view)
            next_btn.callback = _next
            self.add_item(next_btn)

        # Add New Item button (separate from the select)
        add_btn = Button(label="➕ Add New Item", style=discord.ButtonStyle.success)
        async def _add_btn_cb(inter: discord.Interaction):
            # open empty StockModal to add a new entry
            await inter.response.send_modal(StockModal(self.config, self.guild_id, self.shop_name))
        add_btn.callback = _add_btn_cb
        self.add_item(add_btn)

        # Cancel button
        cancel = Button(label="Cancel", style=discord.ButtonStyle.danger)
        async def _cancel(inter: discord.Interaction):
            for c in self.children:
                c.disabled = True
            await inter.response.edit_message(content="Cancelled.", view=self)
        cancel.callback = _cancel
        self.add_item(cancel)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(content="⌛ Restock session timed out.", view=self)
            except Exception:
                pass


class AddStockItemSelect(Select):
    def __init__(self, options, config: Config, guild_id: int, shop_name: str):
        super().__init__(
            placeholder="Choose an existing item to edit…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="addstock_item_select",
        )
        self.config = config
        self.guild_id = guild_id
        self.shop_name = shop_name

    async def callback(self, interaction: discord.Interaction):
        sel = self.values[0]
        guild_conf = self.config.guild_from_id(self.guild_id)
        shops = await guild_conf.shops()
        stock = shops.get(self.shop_name, {}).get("stock", {})

        # Prefill modal with existing entry data for editing
        existing = stock.get(sel, {})
        await interaction.response.send_modal(
            StockModal(
                self.config,
                self.guild_id,
                self.shop_name,
                existing_item_name=sel,
                existing_entry=existing,
            )
        )
            