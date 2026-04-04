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
log = logging.getLogger("red.reactionroles")


def emoji_to_key(emoji: typing.Union[discord.PartialEmoji, discord.Emoji, str]) -> str:
    if isinstance(emoji, (discord.PartialEmoji, discord.Emoji)):
        if getattr(emoji, "id", None):
            return f"<:{emoji.name}:{emoji.id}>"
        return str(emoji)
    return str(emoji)


class ReactionRoles(commands.Cog):
    """Reaction role manager (admin only)."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.logger = log
        self.config = Config.get_conf(self, identifier=0xA1B2C3D4E7, force_registration=True)
        self.config.register_guild(messages={})
        self._dashboard_integration: typing.Optional[DashboardIntegration] = None

    # ---------------- internal handler helpers ----------------
    def _is_registered_in_handler(self, handler, inst) -> bool:
        try:
            for attr in ("third_parties", "_third_parties", "registered", "_registered", "third_parties_list"):
                val = getattr(handler, attr, None)
                if not val:
                    continue
                if isinstance(val, dict):
                    if inst in val.values() or getattr(inst, "name", None) in val:
                        return True
                if isinstance(val, (list, tuple, set)):
                    for item in val:
                        if item is inst:
                            return True
                        if isinstance(item, dict) and item.get("object") is inst:
                            return True
            if hasattr(handler, "list_third_parties"):
                try:
                    listed = handler.list_third_parties()
                    if listed:
                        for item in listed:
                            if item is inst:
                                return True
                            if isinstance(item, dict) and item.get("object") is inst:
                                return True
                except Exception:
                    pass
        except Exception:
            return False
        return False

    def _force_register_in_handler(self, handler, inst) -> bool:
        try:
            name = getattr(inst, "name", None) or getattr(inst, "__class__", type(inst)).__name__
            for attr in ("third_parties", "_third_parties", "registered", "_registered"):
                val = getattr(handler, attr, None)
                if isinstance(val, dict):
                    try:
                        val[name] = inst
                        return True
                    except Exception:
                        pass
                if isinstance(val, list):
                    try:
                        if inst not in val:
                            val.append(inst)
                        return True
                    except Exception:
                        pass
            for attr in ("_third_parties", "third_parties"):
                val = getattr(handler, attr, None)
                if isinstance(val, list):
                    try:
                        if inst not in val:
                            val.append(inst)
                        return True
                    except Exception:
                        pass
            for method_name in ("add_third_party", "register_third_party", "register", "add"):
                method = getattr(handler, method_name, None)
                if callable(method):
                    try:
                        try:
                            method(inst)
                        except TypeError:
                            try:
                                method(name, inst)
                            except Exception:
                                method(inst)
                        if self._is_registered_in_handler(handler, inst):
                            return True
                    except Exception:
                        pass
            try:
                if not hasattr(handler, "_third_parties_custom"):
                    setattr(handler, "_third_parties_custom", [])
                custom = getattr(handler, "_third_parties_custom")
                if isinstance(custom, list) and inst not in custom:
                    custom.append(inst)
                    return True
            except Exception:
                pass
        except Exception:
            pass
        return False

    async def _register_with_dashboard_handler(self, dashboard_cog: commands.Cog) -> bool:
        handler = getattr(dashboard_cog.rpc, "third_parties_handler", None)
        if handler is None:
            return False
        inst = self.dashboard
        inst.bot = self.bot
        inst.cog = self

        try:
            if hasattr(handler, "add_third_party"):
                try:
                    handler.add_third_party(inst)
                except TypeError:
                    try:
                        handler.add_third_party(getattr(inst, "name", None) or inst.__class__.__name__, inst)
                    except Exception:
                        pass
        except Exception:
            self.logger.debug("ReactionRoles: add_third_party call raised an exception (continuing to fallbacks).")

        if self._is_registered_in_handler(handler, inst):
            return True

        try:
            if self._force_register_in_handler(handler, inst):
                if self._is_registered_in_handler(handler, inst):
                    return True
        except Exception:
            pass

        return self._is_registered_in_handler(handler, inst)

    # ---------------- lifecycle hooks ----------------
    async def cog_load(self) -> None:
        try:
            dashboard_cog = self.bot.get_cog("Dashboard")
            if dashboard_cog:
                ok = await self._register_with_dashboard_handler(dashboard_cog)
                if ok:
                    self.logger.info("ReactionRoles: dashboard integration registered during cog_load.")
                else:
                    self.logger.debug("ReactionRoles: dashboard integration NOT registered during cog_load.")
        except Exception:
            self.logger.exception("ReactionRoles: unexpected error in cog_load while registering dashboard integration.")

    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        try:
            ok = await self._register_with_dashboard_handler(dashboard_cog)
            if ok:
                self.logger.info("ReactionRoles: dashboard integration registered via on_dashboard_cog_add.")
            else:
                self.logger.debug("ReactionRoles: dashboard integration NOT registered via on_dashboard_cog_add.")
        except Exception:
            self.logger.exception("ReactionRoles: failed to register dashboard integration via event")

    # ---------------- debug/status commands ----------------
    @commands.command(name="reactionroles-dashboardstatus")
    @checks.admin_or_permissions(manage_guild=True)
    async def dashboard_status(self, ctx: commands.Context):
        """Show dashboard registration status (debug)."""
        lines = []
        dashboard_cog = self.bot.get_cog("Dashboard")
        lines.append(f"Dashboard cog loaded: {bool(dashboard_cog)}")
        if not dashboard_cog:
            await ctx.send("\n".join(lines))
            return

        handler = getattr(dashboard_cog.rpc, "third_parties_handler", None)
        lines.append(f"third_parties_handler present: {bool(handler)}")
        if not handler:
            await ctx.send("\n".join(lines))
            return

        registered = None
        try:
            registered = getattr(handler, "third_parties", None)
            if registered is None:
                registered = getattr(handler, "_third_parties", None)
            if registered is None and hasattr(handler, "list_third_parties"):
                try:
                    registered = handler.list_third_parties()
                except Exception:
                    registered = None
        except Exception as e:
            lines.append(f"error accessing handler internals: {e}")

        objs = []
        if registered:
            if isinstance(registered, dict):
                for k, v in registered.items():
                    if isinstance(v, dict) and "object" in v:
                        objs.append(v["object"])
                    else:
                        objs.append(v)
            elif isinstance(registered, (list, tuple, set)):
                for item in registered:
                    if isinstance(item, dict) and "object" in item:
                        objs.append(item["object"])
                    else:
                        objs.append(item)
            else:
                objs.append(registered)
        else:
            for attr in ("_third_parties", "third_parties", "registered", "_registered"):
                val = getattr(handler, attr, None)
                if val:
                    if isinstance(val, (list, tuple, set)):
                        objs.extend(val)
                    elif isinstance(val, dict):
                        objs.extend(val.values())
                    else:
                        objs.append(val)

        def is_integration_candidate(o):
            try:
                for attr in dir(o):
                    obj = getattr(o, attr, None)
                    if hasattr(obj, "__dashboard_decorator_params__"):
                        return True
            except Exception:
                return False
            return False

        inst = self.dashboard
        present_identity = any(o is inst for o in objs)
        present_candidate = any(is_integration_candidate(o) for o in objs)
        candidate_names = [getattr(o, "name", getattr(o, "__class__", type(o)).__name__) for o in objs if is_integration_candidate(o)]

        lines.append(f"our integration instance registered (identity): {present_identity}")
        lines.append(f"any integration-like object registered (decorated pages): {present_candidate}")
        lines.append(f"integration-like registered names (sample up to 10): {candidate_names[:10]}")

        pages = []
        try:
            for attr in dir(inst):
                obj = getattr(inst, attr)
                if hasattr(obj, "__dashboard_decorator_params__"):
                    pages.append(f"{attr}: {getattr(obj,'__dashboard_decorator_params__')}")
        except Exception as e:
            pages.append(f"error enumerating pages: {e}")

        lines.append(f"decorated pages found on our instance: {len(pages)}")
        lines.extend(pages[:20])

        await ctx.send("\n".join(lines))

    @commands.command(name="reactionroles-dashboarddump")
    @checks.is_owner()
    async def dashboard_dump(self, ctx: commands.Context):
        """Dump raw third_parties_handler internals for debugging."""
        dashboard_cog = self.bot.get_cog("Dashboard")
        if not dashboard_cog:
            return await ctx.send("Dashboard cog not loaded.")
        handler = getattr(dashboard_cog.rpc, "third_parties_handler", None)
        if not handler:
            return await ctx.send("third_parties_handler not present.")
        out = []
        for attr in ("third_parties", "_third_parties", "registered", "_registered", "third_parties_list"):
            val = getattr(handler, attr, None)
            out.append(f"{attr}: {type(val).__name__} -> {repr(val)[:1000]}")
        if hasattr(handler, "list_third_parties"):
            try:
                listed = handler.list_third_parties()
                out.append(f"list_third_parties(): {type(listed).__name__} -> {repr(listed)[:1000]}")
            except Exception as e:
                out.append(f"list_third_parties() raised: {e}")
        # send in chunks if too long
        text = "\n".join(out)
        if len(text) <= 1900:
            await ctx.send(f"```\n{text}\n```")
        else:
            for i in range(0, len(text), 1900):
                await ctx.send(f"```\n{text[i:i+1900]}\n```")

    # ---------------- Events ----------------
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

    # ---------------- Commands (core) ----------------
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
            await ctx.send("I cannot send messages in that channel.")
            return
        try:
            msg = await channel.send(content)
        except Exception as e:
            await ctx.send(f"Failed to send message: {e}")
            return
        async with self.config.guild(ctx.guild).all() as guild_conf:
            messages = guild_conf.get("messages", {})
            messages[str(msg.id)] = {"channel": channel.id, "mappings": {}}
            guild_conf["messages"] = messages
        await ctx.send(f"Message sent and registered for reaction roles: {msg.id}")

    @reactionroles.command(name="add")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def rr_add(self, ctx: commands.Context, message_id: int, emoji: str, role: discord.Role):
        guild_conf = await self.config.guild(ctx.guild).all()
        messages = guild_conf.get("messages", {})

        msg_conf = messages.get(str(message_id))
        message = None
        if msg_conf:
            channel = ctx.guild.get_channel(msg_conf["channel"])
            if channel:
                try:
                    message = await channel.fetch_message(message_id)
                except Exception:
                    message = None
        if message is None:
            for ch in ctx.guild.text_channels:
                if ch.permissions_for(ctx.guild.me).read_messages and ch.permissions_for(ctx.guild.me).read_message_history:
                    try:
                        message = await ch.fetch_message(message_id)
                        async with self.config.guild(ctx.guild).all() as guild_conf:
                            messages = guild_conf.get("messages", {})
                            messages[str(message.id)] = {"channel": ch.id, "mappings": {}}
                            guild_conf["messages"] = messages
                        break
                    except Exception:
                        continue
        if message is None:
            await ctx.send("Could not find that message in this guild.")
            return

        async with self.config.guild(ctx.guild).all() as guild_conf:
            messages = guild_conf.get("messages", {})
            msg_conf = messages.get(str(message.id), {"channel": message.channel.id, "mappings": {}})
            current_mappings = msg_conf.get("mappings", {})
            if len(current_mappings) >= 20:
                await ctx.send("A message can have no more than 20 reaction-role mappings.")
                return

        try:
            parsed = discord.PartialEmoji.from_str(emoji)
        except Exception:
            parsed = emoji

        emoji_key = emoji_to_key(parsed)
        if emoji_key in current_mappings:
            await ctx.send("That emoji is already mapped to a role for this message.")
            return

        try:
            await message.add_reaction(parsed)
        except Exception as e:
            await ctx.send(f"Failed to add reaction to message: {e}")
            return

        async with self.config.guild(ctx.guild).all() as guild_conf:
            messages = guild_conf.get("messages", {})
            messages[str(message.id)]["mappings"][emoji_key] = role.id
            guild_conf["messages"] = messages

        await ctx.send(f"Mapping added: {emoji_key} -> {role.mention}")

    @reactionroles.command(name="remove")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def rr_remove(self, ctx: commands.Context, message_id: int, emoji: str):
        guild_conf = await self.config.guild(ctx.guild).all()
        messages = guild_conf.get("messages", {})
        msg_conf = messages.get(str(message_id))
        if not msg_conf:
            await ctx.send("Message ID not registered.")
            return

        try:
            parsed = discord.PartialEmoji.from_str(emoji)
        except Exception:
            parsed = emoji
        emoji_key = emoji_to_key(parsed)

        if emoji_key not in msg_conf.get("mappings", {}):
            await ctx.send("That emoji is not mapped for this message.")
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

        await ctx.send(f"Mapping removed: {emoji_key}")

    @reactionroles.command(name="list")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def rr_list(self, ctx: commands.Context, message_id: int = None):
        guild_conf = await self.config.guild(ctx.guild).all()
        messages = guild_conf.get("messages", {})

        if message_id is None:
            if not messages:
                await ctx.send("No reaction-role messages registered in this guild.")
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
            await ctx.send("Message ID not registered.")
            return
        mappings = msg_conf.get("mappings", {})
        if not mappings:
            await ctx.send("No mappings for that message.")
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
            await ctx.send("Message ID not registered.")
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

        await ctx.send(f"All mappings cleared for message {message_id}")

    @reactionroles.command(name="delete")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def rr_delete(self, ctx: commands.Context, message_id: int):
        async with self.config.guild(ctx.guild).all() as guild_conf:
            messages = guild_conf.get("messages", {})
            if str(message_id) not in messages:
                await ctx.send("Message ID not registered.")
                return
            messages.pop(str(message_id), None)
            guild_conf["messages"] = messages
        await ctx.send(f"Message {message_id} removed from reaction-role management.")

    # ---------------- Dashboard integration exposure ----------------
    @property
    def dashboard(self) -> DashboardIntegration:
        if self._dashboard_integration is None:
            inst = DashboardIntegration()
            inst.bot = self.bot
            inst.cog = self
            self._dashboard_integration = inst
        return self._dashboard_integration
