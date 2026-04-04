# reactionroles/dashboard.py
import os
import typing

import discord
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator

_ = Translator("ReactionRoles", __file__)


def dashboard_page(*args, **kwargs):
    """
    Module-level decorator used by the Red dashboard integration.
    Attaches decorator params to the function so the dashboard cog can discover pages.
    """
    def decorator(func: typing.Callable):
        func.__dashboard_decorator_params__ = (args, kwargs)
        return func
    return decorator


class DashboardIntegration:
    """
    Dashboard integration for the Red web dashboard.
    Methods are decorated with the module-level @dashboard_page decorator so the dashboard can discover them.
    The integration uses the cog via bot.get_cog("ReactionRoles") when needed.
    """

    bot: Red
    cog: typing.Any  # will be set by the cog when exposing the integration

    # NOTE: Do NOT use @commands.Cog.listener here. The dashboard cog will call
    # on_dashboard_cog_add on all loaded cogs; instead we register the third party
    # from the ReactionRoles cog's on_dashboard_cog_add listener (see reactionroles.py).
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        # This method is kept for compatibility but is not decorated as a listener.
        # The actual registration is performed by the ReactionRoles cog to ensure
        # the dashboard integration instance is the one registered.
        try:
            dashboard_cog.rpc.third_parties_handler.add_third_party(self)
        except Exception:
            # avoid raising; the cog's logger will capture issues
            return

    @staticmethod
    def _read_file(name: str) -> str:
        file_path = os.path.join(os.path.dirname(__file__), name)
        with open(file_path, "rt", encoding="utf-8") as f:
            return f.read()

    @property
    def logger(self):
        return getattr(self.bot, "logger", None)

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

    @dashboard_page(name=None, description="Reaction Roles editor")
    async def dashboard_editor(self, **kwargs) -> None:
        source = self._read_file("editor.html")
        return {"status": 0, "web_content": {"source": source, "standalone": True}}

    @dashboard_page(
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
                cog = self.bot.get_cog("ReactionRoles")
                if not cog:
                    notifications.append({"message": _("ReactionRoles cog not loaded."), "category": "danger"})
                    return {"status": 0, "notifications": notifications}

                if message_id:
                    try:
                        message = await channel.fetch_message(int(message_id))
                    except Exception as e:
                        notifications.append({"message": str(e), "category": "danger"})
                        return {"status": 0, "notifications": notifications}
                    async with cog.config.guild(guild).all() as guild_conf:
                        messages = guild_conf.get("messages", {})
                        messages[str(message.id)] = {"channel": channel.id, "mappings": {}}
                        guild_conf["messages"] = messages
                else:
                    if not content:
                        notifications.append({"message": _("No content provided."), "category": "danger"})
                        return {"status": 0, "notifications": notifications}
                    message = await channel.send(content)
                    async with cog.config.guild(guild).all() as guild_conf:
                        messages = guild_conf.get("messages", {})
                        messages[str(message.id)] = {"channel": channel.id, "mappings": {}}
                        guild_conf["messages"] = messages

                # add reaction and mapping
                try:
                    parsed = discord.PartialEmoji.from_str(emoji)
                except Exception:
                    parsed = emoji
                await message.add_reaction(parsed)

                async with cog.config.guild(guild).all() as guild_conf:
                    messages = guild_conf.get("messages", {})
                    messages[str(message.id)]["mappings"][emoji if isinstance(parsed, str) else f"<:{getattr(parsed,'name',parsed)}:{getattr(parsed,'id', '')}>"] = role_id
                    guild_conf["messages"] = messages

                notifications.append({"message": _("Success."), "category": "success"})
            except Exception as e:
                notifications.append({"message": str(e), "category": "danger"})
            return {"status": 0, "notifications": notifications, "redirect_url": kwargs["request_url"]}

        return {
            "status": 0,
            "web_content": {"source": source, "standalone": True, "send_form": send_form_string},
        }
