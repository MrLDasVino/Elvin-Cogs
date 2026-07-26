import asyncio
import io
import random
import re
from typing import Optional

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")


class ConfirmView(discord.ui.View):
    def __init__(self, author: discord.abc.User):
        super().__init__(timeout=30)
        self.author = author
        self.value: Optional[bool] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "This isn't your menu to control.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        await interaction.response.defer()
        self.stop()


class AddWordModal(discord.ui.Modal, title="Add Blacklisted Words"):
    words_input = discord.ui.TextInput(
        label="Words (comma separated)",
        style=discord.TextStyle.paragraph,
        placeholder="word1, word2, word3",
        required=True,
        max_length=1000,
    )

    def __init__(self, cog: "ChatterBox", ctx: commands.Context):
        super().__init__()
        self.cog = cog
        self.ctx = ctx

    async def on_submit(self, interaction: discord.Interaction):
        new_words = [w.strip().lower() for w in self.words_input.value.split(",") if w.strip()]
        if not new_words:
            await interaction.response.send_message(
                "No valid words were provided.", ephemeral=True
            )
            return
        async with self.cog.config.guild(self.ctx.guild).blacklist() as blacklist:
            for word in new_words:
                if word not in blacklist:
                    blacklist.append(word)
            blacklist.sort()
        removed = await self.cog.purge_blacklisted_messages(self.ctx.guild, new_words)
        await interaction.response.send_message(
            f"Added {len(new_words)} word(s) to the blacklist and removed {removed} "
            "matching saved message(s) from the database.",
            ephemeral=True,
        )


class BlacklistView(discord.ui.View):
    def __init__(self, cog: "ChatterBox", ctx: commands.Context):
        super().__init__(timeout=120)
        self.cog = cog
        self.ctx = ctx
        self.message: Optional[discord.Message] = None

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "This isn't your menu to control.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Import (Overwrite)", style=discord.ButtonStyle.primary)
    async def import_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Upload a .txt file with your blacklisted words separated by commas, "
            "or just type the words separated by commas. This will replace the entire "
            "blacklist. You have 60 seconds.",
            ephemeral=True,
        )

        def check(m: discord.Message) -> bool:
            return m.author.id == self.ctx.author.id and m.channel.id == self.ctx.channel.id

        try:
            message = await self.cog.bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            await interaction.followup.send(
                "You didn't respond in time. Import cancelled.", ephemeral=True
            )
            return

        if message.attachments:
            attachment = message.attachments[0]
            try:
                raw = await attachment.read()
                content = raw.decode("utf-8")
            except Exception:
                await interaction.followup.send(
                    "I couldn't read that file. Make sure it's a plain text file.",
                    ephemeral=True,
                )
                return
        else:
            content = message.content

        words = sorted({w.strip().lower() for w in content.split(",") if w.strip()})
        await self.cog.config.guild(self.ctx.guild).blacklist.set(words)
        removed = await self.cog.purge_blacklisted_messages(self.ctx.guild, words)

        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass

        await interaction.followup.send(
            f"Imported {len(words)} blacklisted word(s), overwriting the previous list, "
            f"and removed {removed} matching saved message(s) from the database.",
            ephemeral=True,
        )

    @discord.ui.button(label="Add Words", style=discord.ButtonStyle.secondary)
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddWordModal(self.cog, self.ctx))

    @discord.ui.button(label="Export", style=discord.ButtonStyle.secondary)
    async def export_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        blacklist = await self.cog.config.guild(self.ctx.guild).blacklist()
        if not blacklist:
            await interaction.response.send_message(
                "The blacklist is currently empty.", ephemeral=True
            )
            return
        content = ", ".join(blacklist)
        buffer = io.BytesIO(content.encode("utf-8"))
        file = discord.File(buffer, filename="chatterbox_blacklist.txt")
        await interaction.response.send_message(file=file, ephemeral=True)


class ChannelAddSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select a channel to ignore",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "ChannelAddView" = self.view
        channel = self.values[0]
        async with view.cog.config.guild(view.ctx.guild).ignored_channels() as ignored:
            if channel.id in ignored:
                await interaction.response.send_message(
                    f"{channel.mention} is already being ignored.", ephemeral=True
                )
                return
            ignored.append(channel.id)
        embed = await view.cog.build_channels_embed(view.ctx)
        try:
            await view.parent_message.edit(embed=embed)
        except discord.HTTPException:
            pass
        await interaction.response.send_message(
            f"{channel.mention} will now be ignored by ChatterBox.", ephemeral=True
        )


class ChannelAddView(discord.ui.View):
    def __init__(self, cog: "ChatterBox", ctx: commands.Context, parent_message: discord.Message):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.parent_message = parent_message
        self.add_item(ChannelAddSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "This isn't your menu to control.", ephemeral=True
            )
            return False
        return True


class ChannelRemoveSelect(discord.ui.Select):
    def __init__(self, ignored_channels, guild: discord.Guild):
        options = []
        for channel_id in ignored_channels[:25]:
            channel = guild.get_channel(channel_id)
            label = f"#{channel.name}" if channel else str(channel_id)
            options.append(discord.SelectOption(label=label[:100], value=str(channel_id)))
        super().__init__(
            placeholder="Select a channel to remove",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "ChannelRemoveView" = self.view
        channel_id = int(self.values[0])
        async with view.cog.config.guild(view.ctx.guild).ignored_channels() as ignored:
            if channel_id in ignored:
                ignored.remove(channel_id)
        channel = view.ctx.guild.get_channel(channel_id)
        mention = channel.mention if channel else f"`{channel_id}`"
        embed = await view.cog.build_channels_embed(view.ctx)
        try:
            await view.parent_message.edit(embed=embed)
        except discord.HTTPException:
            pass
        await interaction.response.send_message(
            f"{mention} will no longer be ignored by ChatterBox.", ephemeral=True
        )


class ChannelRemoveView(discord.ui.View):
    def __init__(
        self,
        cog: "ChatterBox",
        ctx: commands.Context,
        parent_message: discord.Message,
        ignored_channels,
    ):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.parent_message = parent_message
        self.add_item(ChannelRemoveSelect(ignored_channels, ctx.guild))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "This isn't your menu to control.", ephemeral=True
            )
            return False
        return True


class ChannelsView(discord.ui.View):
    def __init__(self, cog: "ChatterBox", ctx: commands.Context):
        super().__init__(timeout=120)
        self.cog = cog
        self.ctx = ctx
        self.message: Optional[discord.Message] = None

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "This isn't your menu to control.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Add Channel", style=discord.ButtonStyle.success)
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ChannelAddView(self.cog, self.ctx, self.message)
        await interaction.response.send_message(
            "Choose a channel to add to the ignore list.", view=view, ephemeral=True
        )

    @discord.ui.button(label="Remove Channel", style=discord.ButtonStyle.danger)
    async def remove_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ignored = await self.cog.config.guild(self.ctx.guild).ignored_channels()
        if not ignored:
            await interaction.response.send_message(
                "There are no ignored channels to remove.", ephemeral=True
            )
            return
        view = ChannelRemoveView(self.cog, self.ctx, self.message, ignored)
        await interaction.response.send_message(
            "Choose a channel to remove from the ignore list.", view=view, ephemeral=True
        )


class ChatterBox(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1357924680, force_registration=True)
        self.config.register_guild(
            enabled=False,
            frequency=5,
            blacklist=[],
            messages=[],
            max_messages=None,
            min_length=0,
            ping_users=False,
            ignored_channels=[],
        )

    async def cog_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return False
        if await self.bot.is_owner(ctx.author):
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        return await self.bot.is_admin(ctx.author)

    async def red_get_data_for_user(self, *, user_id: int):
        return {}

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:
        return

    async def build_channels_embed(self, ctx: commands.Context) -> discord.Embed:
        ignored = await self.config.guild(ctx.guild).ignored_channels()
        if ignored:
            lines = []
            for channel_id in ignored:
                channel = ctx.guild.get_channel(channel_id)
                lines.append(channel.mention if channel else f"`{channel_id}` (deleted channel)")
            description = "\n".join(lines)
        else:
            description = "There are currently no ignored channels."
        return discord.Embed(
            title="ChatterBox Ignored Channels",
            description=description,
            color=await ctx.embed_color(),
        )

    async def purge_blacklisted_messages(self, guild: discord.Guild, words) -> int:
        if not words:
            return 0
        removed = 0
        async with self.config.guild(guild).messages() as messages:
            kept = []
            for msg in messages:
                lowered = msg.lower()
                if any(word in lowered for word in words):
                    removed += 1
                else:
                    kept.append(msg)
            messages[:] = kept
        return removed

    @commands.group(name="chatterbox", invoke_without_command=True)
    @commands.guild_only()
    async def chatterbox(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    @chatterbox.command(name="enable", help="Enable ChatterBox in this server.")
    async def chatterbox_enable(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send(
            "ChatterBox is now enabled. I will start collecting messages and "
            "chiming in randomly."
        )

    @chatterbox.command(name="disable", help="Disable ChatterBox in this server.")
    async def chatterbox_disable(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("ChatterBox is now disabled.")

    @chatterbox.command(name="status", help="View the current ChatterBox settings.")
    async def chatterbox_status(self, ctx: commands.Context):
        data = await self.config.guild(ctx.guild).all()
        embed = discord.Embed(title="ChatterBox Settings", color=await ctx.embed_color())
        embed.add_field(name="Enabled", value=str(data["enabled"]))
        embed.add_field(name="Frequency", value=f"{data['frequency']}%")
        embed.add_field(name="Stored Messages", value=str(len(data["messages"])))
        max_messages_display = "No limit" if data["max_messages"] is None else str(data["max_messages"])
        embed.add_field(name="Max Stored Messages", value=max_messages_display)
        embed.add_field(name="Min Message Length", value=str(data["min_length"]))
        embed.add_field(name="Blacklisted Words", value=str(len(data["blacklist"])))
        embed.add_field(name="Ping Users", value=str(data["ping_users"]))
        embed.add_field(name="Ignored Channels", value=str(len(data["ignored_channels"])))
        await ctx.send(embed=embed)

    @chatterbox.command(
        name="frequency", help="View or set how often the bot chimes in, as a percentage."
    )
    async def chatterbox_frequency(self, ctx: commands.Context, percent: Optional[int] = None):
        if percent is None:
            current = await self.config.guild(ctx.guild).frequency()
            await ctx.send(f"The current chat frequency is {current}%.")
            return
        if percent < 0 or percent > 100:
            await ctx.send("Please provide a percentage between 0 and 100.")
            return
        await self.config.guild(ctx.guild).frequency.set(percent)
        await ctx.send(f"Chat frequency set to {percent}%.")

    @chatterbox.command(
        name="maxmessages",
        help=(
            "View or set the maximum number of messages to store. Pass 'none' for no limit, "
            "or a number to cap it. Defaults to no limit."
        ),
    )
    async def chatterbox_maxmessages(self, ctx: commands.Context, amount: Optional[str] = None):
        if amount is None:
            current = await self.config.guild(ctx.guild).max_messages()
            if current is None:
                await ctx.send("There is currently no limit on stored messages.")
            else:
                await ctx.send(f"The current maximum stored messages is {current}.")
            return

        if amount.lower() in ("none", "unlimited", "nolimit", "no", "off", "0"):
            await self.config.guild(ctx.guild).max_messages.set(None)
            await ctx.send("Maximum stored messages set to no limit. All messages will be kept.")
            return

        if not amount.isdigit() or int(amount) < 1:
            await ctx.send(
                "Please provide a whole number greater than 0, or `none` for no limit."
            )
            return

        cap = int(amount)
        await self.config.guild(ctx.guild).max_messages.set(cap)
        async with self.config.guild(ctx.guild).messages() as messages:
            if len(messages) > cap:
                del messages[: len(messages) - cap]
        await ctx.send(f"Maximum stored messages set to {cap}.")

    @chatterbox.command(
        name="minlength", help="View or set the minimum message length required to be stored."
    )
    async def chatterbox_minlength(self, ctx: commands.Context, length: Optional[int] = None):
        if length is None:
            current = await self.config.guild(ctx.guild).min_length()
            await ctx.send(f"The current minimum message length is {current} characters.")
            return
        if length < 0:
            await ctx.send("Please provide a number of 0 or greater.")
            return
        await self.config.guild(ctx.guild).min_length.set(length)
        await ctx.send(f"Minimum message length set to {length} characters.")

    @chatterbox.command(
        name="ping",
        help=(
            "View or set whether the bot is allowed to ping users when a saved message "
            "mentions them. @everyone and role mentions are always ignored."
        ),
    )
    async def chatterbox_ping(self, ctx: commands.Context, toggle: Optional[bool] = None):
        if toggle is None:
            current = await self.config.guild(ctx.guild).ping_users()
            state = "enabled" if current else "disabled"
            await ctx.send(
                f"User pinging is currently **{state}**. `@everyone` and role mentions "
                "are always ignored regardless of this setting."
            )
            return
        await self.config.guild(ctx.guild).ping_users.set(toggle)
        state = "enabled" if toggle else "disabled"
        await ctx.send(
            f"User pinging is now **{state}**. `@everyone` and role mentions will always "
            "be ignored."
        )

    @chatterbox.command(
        name="channels",
        help="View and manage the channels ChatterBox should ignore, using buttons to add or remove them.",
    )
    async def chatterbox_channels(self, ctx: commands.Context):
        embed = await self.build_channels_embed(ctx)
        view = ChannelsView(self, ctx)
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    @chatterbox.command(
        name="blacklist", help="Manage the word blacklist using buttons to import, add, or export."
    )
    async def chatterbox_blacklist(self, ctx: commands.Context):
        blacklist = await self.config.guild(ctx.guild).blacklist()
        embed = discord.Embed(
            title="ChatterBox Blacklist",
            description=f"There are currently {len(blacklist)} blacklisted word(s).",
            color=await ctx.embed_color(),
        )
        view = BlacklistView(self, ctx)
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    @chatterbox.command(name="purge", help="Permanently wipe all of ChatterBox's saved messages.")
    async def chatterbox_purge(self, ctx: commands.Context):
        count = len(await self.config.guild(ctx.guild).messages())
        if count == 0:
            await ctx.send("There are no saved messages to purge.")
            return
        view = ConfirmView(ctx.author)
        message = await ctx.send(
            f"This will permanently delete {count} saved message(s). Are you sure?", view=view
        )
        await view.wait()
        if view.value is None:
            await message.edit(content="Purge timed out.", view=None)
        elif view.value:
            await self.config.guild(ctx.guild).messages.set([])
            await message.edit(content=f"Purged {count} saved message(s).", view=None)
        else:
            await message.edit(content="Purge cancelled.", view=None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None:
            return
        if message.author.bot:
            return
        if not message.content:
            return
        if message.attachments:
            return
        if not message.content[0].isalnum() and not CUSTOM_EMOJI_RE.match(message.content):
            return

        prefixes = await self.bot.get_valid_prefixes(message.guild)
        if any(message.content.startswith(prefix) for prefix in prefixes):
            return

        guild_data = await self.config.guild(message.guild).all()
        if not guild_data["enabled"]:
            return
        if message.channel.id in guild_data["ignored_channels"]:
            return

        content = message.content.strip()
        if len(content) >= guild_data["min_length"]:
            lowered = content.lower()
            if not any(word in lowered for word in guild_data["blacklist"]):
                async with self.config.guild(message.guild).messages() as messages:
                    messages.append(content)
                    max_messages = guild_data["max_messages"]
                    if max_messages is not None and len(messages) > max_messages:
                        del messages[: len(messages) - max_messages]

        if guild_data["messages"] and random.randint(1, 100) <= guild_data["frequency"]:
            reply = random.choice(guild_data["messages"])
            allowed_mentions = discord.AllowedMentions(
                everyone=False,
                roles=False,
                users=guild_data["ping_users"],
            )
            try:
                await message.channel.send(reply, allowed_mentions=allowed_mentions)
            except discord.Forbidden:
                pass
