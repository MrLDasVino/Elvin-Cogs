from typing import Dict, Any, Optional
import json

# Try to import the dashboard API; fall back to no-op placeholders if unavailable.
try:
    from red_web_dashboard.api import dashboard_page, add_third_party, Form, DpyObjectConverter
except Exception:
    # No-op placeholders
    def dashboard_page(func):
        return func

    def add_third_party(name, pages):
        return None

    class Form(dict):
        pass

    class DpyObjectConverter:
        def __init__(self, obj_type: str):
            self.obj_type = obj_type


# Helper to safely get the cog instance from the bot
def _get_cog(bot, cog_name: str):
    try:
        return bot.get_cog(cog_name)
    except Exception:
        return None


# -----------------------
# Page implementations
# -----------------------
@dashboard_page
async def list_page(request_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    List reaction role messages for a guild.
    Expects request_context to include: 'bot', 'guild_id'.
    Returns: {'data': {...}} or {'notifications': [...]}
    """
    bot = request_context.get("bot")
    guild_id = request_context.get("guild_id")
    if not bot or not guild_id:
        return {"notifications": [{"type": "error", "message": "Missing bot or guild context."}]}

    cog = _get_cog(bot, "ReactionRoles")
    if not cog:
        return {"notifications": [{"type": "error", "message": "ReactionRoles cog not loaded."}]}

    guild_data = await cog.config.reaction_messages()
    guild_map = guild_data.get(str(guild_id), {})

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


@dashboard_page
async def create_page(request_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new reaction role message via the dashboard.
    Renders a form on GET and processes form_data on POST.
    """
    bot = request_context.get("bot")
    guild_id = request_context.get("guild_id")
    user = request_context.get("user", {})
    method = request_context.get("method", "GET").upper()
    form_data = request_context.get("form_data", {})

    if not bot or not guild_id:
        return {"notifications": [{"type": "error", "message": "Missing bot or guild context."}]}

    cog = _get_cog(bot, "ReactionRoles")
    if not cog:
        return {"notifications": [{"type": "error", "message": "ReactionRoles cog not loaded."}]}

    # Build a simple form description for the dashboard to render
    form = Form()
    form["fields"] = [
        {"name": "channel_id", "type": "dpy_channel", "label": "Channel", "converter": DpyObjectConverter("channel")},
        {"name": "content", "type": "textarea", "label": "Message content", "placeholder": "Write the message users will react to"},
        {"name": "mappings", "type": "json", "label": "Emoji -> Role mappings", "placeholder": '[{"emoji":"✅","role_id":123456789}]', "help": "Provide a JSON array of {emoji, role_id} objects."}
    ]
    form["method"] = "POST"
    form["submit_label"] = "Create Reaction Role Message"

    if method == "POST":
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

        guild = bot.get_guild(int(guild_id))
        if not guild:
            return {"notifications": [{"type": "error", "message": "Guild not found on bot."}]}

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
            guild_data = await cog.config.reaction_messages()
            guild_map = guild_data.setdefault(str(guild_id), {})
            guild_map[str(msg.id)] = {
                "channel_id": channel.id,
                "mapping": mapping,
                "author_id": user.get("id"),
                "content": content,
            }
            await cog.config.reaction_messages.set(guild_data)
            return {"notifications": [{"type": "success", "message": "Reaction role message created."}], "data": {"message_id": msg.id}}
        except Exception as e:
            return {"notifications": [{"type": "error", "message": f"Failed to create message: {e}"}], "form": form}

    # GET: return the form
    return {"form": form}


@dashboard_page
async def edit_page(request_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Edit an existing reaction role message mappings.
    Expects 'message_id' in request_context['params'].
    """
    bot = request_context.get("bot")
    guild_id = request_context.get("guild_id")
    params = request_context.get("params", {})
    method = request_context.get("method", "GET").upper()
    form_data = request_context.get("form_data", {})

    message_id = params.get("message_id")
    if not bot or not guild_id or not message_id:
        return {"notifications": [{"type": "error", "message": "Missing parameters."}]}

    cog = _get_cog(bot, "ReactionRoles")
    if not cog:
        return {"notifications": [{"type": "error", "message": "ReactionRoles cog not loaded."}]}

    guild_data = await cog.config.reaction_messages()
    guild_map = guild_data.get(str(guild_id), {})
    entry = guild_map.get(str(message_id))
    if not entry:
        return {"notifications": [{"type": "error", "message": "Reaction role message not found."}]}

    form = Form()
    form["fields"] = [
        {"name": "content", "type": "textarea", "label": "Message content", "value": entry.get("content", "")},
        {"name": "mappings", "type": "json", "label": "Emoji -> Role mappings", "value": [{"emoji": e, "role_id": r} for e, r in entry.get("mapping", {}).items()]},
    ]
    form["method"] = "POST"
    form["submit_label"] = "Save changes"

    if method == "POST":
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
            guild = bot.get_guild(int(guild_id))
            channel = guild.get_channel(entry["channel_id"])
            msg = await channel.fetch_message(int(message_id))
            await msg.edit(content=content)
            for emoji in mapping.keys():
                try:
                    await msg.add_reaction(emoji)
                except Exception:
                    pass
        except Exception:
            pass

        return {"notifications": [{"type": "success", "message": "Reaction role message updated."}]}

    return {"form": form, "data": {"message": entry}}


@dashboard_page
async def delete_page(request_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Delete a managed reaction role message entry (does not delete the Discord message).
    Expects 'message_id' in params.
    """
    bot = request_context.get("bot")
    guild_id = request_context.get("guild_id")
    params = request_context.get("params", {})
    message_id = params.get("message_id")
    if not bot or not guild_id or not message_id:
        return {"notifications": [{"type": "error", "message": "Missing parameters."}]}

    cog = _get_cog(bot, "ReactionRoles")
    if not cog:
        return {"notifications": [{"type": "error", "message": "ReactionRoles cog not loaded."}]}

    guild_data = await cog.config.reaction_messages()
    guild_map = guild_data.get(str(guild_id), {})
    if str(message_id) in guild_map:
        guild_map.pop(str(message_id))
        await cog.config.reaction_messages.set(guild_data)
        return {"notifications": [{"type": "success", "message": "Removed reaction role configuration."}]}
    else:
        return {"notifications": [{"type": "error", "message": "Message not found."}]}


@dashboard_page
async def preview_page(request_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a preview payload for a reaction role message.
    Expects 'message_id' in params.
    """
    bot = request_context.get("bot")
    guild_id = request_context.get("guild_id")
    params = request_context.get("params", {})
    message_id = params.get("message_id")
    if not bot or not guild_id or not message_id:
        return {"notifications": [{"type": "error", "message": "Missing parameters."}]}

    cog = _get_cog(bot, "ReactionRoles")
    if not cog:
        return {"notifications": [{"type": "error", "message": "ReactionRoles cog not loaded."}]}

    guild_data = await cog.config.reaction_messages()
    entry = guild_data.get(str(guild_id), {}).get(str(message_id))
    if not entry:
        return {"notifications": [{"type": "error", "message": "Message not found."}]}

    preview = {
        "content": entry.get("content", ""),
        "mappings": [{"emoji": e, "role_id": r} for e, r in entry.get("mapping", {}).items()]
    }
    return {"data": {"preview": preview}}


# -----------------------
# Registration helpers
# -----------------------
_registered = False


async def register(bot, cog_instance) -> None:
    """
    Register the third-party pages with the dashboard.
    Called from the cog's cog_load hook with the bot and cog instance.
    """
    global _registered
    if _registered:
        return

    try:
        pages = {
            "list": list_page,
            "create": create_page,
            "edit": edit_page,
            "delete": delete_page,
            "preview": preview_page,
        }
        add_third_party("reaction_roles", pages)
        _registered = True
    except Exception:
        # If registration fails, do not raise; dashboard may not be installed.
        try:
            bot.log.warning("ReactionRoles dashboard integration: failed to register pages.")
        except Exception:
            pass


async def unregister(bot) -> None:
    """
    Optional: if your dashboard supports unregistering, implement it here.
    This module provides a placeholder to call on cog_unload.
    """
    global _registered
    # No-op by default; set flag to False so future register attempts can run.
    _registered = False
