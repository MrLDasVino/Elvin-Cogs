import html
import logging
import typing
from pathlib import Path

import discord
from redbot.core import commands
from redbot.core.bot import Red

log = logging.getLogger("red.shop.dashboard")

HTML_PATH = Path(__file__).parent / "shop_dashboard.html"


def _load_template() -> str:
    try:
        return HTML_PATH.read_text(encoding="utf-8")
    except Exception:
        log.exception("Shop: could not read shop_dashboard.html from %s", HTML_PATH)
        return (
            "<p><strong>Shop dashboard template failed to load.</strong><br>"
            "Check the bot's console/logs for a traceback, and make sure "
            "<code>shop_dashboard.html</code> is in the same folder as "
            "<code>dashboard_integration.py</code>.</p>"
        )


def _safe_render(label: str, func: typing.Callable, *args, **kwargs) -> str:
    try:
        return str(func(*args, **kwargs))
    except Exception:
        log.exception("Shop dashboard: failed to render %s", label)
        return f"<!-- failed to render {label}, see bot logs -->"


def _role_color_hex(role: discord.Role) -> str:
    return f"#{role.color.value:06x}" if role.color.value else "#99aab5"


def _render_role_select(field, id_: str, role_data) -> str:
    selected_value = field.data or ""
    placeholder_selected = " selected" if selected_value == "" else ""
    options = [f'<option value=""{placeholder_selected}>Select a role\u2026</option>']
    for role_id, role_name, color in role_data:
        selected = " selected" if role_id == selected_value else ""
        options.append(
            f'<option value="{role_id}" style="color:{color};" data-color="{color}"{selected}>{html.escape(role_name)}</option>'
        )
    select_html = (
        f'<select name="{field.name}" id="{id_}" class="shop-input shop-role-select" onchange="shopUpdateRoleDot(this)">'
        + "".join(options)
        + "</select>"
    )
    return (
        f'<div class="shop-role-select-wrap">'
        f'<span class="shop-role-color-dot" id="{id_}_dot"></span>'
        f"{select_html}"
        f"</div>"
    )


def _render_add_shop_form_html(form) -> str:
    hidden = _safe_render("add_shop_form.hidden_tag", form.hidden_tag)
    name_field = _safe_render("add_shop_form.name", form.name, class_="shop-input", placeholder="e.g. General Store")
    name_errors = "".join(f'<span class="shop-error">{e}</span>' for e in getattr(form.name, "errors", []))
    desc_field = _safe_render("add_shop_form.description", form.description, class_="shop-input", rows="2")
    thumb_field = _safe_render(
        "add_shop_form.thumbnail", form.thumbnail, class_="shop-input", placeholder="https://example.com/image.png"
    )
    thumb_errors = "".join(f'<span class="shop-error">{e}</span>' for e in getattr(form.thumbnail, "errors", []))
    giftable_field = _safe_render("add_shop_form.giftable", form.giftable)
    submit_field = _safe_render("add_shop_form.submit", form.submit, class_="shop-btn")
    return f"""
    <form method="POST">
        {hidden}
        <div class="shop-form-row">
            <label>Shop name</label>
            {name_field}
            {name_errors}
        </div>
        <div class="shop-form-row">
            <label>Description</label>
            {desc_field}
        </div>
        <div class="shop-form-row">
            <label>Thumbnail URL</label>
            {thumb_field}
            {thumb_errors}
        </div>
        <div class="shop-form-row shop-checkbox-row">
            {giftable_field}
            <label>Allow gifting items from this shop</label>
        </div>
        {submit_field}
    </form>
    """


def _render_edit_shop_form_html(form) -> str:
    hidden = _safe_render("edit_shop_form.hidden_tag", form.hidden_tag)
    original_name_field = _safe_render(
        "edit_shop_form.original_name", form.original_name, id="shop_edit_shop_original_name"
    )
    name_field = _safe_render(
        "edit_shop_form.name", form.name, id="shop_edit_shop_name", class_="shop-input"
    )
    desc_field = _safe_render(
        "edit_shop_form.description", form.description, id="shop_edit_shop_description", class_="shop-input", rows="2"
    )
    thumb_field = _safe_render(
        "edit_shop_form.thumbnail", form.thumbnail, id="shop_edit_shop_thumbnail", class_="shop-input"
    )
    giftable_field = _safe_render(
        "edit_shop_form.giftable", form.giftable, id="shop_edit_shop_giftable"
    )
    submit_field = _safe_render("edit_shop_form.submit", form.submit, class_="shop-btn")
    return f"""
    <form method="POST">
        {hidden}
        {original_name_field}
        <div class="shop-form-row">
            <label>Shop name</label>
            {name_field}
        </div>
        <div class="shop-form-row">
            <label>Description</label>
            {desc_field}
        </div>
        <div class="shop-form-row">
            <label>Thumbnail URL</label>
            {thumb_field}
        </div>
        <div class="shop-form-row shop-checkbox-row">
            {giftable_field}
            <label>Allow gifting items from this shop</label>
        </div>
        {submit_field}
        <button type="button" class="shop-btn shop-btn-secondary" onclick="shopCloseEditShop()">Cancel</button>
    </form>
    """


def _render_add_item_form_html(form, role_data) -> str:
    hidden = _safe_render("add_item_form.hidden_tag", form.hidden_tag)
    shop_name_field = _safe_render(
        "add_item_form.shop_name", form.shop_name, id="shop_add_item_shop_name"
    )
    mode_field = _safe_render(
        "add_item_form.mode", form.mode, id="shop_add_item_mode", onchange="shopToggleItemMode('add')"
    )
    item_name_field = _safe_render(
        "add_item_form.item_name", form.item_name, id="shop_add_item_item_name", class_="shop-input"
    )
    role_field = _render_role_select(form.role, "shop_add_item_role", role_data)
    role_errors = "".join(f'<span class="shop-error">{e}</span>' for e in getattr(form.role, "errors", []))
    price_field = _safe_render("add_item_form.price", form.price, id="shop_add_item_price", class_="shop-input")
    price_errors = "".join(f'<span class="shop-error">{e}</span>' for e in getattr(form.price, "errors", []))
    amount_field = _safe_render("add_item_form.amount", form.amount, id="shop_add_item_amount", class_="shop-input")
    desc_field = _safe_render(
        "add_item_form.description", form.description, id="shop_add_item_description", class_="shop-input", rows="2"
    )
    submit_field = _safe_render("add_item_form.submit", form.submit, class_="shop-btn")
    return f"""
    <form method="POST">
        {hidden}
        {shop_name_field}
        <div class="shop-form-row">
            <label>Type</label>
            {mode_field}
        </div>
        <div class="shop-form-row" id="shop_add_item_item_name_row" style="display:none;">
            <label>Item name</label>
            {item_name_field}
        </div>
        <div class="shop-form-row" id="shop_add_item_role_row">
            <label>Role reward</label>
            {role_field}
            {role_errors}
        </div>
        <div class="shop-form-row">
            <label>Price (credits)</label>
            {price_field}
            {price_errors}
        </div>
        <div class="shop-form-row">
            <label>Stock amount (leave blank for unlimited)</label>
            {amount_field}
        </div>
        <div class="shop-form-row">
            <label>Description</label>
            {desc_field}
        </div>
        {submit_field}
    </form>
    """


def _render_edit_item_form_html(form, role_data) -> str:
    hidden = _safe_render("edit_item_form.hidden_tag", form.hidden_tag)
    shop_name_field = _safe_render(
        "edit_item_form.shop_name", form.shop_name, id="shop_edit_item_shop_name"
    )
    original_key_field = _safe_render(
        "edit_item_form.original_key", form.original_key, id="shop_edit_item_original_key"
    )
    mode_field = _safe_render(
        "edit_item_form.mode", form.mode, id="shop_edit_item_mode", onchange="shopToggleItemMode('edit')"
    )
    item_name_field = _safe_render(
        "edit_item_form.item_name", form.item_name, id="shop_edit_item_item_name", class_="shop-input"
    )
    role_field = _render_role_select(form.role, "shop_edit_item_role", role_data)
    role_errors = "".join(f'<span class="shop-error">{e}</span>' for e in getattr(form.role, "errors", []))
    price_field = _safe_render("edit_item_form.price", form.price, id="shop_edit_item_price", class_="shop-input")
    amount_field = _safe_render(
        "edit_item_form.amount", form.amount, id="shop_edit_item_amount", class_="shop-input"
    )
    desc_field = _safe_render(
        "edit_item_form.description", form.description, id="shop_edit_item_description", class_="shop-input", rows="2"
    )
    submit_field = _safe_render("edit_item_form.submit", form.submit, class_="shop-btn")
    return f"""
    <form method="POST">
        {hidden}
        {shop_name_field}
        {original_key_field}
        <div class="shop-form-row">
            <label>Type</label>
            {mode_field}
        </div>
        <div class="shop-form-row" id="shop_edit_item_item_name_row" style="display:none;">
            <label>Item name</label>
            {item_name_field}
        </div>
        <div class="shop-form-row" id="shop_edit_item_role_row">
            <label>Role reward</label>
            {role_field}
            {role_errors}
        </div>
        <div class="shop-form-row">
            <label>Price (credits)</label>
            {price_field}
        </div>
        <div class="shop-form-row">
            <label>Stock amount (leave blank for unlimited)</label>
            {amount_field}
        </div>
        <div class="shop-form-row">
            <label>Description</label>
            {desc_field}
        </div>
        {submit_field}
        <button type="button" class="shop-btn shop-btn-secondary" onclick="shopCloseEditItem()">Cancel</button>
    </form>
    """


def _render_manage_form_html(form) -> str:
    hidden = _safe_render("manage_form.hidden_tag", form.hidden_tag)
    shop_name_field = _safe_render("manage_form.shop_name", form.shop_name, id="shop_manage_shop_name")
    item_key_field = _safe_render("manage_form.item_key", form.item_key, id="shop_manage_item_key")
    action_field = _safe_render("manage_form.action", form.action, id="shop_manage_action")
    submit_field = _safe_render("manage_form.submit", form.submit, id="shop_manage_submit")
    return f"""
    <form id="shop-manage-form" method="POST" style="display:none;">
        {hidden}
        {shop_name_field}
        {item_key_field}
        {action_field}
        {submit_field}
    </form>
    """


def _render_settings_form_html(form) -> str:
    hidden = _safe_render("settings_form.hidden_tag", form.hidden_tag)
    label = _safe_render("settings_form.log_channel.label", lambda: form.log_channel.label)
    field = _safe_render("settings_form.log_channel", form.log_channel, class_="shop-input")
    submit_field = _safe_render("settings_form.submit", form.submit, class_="shop-btn")
    return f"""
    <form method="POST">
        {hidden}
        <div class="shop-form-row">
            <label>{label}</label>
            {field}
        </div>
        {submit_field}
    </form>
    """


def dashboard_page(*args, **kwargs):
    def decorator(func: typing.Callable):
        func.__dashboard_decorator_params__ = (args, kwargs)
        return func

    return decorator


class DashboardIntegration:
    bot: Red

    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        dashboard_cog.rpc.third_parties_handler.add_third_party(self)

    @dashboard_page(
        name="guild",
        description="Create, edit and manage this server's shops and items!",
        methods=("GET", "POST"),
    )
    async def shop_dashboard_guild_page(
        self, user: discord.User, guild: discord.Guild, **kwargs
    ) -> typing.Dict[str, typing.Any]:
        try:
            member = guild.get_member(user.id)
            is_owner = user.id in self.bot.owner_ids
            has_permission = is_owner or (member is not None and await self.bot.is_admin(member))
            if not has_permission:
                return {
                    "status": 0,
                    "error_code": 403,
                    "message": "You don't have permissions to manage the shop in this server.",
                }

            import wtforms

            me = guild.me
            text_channels = []
            for channel in guild.text_channels:
                try:
                    perms = channel.permissions_for(me) if me is not None else None
                except Exception:
                    perms = None
                if perms is None or perms.send_messages:
                    text_channels.append((str(channel.id), f"#{channel.name}"))
            channel_choices = [("0", "(none - disable logging)")] + text_channels

            role_choices = [("", "Select a role\u2026")]
            for role in reversed(guild.roles):
                if role.is_default() or role.managed:
                    continue
                role_choices.append((str(role.id), role.name))

            class AddShopForm(kwargs["Form"]):
                def __init__(self) -> None:
                    super().__init__(prefix="shop_add_shop_")

                name: wtforms.StringField = wtforms.StringField(
                    "Shop name",
                    validators=[wtforms.validators.DataRequired(), wtforms.validators.Length(max=100)],
                )
                description: wtforms.TextAreaField = wtforms.TextAreaField(
                    "Description", validators=[wtforms.validators.Optional(), wtforms.validators.Length(max=500)]
                )
                thumbnail: wtforms.StringField = wtforms.StringField(
                    "Thumbnail URL", validators=[wtforms.validators.Optional(), wtforms.validators.URL()]
                )
                giftable: wtforms.BooleanField = wtforms.BooleanField("Allow gifting", default=True)
                submit: wtforms.SubmitField = wtforms.SubmitField("Add shop")

            class EditShopForm(kwargs["Form"]):
                def __init__(self) -> None:
                    super().__init__(prefix="shop_edit_shop_")

                original_name: wtforms.HiddenField = wtforms.HiddenField(
                    validators=[wtforms.validators.DataRequired()]
                )
                name: wtforms.StringField = wtforms.StringField(
                    "Shop name",
                    validators=[wtforms.validators.DataRequired(), wtforms.validators.Length(max=100)],
                )
                description: wtforms.TextAreaField = wtforms.TextAreaField(
                    "Description", validators=[wtforms.validators.Optional(), wtforms.validators.Length(max=500)]
                )
                thumbnail: wtforms.StringField = wtforms.StringField(
                    "Thumbnail URL", validators=[wtforms.validators.Optional(), wtforms.validators.URL()]
                )
                giftable: wtforms.BooleanField = wtforms.BooleanField("Allow gifting")
                submit: wtforms.SubmitField = wtforms.SubmitField("Save changes")

            class AddItemForm(kwargs["Form"]):
                def __init__(self) -> None:
                    super().__init__(prefix="shop_add_item_")

                shop_name: wtforms.HiddenField = wtforms.HiddenField(
                    validators=[wtforms.validators.DataRequired()]
                )
                mode: wtforms.SelectField = wtforms.SelectField(
                    choices=[("role", "Role reward"), ("item", "Item")], default="role"
                )
                item_name: wtforms.StringField = wtforms.StringField(
                    validators=[wtforms.validators.Optional(), wtforms.validators.Length(max=100)]
                )
                role: wtforms.SelectField = wtforms.SelectField(
                    choices=role_choices, validators=[wtforms.validators.Optional()]
                )
                price: wtforms.IntegerField = wtforms.IntegerField(
                    validators=[wtforms.validators.DataRequired(), wtforms.validators.NumberRange(min=0)]
                )
                amount: wtforms.IntegerField = wtforms.IntegerField(
                    validators=[wtforms.validators.Optional(), wtforms.validators.NumberRange(min=0)]
                )
                description: wtforms.TextAreaField = wtforms.TextAreaField(
                    validators=[wtforms.validators.Optional(), wtforms.validators.Length(max=300)]
                )
                submit: wtforms.SubmitField = wtforms.SubmitField("Add item")

            class EditItemForm(kwargs["Form"]):
                def __init__(self) -> None:
                    super().__init__(prefix="shop_edit_item_")

                shop_name: wtforms.HiddenField = wtforms.HiddenField(
                    validators=[wtforms.validators.DataRequired()]
                )
                original_key: wtforms.HiddenField = wtforms.HiddenField(
                    validators=[wtforms.validators.DataRequired()]
                )
                mode: wtforms.SelectField = wtforms.SelectField(
                    choices=[("role", "Role reward"), ("item", "Item")], default="role"
                )
                item_name: wtforms.StringField = wtforms.StringField(
                    validators=[wtforms.validators.Optional(), wtforms.validators.Length(max=100)]
                )
                role: wtforms.SelectField = wtforms.SelectField(
                    choices=role_choices, validators=[wtforms.validators.Optional()]
                )
                price: wtforms.IntegerField = wtforms.IntegerField(
                    validators=[wtforms.validators.DataRequired(), wtforms.validators.NumberRange(min=0)]
                )
                amount: wtforms.IntegerField = wtforms.IntegerField(
                    validators=[wtforms.validators.Optional(), wtforms.validators.NumberRange(min=0)]
                )
                description: wtforms.TextAreaField = wtforms.TextAreaField(
                    validators=[wtforms.validators.Optional(), wtforms.validators.Length(max=300)]
                )
                submit: wtforms.SubmitField = wtforms.SubmitField("Save changes")

            class ManageForm(kwargs["Form"]):
                def __init__(self) -> None:
                    super().__init__(prefix="shop_manage_")

                shop_name: wtforms.HiddenField = wtforms.HiddenField(validators=[wtforms.validators.Optional()])
                item_key: wtforms.HiddenField = wtforms.HiddenField(validators=[wtforms.validators.Optional()])
                action: wtforms.HiddenField = wtforms.HiddenField(validators=[wtforms.validators.Optional()])
                submit: wtforms.SubmitField = wtforms.SubmitField("Go")

            class SettingsForm(kwargs["Form"]):
                def __init__(self) -> None:
                    super().__init__(prefix="shop_settings_")

                log_channel: wtforms.SelectField = wtforms.SelectField(
                    "Purchase & gift log channel", choices=channel_choices, default="0"
                )
                submit: wtforms.SubmitField = wtforms.SubmitField("Save")

            add_shop_form: AddShopForm = AddShopForm()
            edit_shop_form: EditShopForm = EditShopForm()
            add_item_form: AddItemForm = AddItemForm()
            edit_item_form: EditItemForm = EditItemForm()
            manage_form: ManageForm = ManageForm()
            settings_form: SettingsForm = SettingsForm()
            notifications: typing.List[typing.Dict[str, str]] = []

            posted_fields = {}
            if kwargs.get("method") == "POST":
                posted_fields = kwargs.get("data", {}).get("form", {}) or {}

            if any(str(key).startswith("shop_manage_") for key in posted_fields):
                return await self._handle_shop_manage_action(guild, manage_form, kwargs["request_url"])

            if any(str(key).startswith("shop_settings_") for key in posted_fields):
                return await self._handle_shop_settings_submit(guild, settings_form, kwargs["request_url"])

            if any(str(key).startswith("shop_edit_shop_") for key in posted_fields):
                result = await self._handle_edit_shop_submit(guild, edit_shop_form, kwargs["request_url"])
                if result is not None:
                    return result
                notifications.append(
                    {"message": "Please fix the highlighted fields and try again.", "category": "error"}
                )
                return await self._render_shop_page(
                    guild, add_shop_form, edit_shop_form, add_item_form, edit_item_form,
                    manage_form, settings_form, notifications,
                )

            if any(str(key).startswith("shop_add_shop_") for key in posted_fields):
                result = await self._handle_add_shop_submit(guild, add_shop_form, kwargs["request_url"])
                if result is not None:
                    return result
                notifications.append(
                    {"message": "Please fix the highlighted fields and try again.", "category": "error"}
                )
                return await self._render_shop_page(
                    guild, add_shop_form, edit_shop_form, add_item_form, edit_item_form,
                    manage_form, settings_form, notifications,
                )

            if any(str(key).startswith("shop_edit_item_") for key in posted_fields):
                result = await self._handle_edit_item_submit(guild, edit_item_form, kwargs["request_url"])
                if result is not None:
                    return result
                notifications.append(
                    {"message": "Please fix the highlighted fields and try again.", "category": "error"}
                )
                return await self._render_shop_page(
                    guild, add_shop_form, edit_shop_form, add_item_form, edit_item_form,
                    manage_form, settings_form, notifications,
                )

            if any(str(key).startswith("shop_add_item_") for key in posted_fields):
                result = await self._handle_add_item_submit(guild, add_item_form, kwargs["request_url"])
                if result is not None:
                    return result
                notifications.append(
                    {"message": "Please fix the highlighted fields and try again.", "category": "error"}
                )
                return await self._render_shop_page(
                    guild, add_shop_form, edit_shop_form, add_item_form, edit_item_form,
                    manage_form, settings_form, notifications,
                )

            return await self._render_shop_page(
                guild, add_shop_form, edit_shop_form, add_item_form, edit_item_form,
                manage_form, settings_form, notifications,
            )
        except Exception:
            log.exception("Shop: unhandled error building the dashboard guild page")
            return {
                "status": 0,
                "notifications": [
                    {
                        "message": (
                            "The Shop dashboard page hit an unexpected error. "
                            "Check the bot's console/logs for the full traceback "
                            "(logger name: red.shop.dashboard)."
                        ),
                        "category": "error",
                    }
                ],
                "web_content": {
                    "source": _load_template(),
                    "standalone": True,
                    "setup_error": (
                        "This page failed to build normally - see the notification above "
                        "and the bot's console/logs for details."
                    ),
                    "add_shop_form_html": "",
                    "edit_shop_form_html": "",
                    "add_item_form_html": "",
                    "edit_item_form_html": "",
                    "manage_form_html": "",
                    "settings_form_html": "",
                    "shops_rows": [],
                },
            }

    async def _handle_add_shop_submit(
        self, guild: discord.Guild, form, request_url: str
    ) -> typing.Optional[typing.Dict[str, typing.Any]]:
        if not form.validate_on_submit():
            return None
        notifications: typing.List[typing.Dict[str, str]] = []
        name = form.name.data.strip()
        guild_conf = self.config.guild(guild)
        shops = await guild_conf.shops()
        if name in shops:
            notifications.append({"message": f"A shop named '{name}' already exists.", "category": "error"})
            return {"status": 0, "notifications": notifications, "redirect_url": request_url}
        shops[name] = {
            "description": (form.description.data or "").strip(),
            "thumbnail": (form.thumbnail.data or "").strip(),
            "giftable": bool(form.giftable.data),
            "stock": {},
        }
        await guild_conf.shops.set(shops)
        notifications.append({"message": f"Shop '{name}' added!", "category": "success"})
        return {"status": 0, "notifications": notifications, "redirect_url": request_url}

    async def _handle_edit_shop_submit(
        self, guild: discord.Guild, form, request_url: str
    ) -> typing.Optional[typing.Dict[str, typing.Any]]:
        if not form.validate_on_submit():
            return None
        notifications: typing.List[typing.Dict[str, str]] = []
        original_name = form.original_name.data
        new_name = form.name.data.strip()
        guild_conf = self.config.guild(guild)
        shops = await guild_conf.shops()
        if original_name not in shops:
            notifications.append({"message": f"Shop '{original_name}' no longer exists.", "category": "warning"})
            return {"status": 0, "notifications": notifications, "redirect_url": request_url}
        stock = shops[original_name].get("stock", {})
        if new_name != original_name:
            del shops[original_name]
        shops[new_name] = {
            "description": (form.description.data or "").strip(),
            "thumbnail": (form.thumbnail.data or "").strip(),
            "giftable": bool(form.giftable.data),
            "stock": stock,
        }
        await guild_conf.shops.set(shops)
        notifications.append({"message": f"Shop '{new_name}' updated.", "category": "success"})
        return {"status": 0, "notifications": notifications, "redirect_url": request_url}

    async def _handle_add_item_submit(
        self, guild: discord.Guild, form, request_url: str
    ) -> typing.Optional[typing.Dict[str, typing.Any]]:
        if not form.validate_on_submit():
            return None
        notifications: typing.List[typing.Dict[str, str]] = []
        shop_name = form.shop_name.data
        guild_conf = self.config.guild(guild)
        shops = await guild_conf.shops()
        if shop_name not in shops:
            notifications.append({"message": f"Shop '{shop_name}' no longer exists.", "category": "warning"})
            return {"status": 0, "notifications": notifications, "redirect_url": request_url}
        stock = shops[shop_name].setdefault("stock", {})
        if form.mode.data == "role":
            try:
                role_id = int(form.role.data)
            except (TypeError, ValueError):
                role_id = None
            role_obj = guild.get_role(role_id) if role_id else None
            if not role_obj:
                notifications.append({"message": "Please select a valid role.", "category": "error"})
                return {"status": 0, "notifications": notifications, "redirect_url": request_url}
            key = role_obj.name
            stock[key] = {
                "price": form.price.data,
                "amount": form.amount.data,
                "description": (form.description.data or "").strip(),
                "role_id": role_obj.id,
            }
        else:
            item_name = (form.item_name.data or "").strip()
            if not item_name:
                notifications.append({"message": "Item name cannot be empty.", "category": "error"})
                return {"status": 0, "notifications": notifications, "redirect_url": request_url}
            key = item_name
            stock[key] = {
                "price": form.price.data,
                "amount": form.amount.data,
                "description": (form.description.data or "").strip(),
            }
        await guild_conf.shops.set(shops)
        notifications.append({"message": f"Item '{key}' added to '{shop_name}'.", "category": "success"})
        return {"status": 0, "notifications": notifications, "redirect_url": request_url}

    async def _handle_edit_item_submit(
        self, guild: discord.Guild, form, request_url: str
    ) -> typing.Optional[typing.Dict[str, typing.Any]]:
        if not form.validate_on_submit():
            return None
        notifications: typing.List[typing.Dict[str, str]] = []
        shop_name = form.shop_name.data
        original_key = form.original_key.data
        guild_conf = self.config.guild(guild)
        shops = await guild_conf.shops()
        if shop_name not in shops:
            notifications.append({"message": f"Shop '{shop_name}' no longer exists.", "category": "warning"})
            return {"status": 0, "notifications": notifications, "redirect_url": request_url}
        stock = shops[shop_name].setdefault("stock", {})
        if original_key not in stock:
            notifications.append({"message": f"Item '{original_key}' no longer exists.", "category": "warning"})
            return {"status": 0, "notifications": notifications, "redirect_url": request_url}

        if form.mode.data == "role":
            try:
                role_id = int(form.role.data)
            except (TypeError, ValueError):
                role_id = None
            role_obj = guild.get_role(role_id) if role_id else None
            if not role_obj:
                notifications.append({"message": "Please select a valid role.", "category": "error"})
                return {"status": 0, "notifications": notifications, "redirect_url": request_url}
            key = role_obj.name
            if key != original_key:
                del stock[original_key]
            stock[key] = {
                "price": form.price.data,
                "amount": form.amount.data,
                "description": (form.description.data or "").strip(),
                "role_id": role_obj.id,
            }
        else:
            item_name = (form.item_name.data or "").strip()
            if not item_name:
                notifications.append({"message": "Item name cannot be empty.", "category": "error"})
                return {"status": 0, "notifications": notifications, "redirect_url": request_url}
            key = item_name
            if key != original_key:
                del stock[original_key]
            stock[key] = {
                "price": form.price.data,
                "amount": form.amount.data,
                "description": (form.description.data or "").strip(),
            }
        await guild_conf.shops.set(shops)
        notifications.append({"message": f"Item '{key}' updated.", "category": "success"})
        return {"status": 0, "notifications": notifications, "redirect_url": request_url}

    async def _handle_shop_settings_submit(
        self, guild: discord.Guild, form, request_url: str
    ) -> typing.Dict[str, typing.Any]:
        notifications: typing.List[typing.Dict[str, str]] = []
        if form.validate_on_submit():
            guild_conf = self.config.guild(guild)
            raw = form.log_channel.data
            if raw in (None, "", "0"):
                await guild_conf.log_channel.set(None)
                notifications.append({"message": "Shop logging disabled.", "category": "success"})
            else:
                try:
                    channel_id = int(raw)
                except (TypeError, ValueError):
                    channel_id = None
                channel = guild.get_channel(channel_id) if channel_id else None
                if not channel:
                    notifications.append({"message": "Please select a valid channel.", "category": "error"})
                else:
                    await guild_conf.log_channel.set(channel.id)
                    notifications.append(
                        {"message": f"Shop logs will now be posted in #{channel.name}.", "category": "success"}
                    )
        else:
            notifications.append({"message": "Please select a valid channel and try again.", "category": "error"})
        return {"status": 0, "notifications": notifications, "redirect_url": request_url}

    async def _handle_shop_manage_action(
        self, guild: discord.Guild, form, request_url: str
    ) -> typing.Dict[str, typing.Any]:
        notifications: typing.List[typing.Dict[str, str]] = []
        if form.validate_on_submit():
            shop_name = form.shop_name.data
            item_key = form.item_key.data
            action = form.action.data
            guild_conf = self.config.guild(guild)
            shops = await guild_conf.shops()
            if action == "delete_shop":
                if shop_name in shops:
                    del shops[shop_name]
                    await guild_conf.shops.set(shops)
                    notifications.append({"message": f"Shop '{shop_name}' deleted.", "category": "success"})
                else:
                    notifications.append({"message": "That shop no longer exists.", "category": "warning"})
            elif action == "delete_item":
                stock = shops.get(shop_name, {}).get("stock", {})
                if item_key in stock:
                    del stock[item_key]
                    await guild_conf.shops.set(shops)
                    notifications.append({"message": f"Item '{item_key}' deleted.", "category": "success"})
                else:
                    notifications.append({"message": "That item no longer exists.", "category": "warning"})
            else:
                notifications.append({"message": f"Unknown action '{action}'.", "category": "error"})
        else:
            notifications.append({"message": "That action could not be processed.", "category": "error"})
        return {"status": 0, "notifications": notifications, "redirect_url": request_url}

    async def _render_shop_page(
        self,
        guild: discord.Guild,
        add_shop_form,
        edit_shop_form,
        add_item_form,
        edit_item_form,
        manage_form,
        settings_form,
        notifications: typing.List[typing.Dict[str, str]],
    ) -> typing.Dict[str, typing.Any]:
        guild_conf = self.config.guild(guild)
        shops = await guild_conf.shops()
        log_channel_id = await guild_conf.log_channel()

        rows = []
        for shop_name, shop_data in sorted(shops.items()):
            items = []
            for item_key, entry in (shop_data.get("stock") or {}).items():
                role_id = entry.get("role_id")
                role_obj = guild.get_role(role_id) if role_id else None
                is_role = bool(role_id)
                items.append(
                    {
                        "key": item_key,
                        "label": (role_obj.name if role_obj else item_key) if is_role else item_key,
                        "price": entry.get("price", 0),
                        "amount": entry.get("amount"),
                        "stock_label": "Unlimited" if entry.get("amount") is None else entry.get("amount"),
                        "description": entry.get("description", ""),
                        "mode": "role" if is_role else "item",
                        "item_name": "" if is_role else item_key,
                        "role_id": role_id or 0,
                        "role_missing": is_role and role_obj is None,
                    }
                )
            rows.append(
                {
                    "name": shop_name,
                    "description": shop_data.get("description", ""),
                    "thumbnail": shop_data.get("thumbnail", ""),
                    "giftable": shop_data.get("giftable", True),
                    "stock_items": items,
                }
            )

        role_data = [
            (str(role.id), role.name, _role_color_hex(role))
            for role in reversed(guild.roles)
            if not role.is_default() and not role.managed
        ]

        log_channel = guild.get_channel(log_channel_id) if log_channel_id else None

        return {
            "status": 0,
            "notifications": notifications,
            "web_content": {
                "source": _load_template(),
                "standalone": True,
                "add_shop_form_html": _render_add_shop_form_html(add_shop_form),
                "edit_shop_form_html": _render_edit_shop_form_html(edit_shop_form),
                "add_item_form_html": _render_add_item_form_html(add_item_form, role_data),
                "edit_item_form_html": _render_edit_item_form_html(edit_item_form, role_data),
                "manage_form_html": _render_manage_form_html(manage_form),
                "settings_form_html": _render_settings_form_html(settings_form),
                "shops_rows": rows,
                "log_channel_name": f"#{log_channel.name}" if log_channel else "None",
            },
        }
