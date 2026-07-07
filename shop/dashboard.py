import json
import os
import typing

import discord

from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator

_: Translator = Translator("Shop", __file__)


def _safe_json_for_script(obj: typing.Any) -> str:
    """json.dumps, but safe to embed inside an inline <script> tag.

    Without this, a shop/item name or description containing the literal
    substring "</script" would prematurely close the tag as far as the HTML
    parser is concerned, silently truncating (and breaking) every bit of
    JS on the page - including handlers completely unrelated to that shop.
    """
    return json.dumps(obj).replace("</", "<\\/")


def dashboard_page(*args, **kwargs):
    """Required so pages are registered correctly even if Dashboard loads after this cog."""

    def decorator(func: typing.Callable):
        func.__dashboard_decorator_params__ = (args, kwargs)
        return func

    return decorator


class DashboardIntegration:
    """Adds a page to Red-Web-Dashboard to fully manage this guild's shops and items."""

    bot: Red

    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        dashboard_cog.rpc.third_parties_handler.add_third_party(self)

    # --------------------
    # helpers
    # --------------------

    @staticmethod
    def _role_color_hex(role: discord.Role) -> str:
        return f"#{role.color.value:06x}" if role.color.value else "#99aab5"

    def _build_shops_payload(self, guild: discord.Guild, shops: dict) -> dict:
        """Augments the raw config data with live role info for display, without mutating storage."""
        payload = {}
        for shop_name, shop_data in shops.items():
            stock_out = {}
            for item_key, entry in (shop_data.get("stock") or {}).items():
                entry = dict(entry)
                role_id = entry.get("role_id")
                role_obj = guild.get_role(role_id) if role_id else None
                stock_out[item_key] = {
                    "price": entry.get("price", 0),
                    "amount": entry.get("amount", None),
                    "description": entry.get("description", ""),
                    "role_id": role_id,
                    "role_name": role_obj.name if role_obj else (item_key if role_id else None),
                    "role_color": self._role_color_hex(role_obj) if role_obj else None,
                    "role_missing": bool(role_id) and role_obj is None,
                }
            payload[shop_name] = {
                "description": shop_data.get("description", ""),
                "thumbnail": shop_data.get("thumbnail", ""),
                "giftable": shop_data.get("giftable", True),
                "stock": stock_out,
            }
        return payload

    # --------------------
    # dashboard page
    # --------------------

    @dashboard_page(
        name="guild",
        description="Create, edit and manage this server's shops and items!",
        methods=("GET", "POST"),
    )
    async def shop_dashboard_guild(
        self, user: discord.User, guild: discord.Guild, **kwargs
    ) -> typing.Dict[str, typing.Any]:
        is_owner = user.id in self.bot.owner_ids
        member = guild.get_member(user.id)
        if not is_owner and not (member is not None and await self.bot.is_admin(member)):
            return {
                "status": 0,
                "error_code": 403,
                "message": _("You don't have permissions to manage the shop in this server."),
            }

        guild_conf = self.config.guild(guild)

        import wtforms

        class ShopActionForm(kwargs["Form"]):
            def __init__(self) -> None:
                super().__init__(prefix="shop_dashboard_")

            action: wtforms.HiddenField = wtforms.HiddenField(
                validators=[wtforms.validators.DataRequired()],
            )
            payload: wtforms.HiddenField = wtforms.HiddenField(
                validators=[wtforms.validators.Optional()],
            )
            submit: wtforms.SubmitField = wtforms.SubmitField("Save")

        form: ShopActionForm = ShopActionForm()

        if form.validate_on_submit() and await form.validate_dpy_converters():
            notifications = []
            action = form.action.data
            try:
                data = json.loads(form.payload.data or "{}")
            except (json.JSONDecodeError, TypeError):
                data = {}

            shops = await guild_conf.shops()

            if action == "save_shop":
                new_name = (data.get("name") or "").strip()
                original_name = (data.get("original_name") or "").strip() or None
                if not new_name:
                    notifications.append(
                        {"message": _("Shop name cannot be empty."), "category": "danger"},
                    )
                elif len(new_name) > 100:
                    notifications.append(
                        {"message": _("Shop name is too long."), "category": "danger"},
                    )
                else:
                    desc = (data.get("description") or "").strip()
                    thumb = (data.get("thumbnail") or "").strip()
                    is_giftable = bool(data.get("giftable", True))

                    stock = {}
                    if original_name and original_name in shops:
                        stock = shops[original_name].get("stock", {})
                        if new_name != original_name:
                            shops.pop(original_name, None)
                    elif new_name in shops:
                        stock = shops[new_name].get("stock", {})

                    shops[new_name] = {
                        "description": desc,
                        "thumbnail": thumb,
                        "giftable": is_giftable,
                        "stock": stock,
                    }
                    await guild_conf.shops.set(shops)
                    notifications.append(
                        {
                            "message": _("Shop `{name}` saved successfully!").format(name=new_name),
                            "category": "success",
                        },
                    )

            elif action == "delete_shop":
                name = data.get("name")
                if name in shops:
                    shops.pop(name)
                    await guild_conf.shops.set(shops)
                    notifications.append(
                        {
                            "message": _("Shop `{name}` deleted.").format(name=name),
                            "category": "success",
                        },
                    )
                else:
                    notifications.append(
                        {"message": _("That shop no longer exists."), "category": "warning"},
                    )

            elif action == "save_item":
                shop_name = data.get("shop_name")
                if shop_name not in shops:
                    notifications.append(
                        {"message": _("That shop no longer exists."), "category": "danger"},
                    )
                else:
                    stock = shops[shop_name].get("stock", {})
                    mode = data.get("mode")
                    original_key = data.get("original_key") or None

                    try:
                        price = int(data.get("price"))
                        if price < 0:
                            raise ValueError
                    except (TypeError, ValueError):
                        notifications.append(
                            {"message": _("Price must be a positive whole number."), "category": "danger"},
                        )
                        price = None

                    final_amount = None
                    amount_error = False
                    raw_amount = data.get("amount")
                    if raw_amount not in (None, ""):
                        try:
                            final_amount = int(raw_amount)
                            if final_amount < 0:
                                raise ValueError
                        except (TypeError, ValueError):
                            amount_error = True
                            notifications.append(
                                {
                                    "message": _("Stock amount must be a positive whole number, or left blank for unlimited."),
                                    "category": "danger",
                                },
                            )

                    if price is not None and not amount_error:
                        desc = (data.get("description") or "").strip()

                        if mode == "role":
                            try:
                                role_id = int(data.get("role_id"))
                            except (TypeError, ValueError):
                                role_id = None
                            role_obj = guild.get_role(role_id) if role_id else None
                            if not role_obj:
                                notifications.append(
                                    {"message": _("Please select a valid role."), "category": "danger"},
                                )
                            else:
                                key = role_obj.name
                                if original_key and original_key != key:
                                    stock.pop(original_key, None)
                                stock[key] = {
                                    "price": price,
                                    "amount": final_amount,
                                    "description": desc,
                                    "role_id": role_obj.id,
                                }
                                shops[shop_name]["stock"] = stock
                                await guild_conf.shops.set(shops)
                                notifications.append(
                                    {
                                        "message": _("Saved role reward `{name}`.").format(name=key),
                                        "category": "success",
                                    },
                                )
                        else:
                            item_name = (data.get("name") or "").strip()
                            if not item_name:
                                notifications.append(
                                    {"message": _("Item name cannot be empty."), "category": "danger"},
                                )
                            elif len(item_name) > 100:
                                notifications.append(
                                    {"message": _("Item name is too long."), "category": "danger"},
                                )
                            else:
                                if original_key and original_key != item_name:
                                    stock.pop(original_key, None)
                                stock[item_name] = {
                                    "price": price,
                                    "amount": final_amount,
                                    "description": desc,
                                }
                                shops[shop_name]["stock"] = stock
                                await guild_conf.shops.set(shops)
                                notifications.append(
                                    {
                                        "message": _("Saved item `{name}`.").format(name=item_name),
                                        "category": "success",
                                    },
                                )

            elif action == "delete_item":
                shop_name = data.get("shop_name")
                item_key = data.get("item_key")
                if shop_name in shops and item_key in (shops[shop_name].get("stock") or {}):
                    shops[shop_name]["stock"].pop(item_key)
                    await guild_conf.shops.set(shops)
                    notifications.append(
                        {
                            "message": _("Deleted `{name}` from `{shop}`.").format(
                                name=item_key, shop=shop_name,
                            ),
                            "category": "success",
                        },
                    )
                else:
                    notifications.append(
                        {"message": _("That item no longer exists."), "category": "warning"},
                    )

            elif action == "set_log_channel":
                raw_channel_id = data.get("channel_id")
                if raw_channel_id in (None, "", "none"):
                    await guild_conf.log_channel.set(None)
                    notifications.append(
                        {"message": _("Shop logging disabled."), "category": "success"},
                    )
                else:
                    try:
                        channel_id = int(raw_channel_id)
                    except (TypeError, ValueError):
                        channel_id = None
                    channel = guild.get_channel(channel_id) if channel_id else None
                    if not channel:
                        notifications.append(
                            {"message": _("Please select a valid channel."), "category": "danger"},
                        )
                    else:
                        await guild_conf.log_channel.set(channel.id)
                        notifications.append(
                            {
                                "message": _("Shop logs will now be posted in #{name}.").format(
                                    name=channel.name,
                                ),
                                "category": "success",
                            },
                        )
            else:
                notifications.append(
                    {"message": _("Unknown action."), "category": "danger"},
                )

            return {
                "status": 0,
                "notifications": notifications,
                "redirect_url": kwargs["request_url"],
            }

        # GET request (or a failed/invalid submission): render the editor.
        shops = await guild_conf.shops()
        log_channel_id = await guild_conf.log_channel()

        roles_data = [
            {"id": role.id, "name": role.name, "color": self._role_color_hex(role)}
            for role in reversed(guild.roles)
            if not role.is_default() and not role.managed
        ]
        channels_data = [
            {"id": channel.id, "name": channel.name}
            for channel in sorted(guild.text_channels, key=lambda c: c.position)
        ]

        file_path = os.path.join(os.path.dirname(__file__), "shop_dashboard.html")
        with open(file_path, encoding="utf-8") as f:
            source = f.read()

        form_html = f'<form id="shopActionForm" method="POST" action="">{form.hidden_tag()}</form>'

        return {
            "status": 0,
            "web_content": {
                "source": source,
                "standalone": True,
                "form_html": form_html,
                "action_field_id": form.action.id,
                "payload_field_id": form.payload.id,
                "guild_name": guild.name,
                "guild_icon": str(guild.icon.url) if guild.icon else "",
                "shops_json": _safe_json_for_script(self._build_shops_payload(guild, shops)),
                "roles_json": _safe_json_for_script(roles_data),
                "channels_json": _safe_json_for_script(channels_data),
                "log_channel_id_json": _safe_json_for_script(log_channel_id),
            },
        }
