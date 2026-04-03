# reaction_roles.py
from typing import Optional, Dict, Any, List
import asyncio
import discord

from redbot.core import commands, Config, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify

# Dashboard integration helpers (adjust import paths if your environment differs)
# These are the typical names used in the Red Web Dashboard third-party docs:
try:
    from red_web_dashboard.api import dashboard_page, Form, DpyObjectConverter, add_third_party
except Exception:
    # Fallback: provide no-op placeholders so the cog file can still be loaded for testing.
    def dashboard_page(func):
        return func

    class Form(dict):
        pass

    class DpyObjectConverter:
        pass

    def add_third_party(name, pages):
        # In production, the dashboard will call your registration function.
        return None


DEFAULTS = {
    "reaction_messages": {}  # guild_id -> {message_id: {channel_id, mapping: {emoji: role_id}, author_id, content}}
}


class ReactionRoles(commands.Cog):
    """Reaction Roles manager with Red-Web-Dashboard integration."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xA1B2C3D4E5F60708, force_registration=True)
        self.config.register_global(**DEFAULTS)

    # -----------------------
    # Discord commands
    # -----------------------
    @commands.group()
    @checks.admin_or_permissions(manage_roles=True)
    async def reactionroles(self, ctx: commands.Context):
        """Reaction roles management commands."""
        pass

    @reactionroles.command(name="create")
    async def rr_create(self, ctx: commands.Context, channel: discord.TextChannel, *, content: str):
        """
        Create a reaction-role message in a channel.
        After creating, use `reactionroles add <message_id> <emoji> <role>` to add mappings.
        """
        if not channel.permissions_for(ctx.guild.me).send_messages:
            await ctx.send("I don't have permission to send messages in that channel.")
            return
        msg = await channel.send(content)
        guild_data = await self.config.reaction_messages()
        guild_id = str(ctx.guild.id)
        guild_data.setdefault(guild_id, {})
        guild_data[guild_id][str(msg.id)] = {
            "channel_id": channel.id,
            "mapping": {},
            "author_id": ctx.author.id,
            "content": content,
        }
        await self.config.reaction_messages.set(guild_data)
        await ctx.send(f"Reaction role message created: {msg.id}")

    @reactionroles.command(name="add")
    async def rr_add(self, ctx: commands.Context, message_id: int, emoji: str, role: discord.Role):
        """Add a reaction -> role mapping to a managed message."""
        guild_id = str(ctx.guild.id)
        guild_data = await self.config.reaction_messages()
        if guild_id not in guild_data or str(message_id) not in guild_data[guild_id]:
            await ctx.send("That message is not managed by reactionroles.")
            return
        # Add mapping
        guild_data[guild_id][str(message_id)]["mapping"][emoji] = role.id
        await self.config.reaction_messages.set(guild_data)
        # Add reaction to message if possible
        try:
            channel_id = guild_data[guild_id][str(message_id)]["channel_id"]
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                msg = await channel.fetch_message(message_id)
                await msg.add_reaction(emoji)
        except Exception:
            pass
        await ctx.send(f"Added mapping {emoji} -> {role.name}")

    @reactionroles.command(name="remove")
    async def rr_remove(self, ctx: commands.Context, message_id: int, emoji: str):
        """Remove a mapping from a managed message."""
        guild_id = str(ctx.guild.id)
        guild_data = await self.config.reaction_messages()
        if guild_id not in guild_data or str(message_id) not in guild_data[guild_id]:
            await ctx.send("That message is not managed by reactionroles.")
            return
        mapping = guild_data[guild_id][str(message_id)]["mapping"]
        if emoji in mapping:
            mapping.pop(emoji)
            await self.config.reaction_messages.set(guild_data)
            await ctx.send(f"Removed mapping for {emoji}")
        else:
            await ctx.send("That emoji mapping does not exist.")

    @reactionroles.command(name="list")
    async def rr_list(self, ctx: commands.Context):
        """List all reaction role messages and mappings for this guild."""
        guild_id = str(ctx.guild.id)
        guild_data = await self.config.reaction_messages()
        if guild_id not in guild_data or not guild_data[guild_id]:
            await ctx.send("No reaction role messages configured for this server.")
            return
        lines = []
        for mid, info in guild_data[guild_id].items():
            channel = ctx.guild.get_channel(info["channel_id"])
            header = f"Message {mid} in {channel.mention if channel else 'unknown channel'}"
            lines.append(header)
            for emoji, role_id in info["mapping"].items():
                role = ctx.guild.get_role(role_id)
                lines.append(f"  {emoji} → {role.name if role else role_id}")
        for page in pagify("\n".join(lines), delims=["\n"], shorten_by=0):
            await ctx.send(page)

    @reactionroles.command(name="delete")
    async def rr_delete(self, ctx: commands.Context, message_id: int):
        """Stop managing a reaction role message (does not delete the message)."""
        guild_id = str(ctx.guild.id)
        guild_data = await self.config.reaction_messages()
        if guild_id in guild_data and str(message_id) in guild_data[guild_id]:
            guild_data[guild_id].pop(str(message_id))
            await self.config.reaction_messages.set(guild_data)
            await ctx.send("Stopped managing that message.")
        else:
            await ctx.send("That message is not managed.")

    # -----------------------
    # Reaction event handlers
    # -----------------------
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # Only handle guilds
        if payload.guild_id is None:
            return
        guild_id = str(payload.guild_id)
        guild_data = await self.config.reaction_messages()
        if guild_id not in guild_data:
            return
        msg_id = str(payload.message_id)
        if msg_id not in guild_data[guild_id]:
            return
        mapping = guild_data[guild_id][msg_id]["mapping"]
        emoji = str(payload.emoji)
        if emoji not in mapping:
            return
        role_id = mapping[emoji]
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member:
            return
        role = guild.get_role(role_id)
        if not role:
            return
        try:
            await member.add_roles(role, reason="Reaction role assigned via ReactionRoles cog")
        except Exception:
            # ignore permission errors
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return
        guild_id = str(payload.guild_id)
        guild_data = await self.config.reaction_messages()
        if guild_id not in guild_data:
            return
        msg_id = str(payload.message_id)
        if msg_id not in guild_data[guild_id]:
            return
        mapping = guild_data[guild_id][msg_id]["mapping"]
        emoji = str(payload.emoji)
        if emoji not in mapping:
            return
        role_id = mapping[emoji]
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member:
            return
        role = guild.get_role(role_id)
        if not role:
            return
        try:
            await member.remove_roles(role, reason="Reaction role removed via ReactionRoles cog")
        except Exception:
            pass

    # -----------------------
    # Dashboard integration
    # -----------------------
    # The dashboard expects callable pages that accept a request context and return a dict
    # with keys like 'web_content', 'data', 'notifications'. The decorator `dashboard_page`
    # is used to mark these functions for the dashboard. Adjust signatures to match your
    # dashboard version if needed.

    @staticmethod
    @dashboard_page
    async def list_page(request_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dashboard page: list reaction role messages for a guild.
        Expected request_context keys: 'guild_id', 'user', 'lang', etc.
        Returns: {'web_content': html_string} or {'data': {...}}
        """
        # Minimal defensive checks
        guild_id = request_context.get("guild_id")
        if not guild_id:
            return {"notifications": [{"type": "error", "message": "No guild context provided."}]}

        # Access bot config via request_context if provided, otherwise we will call into the bot.
        bot: Optional[Red] = request_context.get("bot")
        if not bot:
            return {"notifications": [{"type": "error", "message": "Bot context missing."}]}

        cog: ReactionRoles = bot.get_cog("ReactionRoles")
        if not cog:
            return {"notifications": [{"type": "error", "message": "ReactionRoles cog not loaded on the bot."}]}

        guild_data = await cog.config.reaction_messages()
        guild_map = guild_data.get(str(guild_id), {})

        # Build a simple JSON-friendly data payload for the dashboard client to render
        items = []
        for mid, info in guild_map.items():
            items.append({
                "message_id": int(mid),
                "channel_id": info.get("channel_id"),
                "author_id": info.get("author_id"),
                "content": info.get("content"),
                "mappings": [{"emoji": e, "role_id": r} for e, r in info.get("mapping", {}).items()]
            })

        return {"data": {"reaction_messages": items}}

    @staticmethod
    @dashboard_page
    async def create_page(request_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dashboard page: create a new reaction role message.
        The dashboard will render the provided Form and POST back the form data.
        """
        guild_id = request_context.get("guild_id")
        bot: Optional[Red] = request_context.get("bot")
        if not guild_id or not bot:
            return {"notifications": [{"type": "error", "message": "Missing context."}]}

        # Build a form description. The dashboard will render fields based on this structure.
        # Use DpyObjectConverter hints so the dashboard can render role/channel pickers.
        form = Form()
        form["fields"] = [
            {"name": "channel_id", "type": "dpy_channel", "label": "Channel", "converter": DpyObjectConverter("channel")},
            {"name": "content", "type": "textarea", "label": "Message content", "placeholder": "Write the message users will react to"},
            {"name": "mappings", "type": "json", "label": "Emoji -> Role mappings", "placeholder": '[{"emoji":"✅","role_id":123456789}]', "help": "Provide a JSON array of {emoji, role_id} objects."}
        ]
        form["method"] = "POST"
        form["submit_label"] = "Create Reaction Role Message"

        # If the dashboard POSTs data, it will be available in request_context['form_data']
        if request_context.get("method", "GET").upper() == "POST":
            form_data = request_context.get("form_data", {})
            # Validate minimal fields
            channel_id = form_data.get("channel_id")
            content = form_data.get("content", "").strip()
            mappings_raw = form_data.get("mappings", "[]")
            try:
                import json
                mappings_list = json.loads(mappings_raw)
                # Normalize mapping
                mapping = {}
                for entry in mappings_list:
                    emoji = str(entry.get("emoji"))
                    role_id = int(entry.get("role_id"))
                    mapping[emoji] = role_id
            except Exception as e:
                return {"notifications": [{"type": "error", "message": f"Invalid mappings JSON: {e}"}], "form": form}

            # Create the message in Discord asynchronously (dashboard may call this via RPC)
            guild = bot.get_guild(int(guild_id))
            if not guild:
                return {"notifications": [{"type": "error", "message": "Guild not found on bot."}]}
            channel = guild.get_channel(int(channel_id))
            if not channel:
                return {"notifications": [{"type": "error", "message": "Channel not found."}]}
            # Permission check
            if not channel.permissions_for(guild.me).send_messages:
                return {"notifications": [{"type": "error", "message": "Bot cannot send messages in that channel."}]}

            try:
                msg = await channel.send(content)
                # Add reactions
                for emoji in mapping.keys():
                    try:
                        await msg.add_reaction(emoji)
                    except Exception:
                        # ignore invalid emoji errors
                        pass
                # Persist
                cog: ReactionRoles = bot.get_cog("ReactionRoles")
                guild_data = await cog.config.reaction_messages()
                guild_map = guild_data.setdefault(str(guild_id), {})
                guild_map[str(msg.id)] = {
                    "channel_id": channel.id,
                    "mapping": mapping,
                    "author_id": request_context.get("user", {}).get("id"),
                    "content": content,
                }
                await cog.config.reaction_messages.set(guild_data)
                return {"notifications": [{"type": "success", "message": "Reaction role message created."}], "data": {"message_id": msg.id}}
            except Exception as e:
                return {"notifications": [{"type": "error", "message": f"Failed to create message: {e}"}], "form": form}

        # GET: return the form to render
        return {"form": form}

    @staticmethod
    @dashboard_page
    async def edit_page(request_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dashboard page: edit an existing reaction role message mappings.
        Expects 'message_id' param in request_context['params'].
        """
        params = request_context.get("params", {})
        message_id = params.get("message_id")
        guild_id = request_context.get("guild_id")
        bot: Optional[Red] = request_context.get("bot")
        if not message_id or not guild_id or not bot:
            return {"notifications": [{"type": "error", "message": "Missing parameters."}]}

        cog: ReactionRoles = bot.get_cog("ReactionRoles")
        guild_data = await cog.config.reaction_messages()
        guild_map = guild_data.get(str(guild_id), {})
        entry = guild_map.get(str(message_id))
        if not entry:
            return {"notifications": [{"type": "error", "message": "Reaction role message not found."}]}

        # Build form prefilled
        form = Form()
        form["fields"] = [
            {"name": "content", "type": "textarea", "label": "Message content", "value": entry.get("content", "")},
            {"name": "mappings", "type": "json", "label": "Emoji -> Role mappings", "value": [{"emoji": e, "role_id": r} for e, r in entry.get("mapping", {}).items()]},
        ]
        form["method"] = "POST"
        form["submit_label"] = "Save changes"

        if request_context.get("method", "GET").upper() == "POST":
            form_data = request_context.get("form_data", {})
            content = form_data.get("content", entry.get("content", ""))
            mappings_raw = form_data.get("mappings", "[]")
            try:
                import json
                mappings_list = json.loads(mappings_raw) if isinstance(mappings_raw, str) else mappings_raw
                mapping = {}
                for entry_map in mappings_list:
                    emoji = str(entry_map.get("emoji"))
                    role_id = int(entry_map.get("role_id"))
                    mapping[emoji] = role_id
            except Exception as e:
                return {"notifications": [{"type": "error", "message": f"Invalid mappings JSON: {e}"}], "form": form}

            # Update persisted config
            guild_map[str(message_id)]["mapping"] = mapping
            guild_map[str(message_id)]["content"] = content
            await cog.config.reaction_messages.set(guild_data)

            # Try to update message content in Discord
            try:
                guild = bot.get_guild(int(guild_id))
                channel = guild.get_channel(entry["channel_id"])
                msg = await channel.fetch_message(int(message_id))
                await msg.edit(content=content)
                # Ensure reactions exist
                for emoji in mapping.keys():
                    try:
                        await msg.add_reaction(emoji)
                    except Exception:
                        pass
            except Exception:
                # ignore errors; still return success for config update
                pass

            return {"notifications": [{"type": "success", "message": "Reaction role message updated."}]}

        return {"form": form, "data": {"message": entry}}

    @staticmethod
    @dashboard_page
    async def delete_page(request_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dashboard page: delete a managed reaction role message entry (does not delete the Discord message).
        Expects 'message_id' in params.
        """
        params = request_context.get("params", {})
        message_id = params.get("message_id")
        guild_id = request_context.get("guild_id")
        bot: Optional[Red] = request_context.get("bot")
        if not message_id or not guild_id or not bot:
            return {"notifications": [{"type": "error", "message": "Missing parameters."}]}

        cog: ReactionRoles = bot.get_cog("ReactionRoles")
        guild_data = await cog.config.reaction_messages()
        guild_map = guild_data.get(str(guild_id), {})
        if str(message_id) in guild_map:
            guild_map.pop(str(message_id))
            await cog.config.reaction_messages.set(guild_data)
            return {"notifications": [{"type": "success", "message": "Removed reaction role configuration."}]}
        else:
            return {"notifications": [{"type": "error", "message": "Message not found."}]}

    @staticmethod
    @dashboard_page
    async def preview_page(request_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dashboard page: preview a reaction role message (returns data for a live preview).
        Expects 'message_id' in params.
        """
        params = request_context.get("params", {})
        message_id = params.get("message_id")
        guild_id = request_context.get("guild_id")
        bot: Optional[Red] = request_context.get("bot")
        if not message_id or not guild_id or not bot:
            return {"notifications": [{"type": "error", "message": "Missing parameters."}]}

        cog: ReactionRoles = bot.get_cog("ReactionRoles")
        guild_data = await cog.config.reaction_messages()
        entry = guild_data.get(str(guild_id), {}).get(str(message_id))
        if not entry:
            return {"notifications": [{"type": "error", "message": "Message not found."}]}

        # Return a preview payload the dashboard can render client-side
        preview = {
            "content": entry.get("content", ""),
            "mappings": [{"emoji": e, "role_id": r} for e, r in entry.get("mapping", {}).items()]
        }
        return {"data": {"preview": preview}}

    # -----------------------
    # Cog setup: register dashboard pages
    # -----------------------
    async def cog_load(self):
        """
        Called when the cog is loaded. Register third-party pages with the dashboard.
        The exact registration API may differ; adapt to your Red-Web-Dashboard version.
        """
        try:
            # Register pages under the 'reaction_roles' namespace
            pages = {
                "list": self.list_page,
                "create": self.create_page,
                "edit": self.edit_page,
                "delete": self.delete_page,
                "preview": self.preview_page,
            }
            # add_third_party is expected to be provided by the dashboard integration layer.
            add_third_party("reaction_roles", pages)
        except Exception:
            # If registration fails, we don't want to crash the bot; log if available
            try:
                self.bot.log.warning("ReactionRoles: failed to register dashboard pages.")
            except Exception:
                pass

    async def cog_unload(self):
        # If your dashboard integration requires explicit removal, do it here.
        # Example: remove_third_party("reaction_roles")
        pass

