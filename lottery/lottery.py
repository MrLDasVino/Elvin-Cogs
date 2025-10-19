import random

import random

import discord
from discord import Embed, SelectOption
from discord.ui import View, Button, Select, Modal, TextInput
from redbot.core import commands, checks, Config, bank


class Lottery(commands.Cog):
    """A lottery system using Red's bank for ticket purchases."""

    def __init__(self, bot: commands.Bot):
        super().__init__()  # initialize Cog base
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890123456)
        # register defaults synchronously
        self.config.register_global(lotteries={})
        self.config.register_user(tickets={})

    @commands.group()
    async def lottery(self, ctx: commands.Context):
        """Base group for lottery commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    # ----------------------------
    # Admin: Manage lotteries
    # ----------------------------
    @lottery.group()
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
        if options:
            await ctx.send("🎟️ Lottery Management Panel", view=view)
        else:
            await ctx.send("No lotteries exist yet. Create one below:", view=view)

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
        await ctx.send("Select a lottery to buy a ticket:", view=view)

    # ----------------------------
    # User: Inventory of tickets
    # ----------------------------
    @lottery.command()
    async def inventory(self, ctx: commands.Context):
        """
        Show how many tickets you hold in each lottery.
        """
        user_data = await self.config.user(ctx.author).tickets()
        lines = []
        currency = await bank.get_currency_name(ctx.guild)
        for guild_id, lotteries in user_data.items():
            if str(ctx.guild.id) != guild_id:
                continue
            for name, count in lotteries.items():
                lines.append(f"{name}: {count} tickets")
        if not lines:
            return await ctx.send("You have no lottery tickets.")
        embed = Embed(title=f"{ctx.author.display_name}'s Tickets", description="\n".join(lines), color=discord.Color.blurple())
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
        await ctx.send("Select a lottery to draw a winner for:", view=view)


class DrawView(View):
    def __init__(self, cog: Lottery, options: list[SelectOption], currency: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.currency = currency
        self.add_item(Select(
            placeholder="Choose a lottery…",
            options=options,
            custom_id="lottery_draw_select",
            min_values=1,
            max_values=1
        ))

    @discord.ui.select()
    async def select_callback(self, select: Select, interaction: discord.Interaction):
        await interaction.response.defer()
        choice = select.values[0]
        data = (await self.cog.config.lotteries())[choice]
        tickets = data["tickets"]
        if not tickets:
            return await interaction.followup.send("No tickets were sold for this lottery.")
        winner_count = min(data["winners"], len(tickets))
        winners = random.sample(tickets, k=winner_count)

        embed = Embed(
            title=f"🎉 Lottery Draw: {choice} 🎉",
            color=discord.Color.gold(),
            description=f"{winner_count} winner{'s' if winner_count>1 else ''} drawn!"
        )
        for uid in winners:
            member = interaction.guild.get_member(uid) or await self.cog.bot.fetch_user(uid)
            embed.add_field(name=member.display_name, value=f"Congratulations!", inline=False)

        await interaction.followup.send(embed=embed)

        # Remove the lottery
        lotteries = await self.cog.config.lotteries()
        lotteries.pop(choice, None)
        await self.cog.config.lotteries.set(lotteries)

        # Clean up tickets from all users
        all_users = await self.cog.config.all_users()
        for user_id, udata in all_users.items():
            tix = udata["tickets"]
            if choice in tix:
                tix.pop(choice)
                await self.cog.config.user_from_id(user_id).tickets.set(tix)

        # Stop listening to further interactions
        self.stop()


    # ----------------------------
    # Admin: Create/Edit lotteries
    # ----------------------------
class ManageView(View):
    def __init__(self, cog: Lottery, options: list[SelectOption]):
        super().__init__(timeout=None)
        self.cog = cog

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

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name.value.strip()
        desc = self.desc.value.strip()
        price = int(self.price.value)
        winners = int(self.winners.value)
        lotteries = await self.cog.config.lotteries()
        if name in lotteries:
            return await interaction.response.send_message("A lottery with that name already exists.", ephemeral=True)
        lotteries[name] = {"desc": desc, "price": price, "winners": winners, "tickets": []}
        await self.cog.config.lotteries.set(lotteries)
        await interaction.response.send_message(f"✅ Created lottery **{name}**.", ephemeral=True)


class EditLotteryModal(Modal):
    def __init__(self, cog: Lottery, name: str, data: dict):
        super().__init__(title=f"Edit Lottery: {name}")
        self.cog = cog
        self.lotto_name = name
        self.desc = TextInput(label="Description", default=data["desc"])
        self.price = TextInput(label="Ticket Price", default=str(data["price"]), max_length=12)
        self.winners = TextInput(label="Number of Winners", default=str(data["winners"]), max_length=2)
        for item in (self.desc, self.price, self.winners):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        desc = self.desc.value.strip()
        price = int(self.price.value)
        winners = int(self.winners.value)
        lotteries = await self.cog.config.lotteries()
        lotteries[self.lotto_name].update({"desc": desc, "price": price, "winners": winners})
        await self.cog.config.lotteries.set(lotteries)
        await interaction.response.send_message(f"✏️ Updated lottery **{self.lotto_name}**.", ephemeral=True)


    # ----------------------------
    # User: Buy tickets UI
    # ----------------------------
class BuyView(View):
    def __init__(self, cog: Lottery, options: list[SelectOption]):
        super().__init__(timeout=None)
        self.cog = cog

        buy_select = Select(
            placeholder="Select lottery…",
            options=options,
            custom_id="lottery_buy_select",
            min_values=1,
            max_values=1
        )
        buy_select.callback = self._buy_callback
        self.add_item(buy_select)

    async def _buy_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        choice = interaction.data["values"][0]
        lotteries = await self.cog.config.lotteries()
        data = lotteries[choice]
        price = data["price"]
        author = interaction.user

        if not await bank.can_spend(author, price):
            return await interaction.followup.send(
                "You don't have enough funds to buy a ticket.",
                ephemeral=True
            )

        await bank.withdraw_credits(author, price)

        # Global ticket record
        data["tickets"].append(author.id)
        lotteries[choice] = data
        await self.cog.config.lotteries.set(lotteries)

        # User inventory record
        user_tix = await self.cog.config.user(author).tickets()
        guild_key = str(interaction.guild.id)
        user_tix.setdefault(guild_key, {})
        user_tix[guild_key][choice] = user_tix[guild_key].get(choice, 0) + 1
        await self.cog.config.user(author).tickets.set(user_tix)

        curr_name = await bank.get_currency_name(interaction.guild)
        await interaction.followup.send(
            f"🎟️ You bought a ticket for **{choice}** "
            f"for {price} {curr_name}.",
            ephemeral=True
        )
        self.stop()


# ----------------------------
# Cog Setup
# ----------------------------
async def setup(bot):
    await bot.add_cog(Lottery(bot))

