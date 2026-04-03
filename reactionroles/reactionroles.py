from typing import Optional, Dict, Any, List
import discord

from redbot.core import commands, Config, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify


DEFAULTS = {
    "reaction_messages": {}  # guild_id -> {message_id: {channel_id, mapping: {emoji: role_id}, author_id, content}}
}


class ReactionRoles(commands.Cog):
    """Reaction Roles manager with optional Red-Web-Dashboard integration."""

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
    # Cog lifecycle hooks
    # -----------------------
    async def cog_load(self):
        """
        Called when the cog is loaded. Attempt to register dashboard pages by importing
        the dashboard integration module and calling its register function.
        """
        try:
            # Import the integration module from the dashboard package inside the cog folder
            # and call its register function with the bot and this cog instance.
            from .dashboard import integration  # type: ignore
            await integration.register(self.bot, self)
        except Exception:
            # If integration is not present or registration fails, ignore silently.
            # Logging is optional; avoid raising to prevent load failure.
            try:
                self.bot.log.warning("ReactionRoles: dashboard integration registration failed or not present.")
            except Exception:
                pass

    async def cog_unload(self):
        # If the integration module exposes an unregister function, call it.
        try:
            from .dashboard import integration  # type: ignore
            if hasattr(integration, "unregister"):
                await integration.unregister(self.bot)
        except Exception:
            pass
