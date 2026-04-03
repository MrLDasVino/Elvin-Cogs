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
    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        try:
            log.info("Dashboard cog added, registering ReactionRoles third party.")
            dashboard_cog.rpc.third_parties_handler.add_third_party(self)
            logging.getLogger("werkzeug").setLevel(logging.WARNING)
        except Exception:
            log.exception("Failed to register ReactionRoles as a dashboard third party.")

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

    # --- robust resolution + logging ---
    def _resolve_guild(self, guild: discord.Guild, kwargs: dict) -> t.Optional[discord.Guild]:
        if guild:
            return guild
        # log incoming kwargs for debugging
        try:
            log.debug("dashboard kwargs: %s", kwargs)
        except Exception:
            pass
        # common alternate keys
        for key in ("guild", "guild_id", "guildId", "guildIdStr", "guildid"):
            gid = kwargs.get(key)
            if gid:
                try:
                    gid_int = int(gid)
                except Exception:
                    continue
                bot = getattr(self, "bot", None)
                if bot:
                    g = bot.get_guild(gid_int)
                    if g:
                        return g
        return None

    def _resolve_message_id(self, message_id: t.Optional[int], kwargs: dict) -> t.Optional[int]:
        if message_id:
            try:
                return int(message_id)
            except Exception:
                return None
        for key in ("message_id", "messageId", "id", "msg_id", "messageid"):
            val = kwargs.get(key)
            if val is None:
                continue
            try:
                return int(val)
            except Exception:
                continue
        return None

    # --- pages now use resolution helpers and return clear notifications ---
    @dashboard_page(name="list", description="List reaction role messages for the guild.")
    async def list_page(self, user: discord.User, guild: discord.Guild = None, **kwargs) -> t.Dict[str, t.Any]:
        guild = self._resolve_guild(guild, kwargs)
        if guild is None:
            return {"notifications": [_notif("Guild context missing. Open this page from a guild view in the dashboard.", "error")]}
        try:
            cog = self
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
            return {"web_content": {"source": page_html, "expanded": False, "fullscreen": False}}
        except Exception as e:
            log.exception("Error building list_page")
            return {"notifications": [_notif(f"Failed to load reaction messages: {e}", "error")]}

    @dashboard_page(name="create", description="Create a reaction role message.", methods=("GET", "POST"))
    async def create_page(self, user: discord.User, guild: discord.Guild = None, method: str = "GET", form_data: dict = None, **kwargs) -> t.Dict[str, t.Any]:
        guild = self._resolve_guild(guild, kwargs)
        if guild is None:
            return {"notifications": [_notif("Guild context missing. Open this page from a guild view in the dashboard.", "error")]}
        try:
            source = self._build_page("create.html")
            page_html = source.replace("/*__INITIAL_DATA__*/", json.dumps({}))
            return {"web_content": {"source": page_html, "expanded": False, "fullscreen": False}}
        except Exception as e:
            log.exception("Error building create_page")
            return {"notifications": [_notif(f"Failed to render create page: {e}", "error")]}

    @dashboard_page(name="edit", description="Edit a reaction role message.", methods=("GET", "POST"))
    async def edit_page(self, user: discord.User, guild: discord.Guild = None, message_id: int = None, method: str = "GET", form_data: dict = None, **kwargs) -> t.Dict[str, t.Any]:
        guild = self._resolve_guild(guild, kwargs)
        resolved_mid = self._resolve_message_id(message_id, kwargs)
        if guild is None or resolved_mid is None:
            return {"notifications": [_notif("Missing guild or message_id parameter. Open the page from the guild view and include message_id in the query.", "error")]}
        try:
            cog = self
            guild_data = await cog.config.reaction_messages()
            entry = guild_data.get(str(guild.id), {}).get(str(resolved_mid))
            if not entry:
                return {"notifications": [_notif("Reaction role message not found.", "error")]}
            source = self._build_page("edit.html")
            page_html = source.replace("/*__INITIAL_DATA__*/", json.dumps({"message": entry, "message_id": int(resolved_mid)}))
            return {"web_content": {"source": page_html, "expanded": False, "fullscreen": False}}
        except Exception as e:
            log.exception("Error building edit_page")
            return {"notifications": [_notif(f"Failed to render edit page: {e}", "error")]}

    @dashboard_page(name="preview", description="Preview a reaction role message.")
    async def preview_page(self, user: discord.User, guild: discord.Guild = None, message_id: int = None, **kwargs) -> t.Dict[str, t.Any]:
        guild = self._resolve_guild(guild, kwargs)
        resolved_mid = self._resolve_message_id(message_id, kwargs)
        if guild is None or resolved_mid is None:
            return {"notifications": [_notif("Missing guild or message_id parameter. Open the page from the guild view and include message_id in the query.", "error")]}
        try:
            cog = self
            guild_data = await cog.config.reaction_messages()
            entry = guild_data.get(str(guild.id), {}).get(str(resolved_mid))
            if not entry:
                return {"notifications": [_notif("Message not found.", "error")]}
            source = self._build_page("preview.html")
            page_html = source.replace(
                "/*__INITIAL_DATA__*/",
                json.dumps({"preview": {"content": entry.get("content", ""), "mappings": [{"emoji": e, "role_id": r} for e, r in entry.get("mapping", {}).items()]}}),
            )
            return {"web_content": {"source": page_html, "expanded": False, "fullscreen": False}}
        except Exception as e:
            log.exception("Error in preview_page")
            return {"notifications": [_notif(f"Failed to build preview: {e}", "error")]}
