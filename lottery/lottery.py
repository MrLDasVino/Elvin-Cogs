import random

import random

import discord
from discord import Embed, SelectOption
from discord.ui import View, Button, Select, Modal, TextInput
from typing import Optional
from redbot.core import commands, checks, Config, bank


class Lottery(commands.Cog):
    """A lottery system using Red's bank for ticket purchases."""

    def __init__(self, bot: commands.Bot):
        super().__init__()  
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890123456)
        # register defaults synchronously
        self.config.register_global(lotteries={})
        self.config.register_user(tickets={})
        self.active_views: list[View] = []

    @commands.group()
    async def lottery(self, ctx: commands.Context):
        """Base group for lottery commands."""
        pass

    # ----------------------------
    # Admin: Manage lotteries
    # ----------------------------
    @lottery.command()
    @checks.admin()
    async def manage(self, ctx: commands.Context):
        """
        Open a UI to create or edit existing lotteries.
        """
        lotteries = await self.config.lotteries()
        options = [
            SelectOption(label=name, description=data["desc"])
            for name, data in lotteries.items()
        ]
        view = ManageView(self, options)
        self.active_views.append(view)
        if options:
            msg = await ctx.send("🎟️ Lottery Management Panel", view=view)
        else:
            msg = await ctx.send("No lotteries exist yet. Create one below:", view=view)
        view.message = msg  
            
    @lottery.command()
    @checks.admin()
    async def purge(
        self,
        ctx: commands.Context,
        member: discord.Member,
        lottery_name: Optional[str] = None,
    ):
        """
        Purge a user's lottery tickets.
        If lottery_name is provided, clears only that lottery;
        otherwise clears all lotteries for that user in this server.
        """
        lotteries = await self.config.lotteries()
        user_conf = self.config.user(member)
        user_tix = await user_conf.tickets()
        guild_key = str(ctx.guild.id)

        if guild_key not in user_tix:
            return await ctx.send(f"{member.display_name} has no tickets in this server.")

        # Purge a single lottery if specified
        if lottery_name:
            if lottery_name not in lotteries:
                return await ctx.send(f"No lottery named `{lottery_name}` exists.")
            removed_count = user_tix[guild_key].pop(lottery_name, 0)

            # Remove from global ticket list
            tickets = lotteries[lottery_name]["tickets"]
            lotteries[lottery_name]["tickets"] = [uid for uid in tickets if uid != member.id]
            await self.config.lotteries.set(lotteries)

            if not user_tix[guild_key]:
                user_tix.pop(guild_key)
            await user_conf.tickets.set(user_tix)

            return await ctx.send(
                f"Purged {removed_count} tickets of {member.display_name} from `{lottery_name}`."
            )

        # Purge all lotteries for this user
        total_removed = 0
        for name, data in lotteries.items():
            before = len(data["tickets"])
            data["tickets"] = [uid for uid in data["tickets"] if uid != member.id]
            total_removed += before - len(data["tickets"])
        await self.config.lotteries.set(lotteries)

        count_lots = len(user_tix[guild_key])
        user_tix.pop(guild_key)
        await user_conf.tickets.set(user_tix)

        await ctx.send(
            f"Purged {total_removed} tickets across {count_lots} lotteries for {member.display_name}."
        )
            

    # ----------------------------
    # User: Buy tickets
    # ----------------------------
    @lottery.command()
    async def buy(self, ctx: commands.Context):
        """
        Buy a ticket for an existing lottery.
        """
        lotteries = await self.config.lotteries()
        if not lotteries:
            return await ctx.send("There are no active lotteries right now.")
        options = [
            SelectOption(label=name, description=f"{data['desc']} — {data['price']} {await bank.get_currency_name(ctx.guild)} per ticket")
            for name, data in lotteries.items()
        ]
        view = BuyView(self, options)
        self.active_views.append(view)
        msg = await ctx.send("🎟️ Select a lottery to buy a ticket:", view=view)
        view.message = msg  

    # ----------------------------
    # User: Inventory of tickets
    # ----------------------------
    @lottery.command()
    async def inventory(self, ctx: commands.Context):
        """
        Show how many tickets you hold in each lottery.
        """
        user_data = await self.config.user(ctx.author).tickets()
        guild_key = str(ctx.guild.id)
        lotteries = user_data.get(guild_key, {})
        if not lotteries:
            return await ctx.send("You have no lottery tickets.")

        currency = await bank.get_currency_name(ctx.guild)
        config_lots = await self.config.lotteries()
        total = sum(lotteries.values())
        embed = Embed(
            title="🎟️ Your Lottery Tickets",
            description=f"You have a total of **{total}** tickets.",
            color=discord.Color.random()
        )
        embed.set_thumbnail(url="https://files.catbox.moe/9200lc.jpg")
        embed.set_author(
            name=ctx.author.display_name,
            icon_url=ctx.author.display_avatar.url
        )

        for name, count in lotteries.items():
            # pull the configured price for this lottery
            price = config_lots.get(name, {}).get("price", 0)
            embed.add_field(
                name=name,
                value=f"{count} 🎟️ at {price} {currency}",
                inline=True
            )

        await ctx.send(embed=embed)

    # ----------------------------
    # Admin: Draw winner(s)
    # ----------------------------
    @lottery.command()
    @checks.admin()
    async def draw(self, ctx: commands.Context):
        """
        Draw winner(s) for an existing lottery, announce them, and clean up.
        """
        lotteries = await self.config.lotteries()
        if not lotteries:
            return await ctx.send("There are no lotteries to draw from.")
        currency = await bank.get_currency_name(ctx.guild)
        options = [
            SelectOption(
                label=name,
                description=f"{data['desc']} — {len(data['tickets'])} tickets sold"
            )
            for name, data in lotteries.items()
        ]
        view = DrawView(self, options, currency)
        self.active_views.append(view)
        msg = await ctx.send("🎟️ Select a lottery to draw a winner for:", view=view)
        view.message = msg  


class DrawView(View):
    def __init__(self, cog: Lottery, options: list[SelectOption], currency: str):
        super().__init__(timeout=60) 
        self.cog = cog
        self.currency = currency
        self.message: discord.Message        

        # Add exactly one Select with real options
        draw_select = Select(
            placeholder="🎟️ Choose a lottery…",
            options=options,
            custom_id="lottery_draw_select",
            min_values=1,
            max_values=1
        )
        draw_select.callback = self._draw_callback
        self.add_item(draw_select)
        
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if hasattr(self, "message"):
            await self.message.edit(view=self)        

    async def _draw_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        choice = interaction.data["values"][0]
        data = (await self.cog.config.lotteries())[choice]
        tickets = data["tickets"]
        if not tickets:
            return await interaction.followup.send("No tickets were sold for this lottery.")
        winner_count = min(data["winners"], len(tickets))
        winners = random.sample(tickets, k=winner_count)

        from datetime import datetime

        # Build a richer embed
        embed = Embed(
            title="🎊 Lottery Draw Result 🎊",
            description=(
                f"**{choice}** has concluded!\n"
                f"**Winners ({winner_count})**"
            ),
            color=discord.Color.random(),
            timestamp=datetime.utcnow()
        )
        # Optional celebratory thumbnail
        embed.set_thumbnail(url="https://files.catbox.moe/gachc4.jpg")

        # Compile each winner with their prizes
        lines: list[str] = []
        for uid in winners:
            member = interaction.guild.get_member(uid) or await self.cog.bot.fetch_user(uid)
            prizes_awarded: list[str] = []

            # Currency prize
            cur_prize = data.get("currency_prize")
            if cur_prize:
                await bank.deposit_credits(member, cur_prize)
                prizes_awarded.append(f"💰 {cur_prize} {self.currency}")

            # Role prize
            role_id = data.get("role_prize")
            if role_id:
                role = interaction.guild.get_role(role_id)
                if role:
                    await member.add_roles(role, reason=f"Lottery win: {choice}")
                    prizes_awarded.append(f"🎖️ {role.name}")

            prize_desc = " & ".join(prizes_awarded) if prizes_awarded else "🎉 Congratulations!"
            lines.append(f"• {member.mention} — {prize_desc}")

        embed.add_field(name="🏆 Winners & Prizes", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"Lottery: {choice}")

        await interaction.followup.send(embed=embed)

        # Remove the lottery
        lotteries = await self.cog.config.lotteries()
        lotteries.pop(choice, None)
        await self.cog.config.lotteries.set(lotteries)

        # Clean up tickets from all users in this guild
        all_users = await self.cog.config.all_users()
        guild_key = str(interaction.guild.id)
        for user_id, udata in all_users.items():
            tickets = udata.get("tickets", {})
            user_tix = tickets.get(guild_key, {})
            if choice in user_tix:
                # Remove this lottery from the user's guild‐specific tickets
                user_tix.pop(choice, None)

                # If no other lotteries in this guild, drop the guild entry
                if not user_tix:
                    tickets.pop(guild_key, None)
                else:
                    tickets[guild_key] = user_tix

                # Save back the cleaned tickets mapping
                await self.cog.config.user_from_id(int(user_id)).tickets.set(tickets)
        for child in self.children:
            child.disabled = True
        if getattr(self, "message", None):
            await self.message.edit(view=self)
        self.stop()


    # ----------------------------
    # Admin: Create/Edit lotteries
    # ----------------------------
class ManageView(View):
    def __init__(self, cog: Lottery, options: list[SelectOption]):
        super().__init__(timeout=60)  
        self.cog = cog
        self.message: discord.Message         

        # Always add the Create button with a unique custom_id
        create_btn = Button(
            label="Create Lottery",
            style=discord.ButtonStyle.green,
            custom_id="lottery_create_btn"
        )
        create_btn.callback = self._create_callback
        self.add_item(create_btn)

        # Only add the Edit dropdown if there are existing lotteries
        if options:
            edit_select = Select(
                placeholder="Edit existing…",
                options=options,
                custom_id="lottery_edit_select",
                min_values=1,
                max_values=1
            )
            edit_select.callback = self._edit_callback
            self.add_item(edit_select)
            
    async def on_timeout(self):
        # disable every component when the view times out
        for child in self.children:
            child.disabled = True
        if hasattr(self, "message"):
            await self.message.edit(view=self)            

    async def _create_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CreateLotteryModal(self.cog))

    async def _edit_callback(self, interaction: discord.Interaction):
        name = interaction.data["values"][0]
        data = (await self.cog.config.lotteries())[name]
        await interaction.response.send_modal(EditLotteryModal(self.cog, name, data))


class CreateLotteryModal(Modal):
    def __init__(self, cog: Lottery):
        super().__init__(title="Create Lottery")
        self.cog = cog
        self.name = TextInput(label="Name", placeholder="Unique key, e.g. winter_raffle")
        self.desc = TextInput(label="Description", placeholder="What is this lottery for?")
        self.price = TextInput(label="Ticket Price", placeholder="Number, e.g. 100", max_length=12)
        self.winners = TextInput(label="Number of Winners", placeholder="e.g. 1", max_length=2)        
        for item in (self.name, self.desc, self.price, self.winners):
            self.add_item(item)
        self.prizes = TextInput(
            label="Prizes (optional)",
            placeholder="Format: currency=1000;role=Moderator (or role ID)",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=100
        )
        self.add_item(self.prizes)           

    async def on_submit(self, interaction: discord.Interaction):
        # strip and convert the core fields
        name = self.name.value.strip()
        desc = self.desc.value.strip()
        price = int(self.price.value.strip())
        winners = int(self.winners.value.strip())

        # ─── PARSE COMBINED PRIZES ────────────────────────────────────────────
        cur_prize = None
        role_id = None
        if self.prizes.value and self.prizes.value.strip():
            for part in self.prizes.value.split(";"):
                key, *val = part.strip().split("=", 1)
                if not val:
                    continue
                v = val[0].strip()
                if key.lower() == "currency" and v.isdigit():
                    cur_prize = int(v)
                elif key.lower() == "role":
                    if v.isdigit():
                        role_id = int(v)
                    else:
                        role = discord.utils.get(interaction.guild.roles, name=v)
                        role_id = role.id if role else None

        # ensure we don’t overwrite an existing lottery
        lotteries = await self.cog.config.lotteries()
        if name in lotteries:
            return await interaction.response.send_message(
                "A lottery with that name already exists.", ephemeral=True
            )

        # build and persist
        lotteries[name] = {
            "desc": desc,
            "price": price,
            "winners": winners,
            "tickets": [],
            "currency_prize": cur_prize,
            "role_prize": role_id,
        }
        await self.cog.config.lotteries.set(lotteries)

        # confirm creation
        await interaction.response.send_message(
            f"✅ Created lottery **{name}**.", ephemeral=True
        )

class EditLotteryModal(Modal):
    def __init__(self, cog: Lottery, name: str, data: dict):
        super().__init__(title=f"Edit Lottery: {name}")
        self.cog = cog
        self.lotto_name = name
        self.desc = TextInput(label="Description", default=data["desc"])
        self.price = TextInput(label="Ticket Price", default=str(data["price"]), max_length=12)
        self.winners = TextInput(label="Number of Winners", default=str(data["winners"]), max_length=2)
        prize_defaults = []
        if data.get("currency_prize") is not None:
            prize_defaults.append(f"currency={data['currency_prize']}")
        if data.get("role_prize") is not None:
            prize_defaults.append(f"role={data['role_prize']}")
        default_prizes = ";".join(prize_defaults)

        self.prizes = TextInput(
            label="Prizes (optional)",
            placeholder="currency=1000;role=Moderator or role ID",
            style=discord.TextStyle.paragraph,
            default=default_prizes,
            required=False,
            max_length=100
        )
        self.add_item(self.prizes)

    async def on_submit(self, interaction: discord.Interaction):
        desc = self.desc.value.strip()
        price = int(self.price.value)
        winners = int(self.winners.value)
        cur_prize = None
        role_id = None
        if self.prizes.value and self.prizes.value.strip():
            for part in self.prizes.value.split(";"):
                key, *val = part.strip().split("=", 1)
                if not val:
                    continue
                v = val[0].strip()
                if key.lower() == "currency" and v.isdigit():
                    cur_prize = int(v)
                elif key.lower() == "role":
                    if v.isdigit():
                        role_id = int(v)
                    else:
                        role = discord.utils.get(interaction.guild.roles, name=v)
                        role_id = role.id if role else None      
        lotteries = await self.cog.config.lotteries()
        lotteries[self.lotto_name].update({
            "desc": desc,
            "price": price,
            "winners": winners,
            "currency_prize": cur_prize,
            "role_prize": role_id,
        })
        await self.cog.config.lotteries.set(lotteries)
        await interaction.response.send_message(
            f"✏️ Updated lottery **{self.lotto_name}**.",
            ephemeral=True
        )


    # ----------------------------
    # User: Buy tickets UI
    # ----------------------------
class BuyView(View):
    def __init__(self, cog: Lottery, options: list[SelectOption]):
        super().__init__(timeout=60) 
        self.cog = cog
        self.message: discord.Message       

        buy_select = Select(
            placeholder="🎟️ Select lottery…",
            options=options,
            custom_id="lottery_buy_select",
            min_values=1,
            max_values=1
        )
        buy_select.callback = self._buy_callback
        self.add_item(buy_select)
        
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if hasattr(self, "message"):
            await self.message.edit(view=self)        

    async def _buy_callback(self, interaction: discord.Interaction):
        choice = interaction.data["values"][0]
        lotteries = await self.cog.config.lotteries()
        data = lotteries[choice]
        price = data["price"]

        # Open a modal to ask for ticket quantity
        await interaction.response.send_modal(
            BuyAmountModal(self.cog, choice, price)
        )
        for child in self.children:
            child.disabled = True
        if getattr(self, "message", None):
            await self.message.edit(view=self)
        self.stop()

# Modal for entering how many tickets to purchase
class BuyAmountModal(Modal, title="Buy Tickets"):
    def __init__(self, cog: Lottery, choice: str, price: int):
        super().__init__()
        self.cog = cog
        self.choice = choice
        self.price = price
        self.amount = TextInput(
            label="Number of tickets",
            placeholder="Enter how many tickets you want",
            min_length=1,
            max_length=6
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        amount = int(self.amount.value)
        total_cost = amount * self.price
        author = interaction.user

        # Check funds for total
        if not await bank.can_spend(author, total_cost):
            return await interaction.response.send_message(
                f"You need {total_cost} {await bank.get_currency_name(interaction.guild)}, "
                "but you have insufficient funds.",
                ephemeral=True
            )

        # Withdraw total cost
        await bank.withdraw_credits(author, total_cost)

        # Record tickets globally
        lotteries = await self.cog.config.lotteries()
        data = lotteries[self.choice]
        data["tickets"].extend([author.id] * amount)
        lotteries[self.choice] = data
        await self.cog.config.lotteries.set(lotteries)

        # Record tickets per user
        user_tix = await self.cog.config.user(author).tickets()
        guild_key = str(interaction.guild.id)
        user_tix.setdefault(guild_key, {})
        user_tix[guild_key][self.choice] = (
            user_tix[guild_key].get(self.choice, 0) + amount
        )
        await self.cog.config.user(author).tickets.set(user_tix)

        curr_name = await bank.get_currency_name(interaction.guild)
        await interaction.response.send_message(
            f"🎟️ You purchased {amount} tickets for **{self.choice}** "
            f"for {total_cost} {curr_name}.",
            ephemeral=True
        )


# ----------------------------
# Cog Setup
# ----------------------------
async def setup(bot):
    await bot.add_cog(Lottery(bot))

