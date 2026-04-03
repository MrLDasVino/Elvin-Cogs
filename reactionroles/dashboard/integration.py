# dashboard/integration.py
import logging
import typing as t
from pathlib import Path
import json

import discord
from redbot.core import commands
from redbot.core.i18n import Translator

try:
    from ..abc import MixinMeta  # type: ignore
except Exception:
    class MixinMeta:
        pass

_ = Translator("ReactionRoles", __file__)
log = logging.getLogger("red.reactionroles.dashboard")
root = Path(__file__).parent
static = root / "static"
templates = root / "templates"


def dashboard_page(*args: t.Any, **kwargs: t.Any) -> t.Callable[[t.Any], t.Any]:
    def decorator(func: t.Callable) -> t.Callable[[t.Any], t.Any]:
        func.__dashboard_decorator_params__ = (args, kwargs)
        return func
    return decorator


def _notif(message: str, category: str = "error") -> t.Dict[str, str]:
    return {"message": message, "category": category}


class DashboardIntegration(MixinMeta):
    """
    Dashboard integration for ReactionRoles.

    This implementation follows the pattern used by other cogs: page callables accept
    (user: discord.User, guild: discord.Guild, **kwargs) and return a dict with
    'status', optional 'notifications', and 'web_content' containing a 'source' HTML string.
    It also supports POST handling when the dashboard forwards form submissions as form_data.
    """

    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        try:
            log.info("Dashboard cog added, registering ReactionRoles third party.")
            dashboard_cog.rpc.third_parties_handler.add_third_party(self)
            logging.getLogger("werkzeug").setLevel(logging.WARNING)
        except Exception:
            log.exception("Failed to register ReactionRoles as a dashboard third party.")

    # helpers
    def _read_template(self, name: str) -> str:
        path = templates / name
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            log.exception("Failed to read template %s", name)
            return f"<pre>Template {name} not found.</pre>"

    def _read_static(self, path_parts: t.List[str]) -> str:
        path = static.joinpath(*path_parts)
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            log.exception("Failed to read static file %s", path)
            return ""

    def _build_page(self, template_name: str) -> str:
        css = self._read_static(["css", "reactionroles.css"])
        js = self._read_static(["js", "reactionroles.js"])
        tpl = self._read_template(template_name)
        return f"<style>\n{css}\n</style>\n\n{tpl}\n\n<script>\n{js}\n</script>"

    # utility to parse mappings JSON safely
    def _parse_mappings(self, raw: t.Union[str, t.List[dict]]) -> t.Dict[str, int]:
        mapping: t.Dict[str, int] = {}
        if raw is None:
            return mapping
        try:
            if isinstance(raw, str):
                parsed = json.loads(raw) if raw.strip() else []
            else:
                parsed = raw
            for entry in parsed:
                emoji = str(entry.get("emoji"))
                role_id = int(entry.get("role_id"))
                mapping[emoji] = role_id
        except Exception:
            # return empty mapping on parse error
            return {}
        return mapping

    # -----------------------
    # Pages
    # -----------------------
    @dashboard_page(name="list", description="List reaction role messages for the guild.")
    async def list_page(self, user: discord.User = None, guild: discord.Guild = None, **kwargs) -> t.Dict[str, t.Any]:
        """
        Return a rendered page listing reaction role messages.
        Signature matches other cogs: accepts user and guild objects when called from a guild view.
        """
        if guild is None:
            return {"status": 0, "notifications": [_notif("Guild context missing. Open this page from the guild view in the dashboard.", "error")]}

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
            source = self._build_page("list.html")
            page_html = source.replace("/*__INITIAL_DATA__*/", json.dumps({"reaction_messages": items}))
            return {"status": 0, "web_content": {"source": page_html, "standalone": True}}
        except Exception as e:
            log.exception("Error building list_page")
            return {"status": 0, "notifications": [_notif(f"Failed to load reaction messages: {e}", "error")]}

    @dashboard_page(name="create", description="Create a reaction role message.", methods=("GET", "POST"))
    async def create_page(
        self,
        user: discord.User = None,
        guild: discord.Guild = None,
        method: str = "GET",
        form_data: dict = None,
        **kwargs,
    ) -> t.Dict[str, t.Any]:
        """
        Render create page on GET. On POST, expect form_data dict with keys:
        channel_id, content, mappings (JSON string or list).
        Returns notifications and redirect_url on success to let the dashboard refresh.
        """
        if guild is None:
            return {"status": 0, "notifications": [_notif("Guild context missing. Open this page from the guild view in the dashboard.", "error")]}

        form_data = form_data or {}
        if str(method).upper() == "POST" and form_data:
            channel_id = form_data.get("channel_id")
            content = (form_data.get("content") or "").strip()
            mappings_raw = form_data.get("mappings", "[]")
            mapping = self._parse_mappings(mappings_raw)
            if not channel_id or not content:
                return {"status": 0, "notifications": [_notif("channel_id and content are required.", "error")]}

            try:
                channel = guild.get_channel(int(channel_id))
                if not channel:
                    return {"status": 0, "notifications": [_notif("Channel not found.", "error")]}

                if not channel.permissions_for(guild.me).send_messages:
                    return {"status": 0, "notifications": [_notif("Bot cannot send messages in that channel.", "error")]}

                msg = await channel.send(content)
                for emoji in mapping.keys():
                    try:
                        await msg.add_reaction(emoji)
                    except Exception:
                        pass

                # persist
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

                notifications = [{"message": "Reaction role message created.", "category": "success"}]
                redirect = kwargs.get("request_url") or kwargs.get("request_url_full") or ""
                return {"status": 0, "notifications": notifications, "redirect_url": redirect}
            except Exception as e:
                log.exception("Failed to create message via dashboard")
                return {"status": 0, "notifications": [_notif(f"Failed to create message: {e}", "error")]}

        # GET: render page
        try:
            source = self._build_page("create.html")
            page_html = source.replace("/*__INITIAL_DATA__*/", json.dumps({}))
            return {"status": 0, "web_content": {"source": page_html, "standalone": True}}
        except Exception as e:
            log.exception("Error building create_page")
            return {"status": 0, "notifications": [_notif(f"Failed to render create page: {e}", "error")]}

    @dashboard_page(name="edit", description="Edit a reaction role message.", methods=("GET", "POST"))
    async def edit_page(
        self,
        user: discord.User = None,
        guild: discord.Guild = None,
        message_id: int = None,
        method: str = "GET",
        form_data: dict = None,
        **kwargs,
    ) -> t.Dict[str, t.Any]:
        """
        Edit an existing reaction role message. On POST expects form_data with content and mappings.
        """
        if guild is None:
            return {"status": 0, "notifications": [_notif("Guild context missing. Open this page from the guild view in the dashboard.", "error")]}

        form_data = form_data or {}
        mid = message_id or form_data.get("message_id") or kwargs.get("message_id")
        try:
            mid_int = int(mid) if mid is not None else None
        except Exception:
            mid_int = None

        if mid_int is None:
            return {"status": 0, "notifications": [_notif("Missing message_id parameter.", "error")]}

        try:
            cog = self  # type: ignore
            guild_data = await cog.config.reaction_messages()
            entry = guild_data.get(str(guild.id), {}).get(str(mid_int))
            if not entry:
                return {"status": 0, "notifications": [_notif("Reaction role message not found.", "error")]}

            if str(method).upper() == "POST" and form_data:
                content = form_data.get("content", entry.get("content", ""))
                mappings_raw = form_data.get("mappings", "[]")
                mapping = self._parse_mappings(mappings_raw)
                guild_map = guild_data.setdefault(str(guild.id), {})
                guild_map[str(mid_int)]["mapping"] = mapping
                guild_map[str(mid_int)]["content"] = content
                await cog.config.reaction_messages.set(guild_data)

                # try to update message in discord
                try:
                    channel = guild.get_channel(entry["channel_id"])
                    if channel:
                        msg = await channel.fetch_message(int(mid_int))
                        await msg.edit(content=content)
                        for emoji in mapping.keys():
                            try:
                                await msg.add_reaction(emoji)
                            except Exception:
                                pass
                except Exception:
                    pass

                notifications = [{"message": "Reaction role message updated.", "category": "success"}]
                redirect = kwargs.get("request_url") or ""
                return {"status": 0, "notifications": notifications, "redirect_url": redirect}

            # GET: render edit page with initial data
            source = self._build_page("edit.html")
            page_html = source.replace("/*__INITIAL_DATA__*/", json.dumps({"message": entry, "message_id": mid_int}))
            return {"status": 0, "web_content": {"source": page_html, "standalone": True}}
        except Exception as e:
            log.exception("Error in edit_page")
            return {"status": 0, "notifications": [_notif(f"Failed to render/edit message: {e}", "error")]}

    @dashboard_page(name="preview", description="Preview a reaction role message.")
    async def preview_page(self, user: discord.User = None, guild: discord.Guild = None, message_id: int = None, **kwargs) -> t.Dict[str, t.Any]:
        """
        Return a preview page for a managed reaction role message.
        """
        if guild is None:
            return {"status": 0, "notifications": [_notif("Guild context missing. Open this page from the guild view in the dashboard.", "error")]}

        try:
            mid = message_id or kwargs.get("message_id")
            mid_int = int(mid) if mid is not None else None
        except Exception:
            mid_int = None

        if mid_int is None:
            return {"status": 0, "notifications": [_notif("Missing message_id parameter.", "error")]}

        try:
            cog = self  # type: ignore
            guild_data = await cog.config.reaction_messages()
            entry = guild_data.get(str(guild.id), {}).get(str(mid_int))
            if not entry:
                return {"status": 0, "notifications": [_notif("Message not found.", "error")]}

            source = self._build_page("preview.html")
            page_html = source.replace(
                "/*__INITIAL_DATA__*/",
                json.dumps({"preview": {"content": entry.get("content", ""), "mappings": [{"emoji": e, "role_id": r} for e, r in entry.get("mapping", {}).items()]}}),
            )
            return {"status": 0, "web_content": {"source": page_html, "standalone": True}}
        except Exception as e:
            log.exception("Error in preview_page")
            return {"status": 0, "notifications": [_notif(f"Failed to build preview: {e}", "error")]}
