# reactionroles/dashboard.py
from redbot.core import commands  # isort:skip
from redbot.core.bot import Red  # isort:skip
from redbot.core.i18n import Translator  # isort:skip
import discord  # isort:skip
import typing  # isort:skip
import os

_ = Translator("ReactionRoles", __file__)


def dashboard_page(*args, **kwargs):
    def decorator(func: typing.Callable):
        func.__dashboard_decorator_params__ = (args, kwargs)
        return func

    return decorator


class DashboardIntegration:
    """
    Dashboard integration for the Red web dashboard.

    This class follows the example in the official docs:
    - It exposes methods decorated with @dashboard_page
    - It registers itself with the dashboard's third_parties_handler when the dashboard cog is added
    """

    bot: Red
    # `cog` will be set by the ReactionRoles cog when exposing the integration instance
    cog: typing.Any

    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        """
        Called by the dashboard cog when it is added. Register this integration instance
        with the dashboard third_parties handler so it appears under Third Parties.
        """
        try:
            dashboard_cog.rpc.third_parties_handler.add_third_party(self)
        except Exception:
            # avoid raising during load; the cog's logger will capture issues
            if hasattr(self.bot, "logger"):
                try:
                    self.bot.logger.exception("Failed to register ReactionRoles dashboard integration")
                except Exception:
                    pass

    @staticmethod
    def _read_file(name: str) -> str:
        file_path = os.path.join(os.path.dirname(__file__), name)
        with open(file_path, "rt", encoding="utf-8") as f:
            return f.read()

    @dashboard_page(name=None, description="Reaction Roles editor")
    async def dashboard_editor(self, **kwargs) -> None:
        file_path = os.path.join(os.path.dirname(__file__), "editor.html")
        with open(file_path, "rt", encoding="utf-8") as f:
            source = f.read()
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

        file_path = os.path.join(os.path.dirname(__file__), "editor.html")
        with open(file_path, "rt", encoding="utf-8") as f:
            source = f.read()

        import wtforms

        class SendForm(kwargs["Form"]):
            def __init__(self) -> None:
                super().__init__(prefix="send_form_")

            username: wtforms.HiddenField = wtforms.HiddenField(
                _("Username:"),
                validators=[wtforms.validators.Optional(), wtforms.validators.Length(max=80)],
            )
            avatar: wtforms.HiddenField = wtforms.HiddenField(
                _("Avatar URL:"),
                validators=[wtforms.validators.Optional(), wtforms.validators.URL()],
            )
            data: wtforms.HiddenField = wtforms.HiddenField(
                _("Data"),
                validators=[
                    wtforms.validators.DataRequired(),
                    # keep converter usage optional; dashboard will provide DpyObjectConverter in kwargs
                    kwargs["DpyObjectConverter"](typing.Any),
                ],
            )
            channels: wtforms.SelectMultipleField = wtforms.SelectMultipleField(
                _("Channels:"),
                choices=[],
                validators=[
                    wtforms.validators.DataRequired(),
                    kwargs["DpyObjectConverter"](typing.Union[discord.TextChannel, discord.VoiceChannel]),
                ],
            )
            submit = wtforms.SubmitField(_("Send Message(s)"))

        send_form: SendForm = SendForm()
        send_form.channels.choices = channels
        send_form_string = f"""
            <form action="" method="POST" role="form" enctype="multipart/form-data">
                {send_form.hidden_tag()}
                {send_form.channels() }
                {send_form.submit(onclick='this.parentElement.querySelector("#send_form_username").value = document.querySelector(".editSenderUsername").value; this.parentElement.querySelector("#send_form_avatar").value = document.querySelector(".editSenderAvatar").value; this.parentElement.querySelector("#send_form_data").value = (JSON.stringify(typeof jsonCode === "object" ? jsonCode : json));', style="cursor: pointer; margin-left: 105px;") }
            </form>
        """

        # validate_dpy_converters is provided by the dashboard; check both conditions like the example
        if send_form.validate_on_submit() and await send_form.validate_dpy_converters():
            notifications = []
            for channel in send_form.channels.data:
                # Use the same logic as the example to send via webhook or normal send
                if send_form.username.data or send_form.avatar.data:
                    if not channel.permissions_for(guild.me).manage_webhooks:
                        notifications.append(
                            {
                                "message": f"{channel.name} ({channel.id}): I don't have permissions to manage webhooks in this channel.",
                                "category": "danger",
                            }
                        )
                        continue
                    if not is_owner and not channel.permissions_for(member).manage_webhooks:
                        notifications.append(
                            {
                                "message": f"{channel.name} ({channel.id}): You don't have permissions to manage webhooks in this channel.",
                                "category": "danger",
                            }
                        )
                        continue
                    try:
                        # create or get a webhook owned by the bot
                        webhooks = await channel.webhooks()
                        hook = None
                        for wh in webhooks:
                            if wh.user and wh.user.id == self.bot.user.id:
                                hook = wh
                                break
                        if not hook and channel.permissions_for(guild.me).manage_webhooks:
                            hook = await channel.create_webhook(name=f"{guild.me.display_name}-dashboard")
                        if hook:
                            await hook.send(
                                **send_form.data.data,
                                username=send_form.username.data or guild.me.display_name,
                                avatar_url=send_form.avatar.data or guild.me.display_avatar,
                                wait=True,
                            )
                    except Exception as error:
                        notifications.append(
                            {
                                "message": f"{channel.name} ({channel.id}): {str(error)}",
                                "category": "danger",
                            }
                        )
                else:
                    try:
                        await channel.send(**send_form.data.data)
                    except Exception as e:
                        notifications.append(
                            {
                                "message": f"{channel.name} ({channel.id}): {str(e)}",
                                "category": "danger",
                            }
                        )
            s = "s" if len(send_form.channels.data) > 1 else ""
            # try to log via bot logger if available
            if hasattr(self.bot, "logger"):
                try:
                    self.bot.logger.trace(
                        f"{len(send_form.channels.data)} message{s} sent in {guild.name} ({guild.id}), from the Dashboard by {user.display_name} ({user.id})."
                    )
                except Exception:
                    pass
            if not notifications:
                notifications.append(
                    {
                        "message": _("Message{s} sent successfully!").format(s=s),
                        "category": "success",
                    }
                )
            return {
                "status": 0,
                "notifications": notifications,
                "redirect_url": kwargs["request_url"],
            }

        return {
            "status": 0,
            "web_content": {"source": source, "standalone": True, "send_form": send_form_string},
        }
