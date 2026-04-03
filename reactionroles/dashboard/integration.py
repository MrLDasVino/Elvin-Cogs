import logging
import typing as t
from pathlib import Path
import json

import discord
from redbot.core import commands
from redbot.core.i18n import Translator

# MixinMeta is expected to be available in your cog package structure (example used ..abc.MixinMeta).
# If your project has a different location for MixinMeta, update the import accordingly.
try:
    from ..abc import MixinMeta  # type: ignore
except Exception:
    # Fallback: define a minimal MixinMeta so the mixin can still be used if abc is not present.
    class MixinMeta:
        pass

_ = Translator("ReactionRoles", __file__)
log = logging.getLogger("red.reactionroles.dashboard")
root = Path(__file__).parent
static = root / "static"
templates = root / "templates"


def dashboard_page(*args: t.Any, **kwargs: t.Any) -> t.Callable[[t.Any], t.Any]:
    """
    Decorator used by the dashboard to mark page callables and carry metadata.
    Mirrors the pattern used in your example integration.
    """
    def decorator(func: t.Callable) -> t.Callable[[t.Any], t.Any]:
        func.__dashboard_decorator_params__ = (args, kwargs)
        return func
    return decorator


class DashboardIntegration(MixinMeta):
    """
    Mixin that provides dashboard integration for the ReactionRoles cog.

    To use: have your main cog class inherit from this mixin (see reactionroles.py).
    This mixin listens for the dashboard cog being added and registers this cog
    as a third party with the dashboard RPC handler.
    """

    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        """
        Called by the dashboard when it loads. Register this cog as a third party.
        """
        try:
            log.info("Dashboard cog added, registering ReactionRoles third party.")
            # The dashboard's RPC exposes third_parties_handler with add_third_party(self)
            dashboard_cog.rpc.third_parties_handler.add_third_party(self)
            # Reduce werkzeug logging spam if present
            logging.getLogger("werkzeug").setLevel(logging.WARNING)
        except Exception:
            log.exception("Failed to register ReactionRoles as a dashboard third party.")

    # -----------------------
    # Helper to access stored reaction messages
    # -----------------------
    def _get_reaction_messages_for_guild(self, guild: discord.Guild) -> t.Dict[str, t.Any]:
        """
        Synchronous helper to fetch config data for a guild.
        The dashboard will call the decorated async methods and pass guild/user objects.
        """
        # The actual config access is async; the dashboard will call the async page methods below,
        # which will await the cog's config. These synchronous helpers are kept minimal.
        return {}

    # -----------------------
    # Dashboard pages
    # -----------------------
    @dashboard_page(name="list", description="List reaction role messages for the guild.")
    async def list_page(self, user: discord.User, guild: discord.Guild, **kwargs) -> t.Dict[str, t.Any]:
        """
        Return a JSON-friendly payload listing reaction role messages for the guild.
        """
        if guild is None:
            return {"notifications": [{"type": "error", "message": "Guild context missing."}]}

        # self here is the cog instance (MixinMeta pattern)
        try:
            cog = self  # type: ignore
            guild_data = await cog.config.reaction_messages()
            guild_map = guild_data.get(str(guild.id), {})
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
        except Exception as e:
            log.exception("Error building list_page")
            return {"notifications": [{"type": "error", "message": f"Failed to load reaction messages: {e}"}]}

    @dashboard_page(name="create", description="Create a reaction role message.", methods=("GET", "POST"))
    async def create_page(self, user: discord.User, guild: discord.Guild, method: str = "GET", form_data: dict = None, **kwargs) -> t.Dict[str, t.Any]:
        """
        Render a form on GET and process creation on POST.
        form_data is expected to be a dict when method == "POST".
        """
        form_data = form_data or {}
        # Build a simple form description the dashboard can render.
        form = {
            "fields": [
                {"name": "channel_id", "type": "dpy_channel", "label": "Channel"},
                {"name": "content", "type": "textarea", "label": "Message content", "placeholder": "Write the message users will react to"},
                {"name": "mappings", "type": "json", "label": "Emoji -> Role mappings", "placeholder": '[{"emoji":"✅","role_id":123456789}]', "help": "Provide a JSON array of {emoji, role_id} objects."}
            ],
            "method": "POST",
            "submit_label": "Create Reaction Role Message"
        }

        if method.upper() == "POST":
            channel_id = form_data.get("channel_id")
            content = (form_data.get("content") or "").strip()
            mappings_raw = form_data.get("mappings", "[]")
            try:
                mappings_list = json.loads(mappings_raw) if isinstance(mappings_raw, str) else mappings_raw
                mapping = {}
                for entry in mappings_list:
                    emoji = str(entry.get("emoji"))
                    role_id = int(entry.get("role_id"))
                    mapping[emoji] = role_id
            except Exception as e:
                return {"notifications": [{"type": "error", "message": f"Invalid mappings JSON: {e}"}], "form": form}

            if guild is None:
                return {"notifications": [{"type": "error", "message": "Guild not found."}], "form": form}

            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if not channel:
                return {"notifications": [{"type": "error", "message": "Channel not found."}], "form": form}

            if not channel.permissions_for(guild.me).send_messages:
                return {"notifications": [{"type": "error", "message": "Bot cannot send messages in that channel."}], "form": form}

            try:
                msg = await channel.send(content)
                for emoji in mapping.keys():
                    try:
                        await msg.add_reaction(emoji)
                    except Exception:
                        pass
                # Persist config
                cog = self  # type: ignore
                guild_data = await cog.config.reaction_messages()
                guild_map = guild_data.setdefault(str(guild.id), {})
                guild_map[str(msg.id)] = {
                    "channel_id": channel.id,
                    "mapping": mapping,
                    "author_id": user.id if user else None,
                    "content": content,
                }
                await cog.config.reaction_messages.set(guild_data)
                return {"notifications": [{"type": "success", "message": "Reaction role message created."}], "data": {"message_id": msg.id}}
            except Exception as e:
                log.exception("Failed to create reaction role message via dashboard")
                return {"notifications": [{"type": "error", "message": f"Failed to create message: {e}"}], "form": form}

        # GET: return the form
        return {"form": form}

    @dashboard_page(name="edit", description="Edit a reaction role message.", methods=("GET", "POST"))
    async def edit_page(self, user: discord.User, guild: discord.Guild, message_id: int = None, method: str = "GET", form_data: dict = None, **kwargs) -> t.Dict[str, t.Any]:
        """
        Edit mappings/content for an existing reaction role message.
        message_id should be provided as an integer parameter.
        """
        form_data = form_data or {}
        if guild is None or message_id is None:
            return {"notifications": [{"type": "error", "message": "Missing guild or message_id parameter."}]}

        try:
            cog = self  # type: ignore
            guild_data = await cog.config.reaction_messages()
            guild_map = guild_data.get(str(guild.id), {})
            entry = guild_map.get(str(message_id))
            if not entry:
                return {"notifications": [{"type": "error", "message": "Reaction role message not found."}]}

            form = {
                "fields": [
                    {"name": "content", "type": "textarea", "label": "Message content", "value": entry.get("content", "")},
                    {"name": "mappings", "type": "json", "label": "Emoji -> Role mappings", "value": [{"emoji": e, "role_id": r} for e, r in entry.get("mapping", {}).items()]},
                ],
                "method": "POST",
                "submit_label": "Save changes"
            }

            if method.upper() == "POST":
                content = form_data.get("content", entry.get("content", ""))
                mappings_raw = form_data.get("mappings", "[]")
                try:
                    mappings_list = json.loads(mappings_raw) if isinstance(mappings_raw, str) else mappings_raw
                    mapping = {}
                    for entry_map in mappings_list:
                        emoji = str(entry_map.get("emoji"))
                        role_id = int(entry_map.get("role_id"))
                        mapping[emoji] = role_id
                except Exception as e:
                    return {"notifications": [{"type": "error", "message": f"Invalid mappings JSON: {e}"}], "form": form}

                guild_map[str(message_id)]["mapping"] = mapping
                guild_map[str(message_id)]["content"] = content
                await cog.config.reaction_messages.set(guild_data)

                # Try to update message content and reactions in Discord
                try:
                    channel = guild.get_channel(entry["channel_id"])
                    msg = await channel.fetch_message(int(message_id))
                    await msg.edit(content=content)
                    for emoji in mapping.keys():
                        try:
                            await msg.add_reaction(emoji)
                        except Exception:
                            pass
                except Exception:
                    # ignore discord update errors
                    pass

                return {"notifications": [{"type": "success", "message": "Reaction role message updated."}]}

            return {"form": form, "data": {"message": entry}}
        except Exception as e:
            log.exception("Error in edit_page")
            return {"notifications": [{"type": "error", "message": f"Failed to edit message: {e}"}]}

    @dashboard_page(name="delete", description="Remove a reaction role configuration.", methods=("POST",))
    async def delete_page(self, user: discord.User, guild: discord.Guild, message_id: int = None, **kwargs) -> t.Dict[str, t.Any]:
        """
        Delete a managed reaction role entry (does not delete the Discord message).
        Expects message_id parameter.
        """
        if guild is None or message_id is None:
            return {"notifications": [{"type": "error", "message": "Missing guild or message_id parameter."}]}

        try:
            cog = self  # type: ignore
            guild_data = await cog.config.reaction_messages()
            guild_map = guild_data.get(str(guild.id), {})
            if str(message_id) in guild_map:
                guild_map.pop(str(message_id))
                await cog.config.reaction_messages.set(guild_data)
                return {"notifications": [{"type": "success", "message": "Removed reaction role configuration."}]}
            else:
                return {"notifications": [{"type": "error", "message": "Message not found."}]}
        except Exception as e:
            log.exception("Error in delete_page")
            return {"notifications": [{"type": "error", "message": f"Failed to delete configuration: {e}"}]}

    @dashboard_page(name="preview", description="Preview a reaction role message.")
    async def preview_page(self, user: discord.User, guild: discord.Guild, message_id: int = None, **kwargs) -> t.Dict[str, t.Any]:
        """
        Return a preview payload for a reaction role message.
        """
        if guild is None or message_id is None:
            return {"notifications": [{"type": "error", "message": "Missing guild or message_id parameter."}]}

        try:
            cog = self  # type: ignore
            guild_data = await cog.config.reaction_messages()
            entry = guild_data.get(str(guild.id), {}).get(str(message_id))
            if not entry:
                return {"notifications": [{"type": "error", "message": "Message not found."}]}
            preview = {
                "content": entry.get("content", ""),
                "mappings": [{"emoji": e, "role_id": r} for e, r in entry.get("mapping", {}).items()]
            }
            return {"data": {"preview": preview}}
        except Exception as e:
            log.exception("Error in preview_page")
            return {"notifications": [{"type": "error", "message": f"Failed to build preview: {e}"}]}
