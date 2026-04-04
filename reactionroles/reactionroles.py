# reactionroles/reactionroles.py
import logging
import typing
import discord
from redbot.core import checks, commands, Config
from redbot.core.bot import Red
from redbot.core.i18n import Translator
from redbot.core.utils.chat_formatting import pagify

from .dashboard import DashboardIntegration  # type: ignore

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
        self.logger = logging.getLogger("red.reactionroles")
        self.config = Config.get_conf(self, identifier=0xA1B2C3D4E6, force_registration=True)
        default_guild = {"messages": {}}
        self.config.register_guild(**default_guild)
        # keep a single dashboard integration instance so the same object is registered
        self._dashboard_integration: typing.Optional[DashboardIntegration] = None

    # ---------- Dashboard registration ----------
    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        """
        Called when the dashboard cog is added. Register our dashboard integration instance
        with the dashboard third_parties handler so the integration appears under Third Parties.
        """
        try:
            inst = self.dashboard
            # ensure the integration has a reference to the bot and the cog
            inst.bot = self.bot
            inst.cog = self
            # register with the dashboard
            dashboard_cog.rpc.third_parties_handler.add_third_party(inst)
        except Exception:
            self.logger.exception("Failed to register ReactionRoles dashboard integration")

    # ---------- Events ----------
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
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
        async with self.config.guild(ctx.guild).all() as guild_conf:
            messages = guild_conf.get("messages", {})
            if str(message_id) not in messages:
                await ctx.send(_("Message ID not registered."))
                return
            messages.pop(str(message_id), None)
            guild_conf["messages"] = messages
        await ctx.send(_("Message {id} removed from reaction-role management.").format(id=message_id))

    # ---------- Dashboard integration exposure ----------
    @property
    def dashboard(self) -> DashboardIntegration:
        """
        Return a single DashboardIntegration instance (create if needed).
        The dashboard cog expects the same object to be registered as a third party.
        """
        if self._dashboard_integration is None:
            inst = DashboardIntegration()
            inst.bot = self.bot
            inst.cog = self
            self._dashboard_integration = inst
        return self._dashboard_integration
