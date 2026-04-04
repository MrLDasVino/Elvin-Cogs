from redbot.core import commands, checks, Config
from redbot.core.bot import Red
from redbot.core.i18n import Translator
import discord
import typing
import os
from redbot.core.utils.chat_formatting import pagify, humanize_list

_ = Translator("ReactionRoles", __file__)


def emoji_to_key(emoji: typing.Union[discord.PartialEmoji, discord.Emoji, str]) -> str:
    """Normalize an emoji to a stable string key for storage."""
    if isinstance(emoji, (discord.PartialEmoji, discord.Emoji)):
        if getattr(emoji, "id", None):
            return f"<:{emoji.name}:{emoji.id}>"
        return str(emoji)
    return str(emoji)


class ReactionRoles(commands.Cog):
    """Manage reaction role messages (send or attach to existing message). Admin commands only."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xA1B2C3D4E6, force_registration=True)
        default_guild = {"messages": {}}  # message_id -> {"channel": channel_id, "mappings": {emoji_key: role_id}}
        self.config.register_guild(**default_guild)
        self.logger = bot.logger

    # ---------- Events ----------
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # Ignore bot reactions
        if payload.user_id == self.bot.user.id:
            return
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        if not guild:
            return
        guild_conf = await self.config.guild(guild).all()
        messages = guild_conf.get("messages", {})
        msg_conf = messages.get(str(payload.message_id))
        if not msg_conf:
            return
        emoji_key = emoji_to_key(payload.emoji)
        role_id = msg_conf.get("mappings", {}).get(emoji_key)
        if not role_id:
            return
        member = guild.get_member(payload.user_id)
        if not member:
            try:
                member = await guild.fetch_member(payload.user_id)
            except Exception:
                return
        role = guild.get_role(role_id)
        if not role:
            return
        try:
            await member.add_roles(role, reason="Reaction role (add)")
        except Exception:
            return

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        if not guild:
            return
        guild_conf = await self.config.guild(guild).all()
        messages = guild_conf.get("messages", {})
        msg_conf = messages.get(str(payload.message_id))
        if not msg_conf:
            return
        emoji_key = emoji_to_key(payload.emoji)
        role_id = msg_conf.get("mappings", {}).get(emoji_key)
        if not role_id:
            return
        try:
            member = guild.get_member(payload.user_id)
            if not member:
                member = await guild.fetch_member(payload.user_id)
        except Exception:
            return
        role = guild.get_role(role_id)
        if not role:
            return
        try:
            await member.remove_roles(role, reason="Reaction role (remove)")
        except Exception:
            return

    # ---------- Commands ----------
    @commands.group(name="reactionroles", invoke_without_command=True)
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def reactionroles(self, ctx: commands.Context):
        """Main group for reaction role management. Use subcommands."""
        await ctx.send_help(ctx.command)

    @reactionroles.command(name="send")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def rr_send(self, ctx: commands.Context, channel: discord.TextChannel, *, content: str):
        """
        Send a new message to a channel and register it for reaction roles.

        Example: [p]reactionroles send #roles React below to get roles!
        """
        if not channel.permissions_for(ctx.guild.me).send_messages:
            await ctx.send(_("I cannot send messages in that channel."))
            return
        try:
            msg = await channel.send(content)
        except Exception as e:
            await ctx.send(_("Failed to send message: {err}").format(err=str(e)))
            return
        async with self.config.guild(ctx.guild).all() as guild_conf:
            messages = guild_conf.get("messages", {})
            messages[str(msg.id)] = {"channel": channel.id, "mappings": {}}
            guild_conf["messages"] = messages
        await ctx.send(_("Message sent and registered for reaction roles: {id}").format(id=msg.id))

    @reactionroles.command(name="attach")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def rr_attach(self, ctx: commands.Context, channel: discord.TextChannel, message_id: int):
        """
        Attach to an existing message by ID in the provided channel.

        Example: [p]reactionroles attach #roles 123456789012345678
        """
        try:
            msg = await channel.fetch_message(message_id)
        except Exception as e:
            await ctx.send(_("Could not fetch message: {err}").format(err=str(e)))
            return
        async with self.config.guild(ctx.guild).all() as guild_conf:
            messages = guild_conf.get("messages", {})
            if str(msg.id) in messages:
                await ctx.send(_("That message is already registered."))
                return
            messages[str(msg.id)] = {"channel": channel.id, "mappings": {}}
            guild_conf["messages"] = messages
        await ctx.send(_("Message attached for reaction roles: {id}").format(id=msg.id))

    @reactionroles.command(name="add")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def rr_add(self, ctx: commands.Context, message_id: int, emoji: str, role: discord.Role):
        """
        Add a reaction-role mapping to a registered message.

        emoji can be a unicode emoji or a custom emoji like <:name:id>.
        Example: [p]reactionroles add 123456789012345678 👍 @MemberRole
        """
        guild_conf = await self.config.guild(ctx.guild).all()
        messages = guild_conf.get("messages", {})
        msg_conf = messages.get(str(message_id))
        if not msg_conf:
            await ctx.send(_("Message ID not registered. Use reactionroles send or attach first."))
            return

        current_mappings = msg_conf.get("mappings", {})
        if len(current_mappings) >= 20:
            await ctx.send(_("A message can have no more than 20 reaction-role mappings."))
            return

        try:
            parsed = discord.PartialEmoji.from_str(emoji)
        except Exception:
            parsed = emoji

        emoji_key = emoji_to_key(parsed)

        if emoji_key in current_mappings:
            await ctx.send(_("That emoji is already mapped to a role for this message."))
            return

        channel = ctx.guild.get_channel(msg_conf["channel"])
        if not channel:
            await ctx.send(_("I cannot find the channel for that message."))
            return
        try:
            message = await channel.fetch_message(message_id)
        except Exception as e:
            await ctx.send(_("Could not fetch message: {err}").format(err=str(e)))
            return

        try:
            await message.add_reaction(parsed)
        except Exception as e:
            await ctx.send(_("Failed to add reaction to message: {err}").format(err=str(e)))
            return

        async with self.config.guild(ctx.guild).all() as guild_conf:
            messages = guild_conf.get("messages", {})
            messages[str(message_id)]["mappings"][emoji_key] = role.id
            guild_conf["messages"] = messages

        await ctx.send(_("Mapping added: {emoji} -> {role}").format(emoji=emoji_key, role=role.mention))

    @reactionroles.command(name="remove")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def rr_remove(self, ctx: commands.Context, message_id: int, emoji: str):
        """
        Remove a reaction-role mapping from a registered message.

        Example: [p]reactionroles remove 123456789012345678 👍
        """
        guild_conf = await self.config.guild(ctx.guild).all()
        messages = guild_conf.get("messages", {})
        msg_conf = messages.get(str(message_id))
        if not msg_conf:
            await ctx.send(_("Message ID not registered."))
            return

        try:
            parsed = discord.PartialEmoji.from_str(emoji)
        except Exception:
            parsed = emoji
        emoji_key = emoji_to_key(parsed)

        if emoji_key not in msg_conf.get("mappings", {}):
            await ctx.send(_("That emoji is not mapped for this message."))
            return

        channel = ctx.guild.get_channel(msg_conf["channel"])
        if channel:
            try:
                message = await channel.fetch_message(message_id)
                for react in message.reactions:
                    if emoji_to_key(react.emoji) == emoji_key:
                        try:
                            await message.clear_reaction(react.emoji)
                        except Exception:
                            pass
                        break
            except Exception:
                pass

        async with self.config.guild(ctx.guild).all() as guild_conf:
            messages = guild_conf.get("messages", {})
            messages[str(message_id)]["mappings"].pop(emoji_key, None)
            guild_conf["messages"] = messages

        await ctx.send(_("Mapping removed: {emoji}").format(emoji=emoji_key))

    @reactionroles.command(name="list")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def rr_list(self, ctx: commands.Context, message_id: int = None):
        """
        List reaction-role mappings.

        If message_id is omitted, lists all registered messages in the guild.
        """
        guild_conf = await self.config.guild(ctx.guild).all()
        messages = guild_conf.get("messages", {})

        if message_id is None:
            if not messages:
                await ctx.send(_("No reaction-role messages registered in this guild."))
                return
            lines = []
            for mid, info in messages.items():
                ch = ctx.guild.get_channel(info.get("channel"))
                mappings = info.get("mappings", {})
                lines.append(f"**Message ID:** {mid} — Channel: {ch.mention if ch else info.get('channel')} — Mappings: {len(mappings)}")
            await ctx.send("\n".join(lines))
            return

        msg_conf = messages.get(str(message_id))
        if not msg_conf:
            await ctx.send(_("Message ID not registered."))
            return
        mappings = msg_conf.get("mappings", {})
        if not mappings:
            await ctx.send(_("No mappings for that message."))
            return
        lines = []
        for emoji_key, role_id in mappings.items():
            role = ctx.guild.get_role(role_id)
            lines.append(f"{emoji_key} -> {role.mention if role else role_id}")
        for page in pagify("\n".join(lines), delims=["\n"], shorten_by=12):
            await ctx.send(page)

    @reactionroles.command(name="clear")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def rr_clear(self, ctx: commands.Context, message_id: int):
        """
        Clear all mappings for a registered message and remove the bot's reactions.

        Example: [p]reactionroles clear 123456789012345678
        """
        guild_conf = await self.config.guild(ctx.guild).all()
        messages = guild_conf.get("messages", {})
        msg_conf = messages.get(str(message_id))
        if not msg_conf:
            await ctx.send(_("Message ID not registered."))
            return

        channel = ctx.guild.get_channel(msg_conf["channel"])
        if channel:
            try:
                message = await channel.fetch_message(message_id)
                try:
                    await message.clear_reactions()
                except Exception:
                    for react in message.reactions:
                        try:
                            await message.clear_reaction(react.emoji)
                        except Exception:
                            pass
            except Exception:
                pass

        async with self.config.guild(ctx.guild).all() as guild_conf:
            messages = guild_conf.get("messages", {})
            messages[str(message_id)]["mappings"] = {}
            guild_conf["messages"] = messages

        await ctx.send(_("All mappings cleared for message {id}").format(id=message_id))

    @reactionroles.command(name="delete")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def rr_delete(self, ctx: commands.Context, message_id: int):
        """
        Remove a message from reaction-role management (does not delete the message).

        Example: [p]reactionroles delete 123456789012345678
        """
        async with self.config.guild(ctx.guild).all() as guild_conf:
            messages = guild_conf.get("messages", {})
            if str(message_id) not in messages:
                await ctx.send(_("Message ID not registered."))
                return
            messages.pop(str(message_id), None)
            guild_conf["messages"] = messages
        await ctx.send(_("Message {id} removed from reaction-role management.").format(id=message_id))

    # ---------- Dashboard integration ----------
    def dashboard_page(self, *args, **kwargs):
        def decorator(func: typing.Callable):
            func.__dashboard_decorator_params__ = (args, kwargs)
            return func
        return decorator

    class DashboardIntegration:
        bot: Red

        @commands.Cog.listener()
        async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
            dashboard_cog.rpc.third_parties_handler.add_third_party(self)

        @staticmethod
        def _read_file(name: str) -> str:
            file_path = os.path.join(os.path.dirname(__file__), name)
            with open(file_path, "rt", encoding="utf-8") as f:
                return f.read()

        @property
        def logger(self):
            return self.bot.logger

        async def _get_hook(self, channel: discord.TextChannel) -> typing.Optional[discord.Webhook]:
            """
            Try to find an existing webhook the bot can use in the channel, or create one.
            Returns a discord.Webhook object or None if not possible.
            """
            try:
                webhooks = await channel.webhooks()
                for wh in webhooks:
                    if wh.user and wh.user.id == self.bot.user.id:
                        return wh
                # create a webhook if we have permission
                if channel.permissions_for(channel.guild.me).manage_webhooks:
                    return await channel.create_webhook(name=f"{channel.guild.me.display_name}-rr")
            except Exception:
                return None
            return None

        @ReactionRoles.dashboard_page(name=None, description="Reaction Roles editor")
        async def dashboard_editor(self, **kwargs) -> None:
            source = self._read_file("editor.html")
            return {"status": 0, "web_content": {"source": source, "standalone": True}}

        @ReactionRoles.dashboard_page(
            name="guild",
            description="Create or manage reaction roles for a guild",
            methods=("GET", "POST"),
        )
        async def dashboard_guild(self, user: discord.User, guild: discord.Guild, **kwargs) -> None:
            is_owner = user.id in self.bot.owner_ids
            member = guild.get_member(user.id)
            if not is_owner and not await self.bot.is_mod(member):
                return {
                    "status": 0,
                    "error_code": 403,
                    "message": _("You don't have permissions to access this page."),
                }
            channels = kwargs["get_sorted_channels"](guild)
            if not channels:
                return {
                    "status": 0,
                    "error_code": 403,
                    "message": _(
                        "I or you don't have permissions to send messages or embeds in any channel in this guild."
                    ),
                }

            source = self._read_file("editor.html")

            import wtforms

            class SendForm(kwargs["Form"]):
                def __init__(self) -> None:
                    super().__init__(prefix="send_form_")

                channel: wtforms.SelectField = wtforms.SelectField(
                    _("Channel:"),
                    choices=[],
                    validators=[wtforms.validators.DataRequired()],
                )
                message_id: wtforms.StringField = wtforms.StringField(
                    _("Message ID (optional to attach)"),
                    validators=[wtforms.validators.Optional()],
                )
                content: wtforms.TextAreaField = wtforms.TextAreaField(
                    _("Message content (if sending new message)"),
                    validators=[wtforms.validators.Optional()],
                )
                emoji: wtforms.StringField = wtforms.StringField(
                    _("Emoji"),
                    validators=[wtforms.validators.DataRequired(), wtforms.validators.Length(max=64)],
                )
                role: wtforms.SelectField = wtforms.SelectField(
                    _("Role"),
                    choices=[],
                    validators=[wtforms.validators.DataRequired()],
                )
                submit = wtforms.SubmitField(_("Submit"))

            send_form: SendForm = SendForm()
            send_form.channel.choices = channels
            roles_choices = [(str(r.id), r.name) for r in guild.roles if not r.is_default()]
            send_form.role.choices = roles_choices

            send_form_string = f"""
                <form action="" method="POST" role="form" enctype="multipart/form-data">
                    {send_form.hidden_tag()}
                    <label>Channel</label>
                    {send_form.channel()}
                    <label>Message ID (leave empty to send new message)</label>
                    {send_form.message_id()}
                    <label>Message content (if sending new message)</label>
                    {send_form.content()}
                    <label>Emoji (unicode or custom like &lt;:name:id&gt;)</label>
                    {send_form.emoji()}
                    <label>Role</label>
                    {send_form.role()}
                    {send_form.submit()}
                </form>
            """

            if send_form.validate_on_submit():
                channel_id = int(send_form.channel.data)
                channel = guild.get_channel(channel_id)
                if not channel:
                    return {"status": 0, "error_code": 400, "message": _("Invalid channel.")}

                message_id = send_form.message_id.data.strip()
                content = send_form.content.data.strip()
                emoji = send_form.emoji.data.strip()
                role_id = int(send_form.role.data)

                notifications = []
                try:
                    if message_id:
                        try:
                            message = await channel.fetch_message(int(message_id))
                        except Exception as e:
                            notifications.append({"message": str(e), "category": "danger"})
                            return {"status": 0, "notifications": notifications}
                        async with self.bot.get_cog("ReactionRoles").config.guild(guild).all() as guild_conf:
                            messages = guild_conf.get("messages", {})
                            messages[str(message.id)] = {"channel": channel.id, "mappings": {}}
                            guild_conf["messages"] = messages
                    else:
                        if not content:
                            notifications.append({"message": _("No content provided."), "category": "danger"})
                            return {"status": 0, "notifications": notifications}
                        message = await channel.send(content)
                        async with self.bot.get_cog("ReactionRoles").config.guild(guild).all() as guild_conf:
                            messages = guild_conf.get("messages", {})
                            messages[str(message.id)] = {"channel": channel.id, "mappings": {}}
                            guild_conf["messages"] = messages

                    # add reaction and mapping
                    try:
                        parsed = discord.PartialEmoji.from_str(emoji)
                    except Exception:
                        parsed = emoji
                    await message.add_reaction(parsed)

                    async with self.bot.get_cog("ReactionRoles").config.guild(guild).all() as guild_conf:
                        messages = guild_conf.get("messages", {})
                        messages[str(message.id)]["mappings"][emoji_to_key(parsed)] = role_id
                        guild_conf["messages"] = messages

                    notifications.append({"message": _("Success."), "category": "success"})
                except Exception as e:
                    notifications.append({"message": str(e), "category": "danger"})
                return {"status": 0, "notifications": notifications, "redirect_url": kwargs["request_url"]}

            return {
                "status": 0,
                "web_content": {"source": source, "standalone": True, "send_form": send_form_string},
            }

    @property
    def dashboard(self):
        inst = ReactionRoles.DashboardIntegration()
        inst.bot = self.bot
        return inst
