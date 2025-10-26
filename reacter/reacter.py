import random
import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import inline
from typing import Optional

default_guild = {
    "enabled": False,
    "frequency": 10,  # percent chance 1-100
    "amount": 2       # number of possible emoji rolls per message
}

class Reacter(commands.Cog):
    """Randomly react to messages with server emojis (includes animated emojis)."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xBEEF1234CAFEBABE)
        self.config.register_guild(**default_guild)

    # ---------------------
    # Admin commands group
    # ---------------------
    @commands.group()
    @commands.admin_or_permissions(manage_guild=True)
    async def reacter(self, ctx: commands.Context):
        """Reacter settings group."""
        if ctx.invoked_subcommand is None:
            data = await self.config.guild(ctx.guild).all()
            enabled = data.get("enabled", False)
            freq = data.get("frequency", 10)
            amt = data.get("amount", 2)
            await ctx.send(
                f"Reacter settings for this server — enabled: {inline(str(enabled))}, frequency: {inline(str(freq))}% , amount: {inline(str(amt))}"
            )

    @reacter.command(name="enable")
    async def reacter_enable(self, ctx: commands.Context, enabled: Optional[bool] = None):
        """Enable or disable the reacter. Usage: reacter enable [true|false]"""
        if enabled is None:
            # toggle if no argument provided
            current = await self.config.guild(ctx.guild).enabled()
            enabled = not current
        await self.config.guild(ctx.guild).enabled.set(bool(enabled))
        await ctx.send(f"Reacter enabled set to {inline(str(bool(enabled)))}")

    @reacter.command(name="frequency")
    async def reacter_frequency(self, ctx: commands.Context, percent: int):
        """Set base chance (1-100) for reacting to messages. Example: reacter frequency 25"""
        if percent < 1 or percent > 100:
            await ctx.send("Frequency must be between 1 and 100.")
            return
        await self.config.guild(ctx.guild).frequency.set(int(percent))
        await ctx.send(f"Reacter frequency set to {inline(str(percent))}%")

    @reacter.command(name="amount")
    async def reacter_amount(self, ctx: commands.Context, amount: int):
        """Set maximum number of emoji rolls per message (>=1). Example: reacter amount 3"""
        if amount < 1 or amount > 20:
            await ctx.send("Amount must be between 1 and 20.")
            return
        await self.config.guild(ctx.guild).amount.set(int(amount))
        await ctx.send(f"Reacter amount set to {inline(str(amount))}")

    # ---------------------
    # Listener
    # ---------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots and webhooks
        if message.author.bot or message.webhook_id is not None:
            return

        # Guild only
        if message.guild is None:
            return

        # Permissions check: bot must be able to add reactions
        me = message.guild.me or message.guild.get_member(self.bot.user.id)
        if me is None:
            return
        if not me.guild_permissions.add_reactions:
            return

        # Get guild config
        conf = await self.config.guild(message.guild).all()
        if not conf.get("enabled", False):
            return

        frequency = conf.get("frequency", 10)
        amount = conf.get("amount", 2)

        # Validate
        try:
            frequency = int(frequency)
            amount = int(amount)
        except Exception:
            frequency = default_guild["frequency"]
            amount = default_guild["amount"]

        # Collect usable emojis from the guild (including animated)
        usable_emojis = [e for e in message.guild.emojis if e.available]
        if not usable_emojis:
            return

        # Avoid reacting to empty messages
        if len(message.content or "") <= 0 and not message.attachments:
            return

        chosen_emojis = []

        # First roll: must succeed to continue
        first_roll = random.randint(1, 100)
        if first_roll > frequency:
            return  # do not attempt any reactions if the first roll fails

        # Pick first emoji (unique)
        tries = 0
        emoji = None
        while tries < 6:
            candidate = random.choice(usable_emojis)
            if candidate not in chosen_emojis:
                emoji = candidate
                break
            tries += 1
        if not emoji:
            return
        chosen_emojis.append(emoji)

        # Remaining rolls: each independent; if roll succeeds, pick a new unique emoji
        for _ in range(amount - 1):
            roll = random.randint(1, 100)
            if roll > frequency:
                continue  # independent chance; failing this roll doesn't stop the others
            tries = 0
            emoji = None
            while tries < 6:
                candidate = random.choice(usable_emojis)
                if candidate not in chosen_emojis:
                    emoji = candidate
                    break
                tries += 1
            if emoji:
                chosen_emojis.append(emoji)
            else:
                break  # no new emoji available, stop trying

        # Attempt to react with each chosen emoji
        for emoji in chosen_emojis:
            try:
                await message.add_reaction(str(emoji))
            except discord.Forbidden:
                return
            except discord.HTTPException:
                continue
