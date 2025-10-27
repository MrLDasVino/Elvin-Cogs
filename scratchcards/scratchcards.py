from redbot.core import commands, Config, checks, bank
from redbot.core.utils.chat_formatting import box
import discord
from discord import ui
import asyncio
import uuid
import random
import typing

CONFIG_ID = 0xBADA55C0FFEE1234
COG_VERSION = "1.1.6"

DEFAULT_GUILD = {
    "enabled": True,
    "max_daily": 10,
    "instant_reveal": True,
    "cards": {}
}


async def _disable_view_later(message: discord.Message, view: ui.View, timeout: int = 60):
    await asyncio.sleep(timeout)
    try:
        view.stop()
        view.disable_all_items()
        await message.edit(view=view)
    except Exception:
        # ignore edit failures (message deleted, ephemeral gone, permissions, etc.)
        pass


class ConfirmView(ui.View):
    def __init__(self, author: discord.User, timeout: int = 60):
        super().__init__(timeout=timeout)
        self.author = author
        self.result: typing.Optional[bool] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author.id

    @ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        self.result = True
        await interaction.response.defer()
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        self.result = False
        await interaction.response.defer()
        self.stop()


class CardSelect(ui.Select):
    def __init__(self, author: discord.User, options: typing.List[discord.SelectOption], timeout: int = 60):
        super().__init__(placeholder="Choose a scratch card...", min_values=1, max_values=1, options=options)
        self.author = author
        self.selected_key: typing.Optional[str] = None

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("This menu isn't for you.", ephemeral=True)
            return
        self.selected_key = self.values[0]
        await interaction.response.defer()
        self.view.stop()


class AdminCardSelect(ui.Select):
    def __init__(self, cog, guild: discord.Guild, author: discord.User, options: typing.List[discord.SelectOption]):
        super().__init__(placeholder="Select a card to manage", min_values=1, max_values=1, options=options)
        self.cog = cog
        self.guild = guild
        self.author = author

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("This panel is for the invoker only.", ephemeral=True)
            return
        chosen_key = self.values[0]
        await interaction.response.defer(ephemeral=True)
        asyncio.create_task(self.cog._card_manager(interaction, None, chosen_key))


class CardModal(ui.Modal, title="Create / Edit Card"):
    key = ui.TextInput(label="Card key (internal, no spaces)", placeholder="basic", required=True, max_length=32)
    display = ui.TextInput(label="Display name", placeholder="Basic Scratch", required=True, max_length=64)
    price = ui.TextInput(label="Price (int)", placeholder="100", required=True, max_length=20)

    def __init__(self, cog=None, guild: discord.Guild = None, existing: dict = None):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.existing = existing

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price_val = int(self.price.value.strip())
        except Exception:
            await interaction.response.send_message("Invalid numeric input.", ephemeral=True)
            return

        if not self.cog or not self.guild:
            await interaction.response.send_message("Internal error: missing context.", ephemeral=True)
            return

        payload = {
            "key": self.key.value.strip(),
            "name": self.display.value.strip(),
            "price": max(0, price_val)
        }

        gc = await self.cog.get_guild_conf(self.guild)
        cards_local = gc.get("cards", {})
        key = payload["key"]
        if key in cards_local:
            await interaction.response.send_message("Card key already exists.", ephemeral=True)
            return

        cards_local[key] = {"name": payload["name"], "price": payload["price"], "prizes": []}
        gc["cards"] = cards_local
        await self.cog.config.guild(self.guild).set(gc)
        await interaction.response.send_message(f"Created card {key}.", ephemeral=True)


class PrizeModal(ui.Modal, title="Create / Edit Prize"):
    name = ui.TextInput(label="Prize name", placeholder="Small Win", required=True, max_length=64)
    value = ui.TextInput(label="Prize value (int)", placeholder="50", required=True, max_length=20)
    weight = ui.TextInput(label="Weight (int)", placeholder="100", required=True, max_length=10)
    tag = ui.TextInput(label="Rarity tag (optional)", placeholder="common", required=False, max_length=32)

    def __init__(self, cog=None, guild: discord.Guild = None, card_key: str = None, existing: dict = None):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.card_key = card_key
        self.existing = existing

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.value.value.strip())
            w = int(self.weight.value.strip())
        except Exception:
            await interaction.response.send_message("Invalid numeric input.", ephemeral=True)
            return

        if not self.cog or not self.guild or not self.card_key:
            await interaction.response.send_message("Internal error: missing context.", ephemeral=True)
            return

        prize_id = str(uuid.uuid4())[:8]
        prize = {
            "id": prize_id,
            "name": self.name.value.strip(),
            "value": max(0, val),
            "weight": max(1, w),
            "tag": self.tag.value.strip() or None
        }

        gc = await self.cog.get_guild_conf(self.guild)
        cards_local = gc.get("cards", {})
        card = cards_local.get(self.card_key)
        if card is None:
            await interaction.response.send_message("Card no longer exists.", ephemeral=True)
            return

        card.setdefault("prizes", []).append(prize)
        cards_local[self.card_key] = card
        gc["cards"] = cards_local
        await self.cog.config.guild(self.guild).set(gc)
        await interaction.response.send_message(f"Added prize {prize_id}.", ephemeral=True)


class PrizeEditModal(ui.Modal, title="Edit Prize (will save on submit)"):
    name = ui.TextInput(label="Prize name", required=True, max_length=64)
    value = ui.TextInput(label="Prize value (int)", required=True, max_length=20)
    weight = ui.TextInput(label="Weight (int)", required=True, max_length=10)
    tag = ui.TextInput(label="Rarity tag (optional)", required=False, max_length=32)

    def __init__(self, cog, guild: discord.Guild, card_key: str, prize_id: str, existing: dict):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.card_key = card_key
        self.prize_id = prize_id
        self.existing = existing
        self.name.default = existing.get("name", "")
        self.value.default = str(existing.get("value", 0))
        self.weight.default = str(existing.get("weight", 1))
        self.tag.default = existing.get("tag") or ""

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.value.value.strip())
            w = int(self.weight.value.strip())
        except Exception:
            await interaction.response.send_message("Invalid numeric input.", ephemeral=True)
            return
        gc = await self.cog.get_guild_conf(self.guild)
        cards = gc.get("cards", {})
        card = cards.get(self.card_key)
        if not card:
            await interaction.response.send_message("Card no longer exists.", ephemeral=True)
            return
        prizes = card.get("prizes", [])
        updated = False
        for p in prizes:
            if p.get("id") == self.prize_id:
                p["name"] = self.name.value.strip()
                p["value"] = max(0, val)
                p["weight"] = max(1, w)
                p["tag"] = self.tag.value.strip() or None
                updated = True
                break
        if not updated:
            await interaction.response.send_message("Prize not found (may have been removed).", ephemeral=True)
            return
        card["prizes"] = prizes
        cards[self.card_key] = card
        gc["cards"] = cards
        await self.cog.config.guild(self.guild).set(gc)
        await interaction.response.send_message(f"Prize {self.prize_id} updated.", ephemeral=True)


class PrizeSelect(ui.Select):
    def __init__(self, cog, guild: discord.Guild, card_key: str, prizes: typing.List[dict], author: discord.User):
        options = [discord.SelectOption(label=f"{p.get('name')} ({p.get('id')})", value=p.get("id")) for p in prizes]
        super().__init__(placeholder="Select prize to edit", options=options, min_values=1, max_values=1)
        self.cog = cog
        self.guild = guild
        self.card_key = card_key
        self.prizes = {p.get("id"): p for p in prizes}
        self.author = author

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("This menu isn't for you.", ephemeral=True)
            return
        prize_id = self.values[0]
        prize = self.prizes.get(prize_id)
        if not prize:
            await interaction.response.send_message("Prize not found.", ephemeral=True)
            return
        modal = PrizeEditModal(self.cog, self.guild, self.card_key, prize_id, prize)
        await interaction.response.send_modal(modal)
        # DO NOT stop the view so select remains reusable


class ScratchCardExtended(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=CONFIG_ID)
        self.config.register_guild(**DEFAULT_GUILD)
        self._buy_lock = asyncio.Lock()

    async def get_guild_conf(self, guild: discord.Guild):
        return await self.config.guild(guild).all()

    def _card_options_from_conf(self, guild_conf: dict) -> typing.List[discord.SelectOption]:
        opts = []
        cards = guild_conf.get("cards", {})
        for k, v in cards.items():
            label = f"{v.get('name')} — {v.get('price')}"
            desc = f"prizes: {len(v.get('prizes', []))}; price {v.get('price')}"
            opts.append(discord.SelectOption(label=label[:100], value=k, description=desc[:100]))
        return opts

    def _weighted_prize_choice(self, prizes: typing.List[dict]) -> dict:
        if not prizes:
            return {"name": "No Prize", "value": 0, "weight": 1, "tag": None, "id": "none"}
        weights = [p.get("weight", 1) for p in prizes]
        chosen = random.choices(prizes, weights=weights, k=1)[0]
        return chosen

    @commands.group()
    async def scratch(self, ctx: commands.Context):
        """Scratch card commands"""

    @scratch.command()
    async def list(self, ctx: commands.Context):
        guild_conf = await self.get_guild_conf(ctx.guild)
        cards = guild_conf.get("cards", {})
        if not cards:
            await ctx.send("No scratch cards configured for this server.")
            return
        lines = []
        for k, v in cards.items():
            prize_count = len(v.get("prizes", []))
            lines.append(f"{k} | {v.get('name')} | Price: {v.get('price')} | Prizes: {prize_count}")
        await ctx.send(box("\n".join(lines)))

    @scratch.command()
    async def buy(self, ctx: commands.Context):
        guild_conf = await self.get_guild_conf(ctx.guild)
        if not guild_conf.get("enabled", True):
            await ctx.send("Scratch cards are disabled in this server.")
            return
        cards = guild_conf.get("cards", {})
        if not cards:
            await ctx.send("No scratch cards available.")
            return

        select_opts = self._card_options_from_conf(guild_conf)
        select = CardSelect(ctx.author, select_opts)
        view = ui.View(timeout=60)
        view.add_item(select)
        msg = await ctx.send("Choose a scratch card to buy:", view=view)
        asyncio.create_task(_disable_view_later(msg, view, 60))
        await view.wait()
        if select.selected_key is None:
            return

        card_key = select.selected_key
        card = cards.get(card_key)
        if card is None:
            return
        price = int(card.get("price", 0))
        currency = await bank.get_currency_name(ctx.guild)

        can_spend = await bank.can_spend(ctx.author, price)
        if not can_spend:
            bal = await bank.get_balance(ctx.author)
            await ctx.send(f"You need {price} {currency} but have {bal} {currency}.")
            return

        confirm = ConfirmView(ctx.author, timeout=60)
        confirm_msg = await ctx.send(f"Confirm purchase of **{card.get('name')}** for **{price} {currency}**?", view=confirm)
        asyncio.create_task(_disable_view_later(confirm_msg, confirm, 60))
        await confirm.wait()
        if not confirm.result:
            return

        async with self._buy_lock:
            try:
                await bank.withdraw_credits(ctx.author, price)
            except Exception as e:
                await ctx.send(f"Purchase failed: {e}")
                return

            prizes = card.get("prizes", [])
            chosen = self._weighted_prize_choice(prizes)
            prize_value = int(chosen.get("value", 0))
            prize_name = chosen.get("name", "Prize")

            try:
                if prize_value > 0:
                    await bank.deposit_credits(ctx.author, prize_value)
            except Exception as e:
                try:
                    await bank.deposit_credits(ctx.author, price)
                except Exception:
                    pass
                await ctx.send(f"Award failed, purchase refunded: {e}")
                return

            currency = await bank.get_currency_name(ctx.guild)
            await ctx.send(f"You bought **{card.get('name')}** for **{price} {currency}** and won **{prize_value} {currency}** ({prize_name})!")

    @scratch.command(name="manage")
    @checks.mod_or_permissions(manage_guild=True)
    async def manage(self, ctx: commands.Context):
        guild_conf = await self.get_guild_conf(ctx.guild)
        cards = guild_conf.get("cards", {})

        desc_lines = ["Admin panel — create or edit cards and manage prizes."]
        if cards:
            desc_lines.append("Existing cards:")
            for k, v in cards.items():
                desc_lines.append(f"- {k}: {v.get('name')} (Price {v.get('price')}) Prizes: {len(v.get('prizes', []))}")
        msg_text = "\n".join(desc_lines)

        view = ui.View(timeout=60)

        async def create_card_cb(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("This panel is for the invoker only.", ephemeral=True)
                return
            modal = CardModal(cog=self, guild=ctx.guild)
            await interaction.response.send_modal(modal)

        async def remove_card_cb(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("This panel is for the invoker only.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)

            gc = await self.get_guild_conf(ctx.guild)
            cards_local = gc.get("cards", {})
            if not cards_local:
                return
            opts = [discord.SelectOption(label=f"{v.get('name')} ({k})", value=k) for k, v in cards_local.items()]
            sel = ui.Select(placeholder="Select a card to remove", options=opts, min_values=1, max_values=1)
            sel_view = ui.View(timeout=60)
            sel_view.add_item(sel)

            follow_msg = await interaction.followup.send("Select a card to remove:", view=sel_view, ephemeral=True)
            asyncio.create_task(_disable_view_later(follow_msg, sel_view, 60))
            await sel_view.wait()
            if not getattr(sel, "values", None):
                return
            key = sel.values[0]
            cards_local.pop(key, None)
            gc["cards"] = cards_local
            await self.config.guild(ctx.guild).set(gc)
            await interaction.followup.send(f"Removed card {key}.", ephemeral=True)

        create_btn = ui.Button(label="Create Card", style=discord.ButtonStyle.green)
        remove_btn = ui.Button(label="Remove Card", style=discord.ButtonStyle.red)

        create_btn.callback = create_card_cb
        remove_btn.callback = remove_card_cb

        view.add_item(create_btn)
        view.add_item(remove_btn)

        if cards:
            opts = [discord.SelectOption(label=f"{v.get('name')} ({k})", value=k) for k, v in cards.items()]
            admin_sel = AdminCardSelect(self, ctx.guild, ctx.author, opts)
            view.add_item(admin_sel)

        panel_msg = await ctx.send(msg_text, view=view)
        asyncio.create_task(_disable_view_later(panel_msg, view, 60))

    async def _card_manager(self, interaction: discord.Interaction, ctx: typing.Optional[commands.Context], card_key: str):
        guild = interaction.guild if interaction and interaction.guild else (ctx.guild if ctx else None)
        if not guild:
            try:
                await interaction.followup.send("Internal error: missing guild context.", ephemeral=True)
            except Exception:
                pass
            return

        gc = await self.get_guild_conf(guild)
        cards_local = gc.get("cards", {})
        card = cards_local.get(card_key)
        if not card:
            try:
                await interaction.followup.send("Card not found.", ephemeral=True)
            except Exception:
                pass
            return

        def build_desc():
            lines = [f"Managing card {card_key}: {card.get('name')} (Price {card.get('price')})"]
            prizes = card.get("prizes", [])
            if not prizes:
                lines.append("No prizes configured yet.")
            else:
                lines.append("Prizes:")
                for p in prizes:
                    lines.append(f"- {p.get('id')} | {p.get('name')} | value {p.get('value')} | weight {p.get('weight')} | tag {p.get('tag')}")
            return "\n".join(lines)

        view = ui.View(timeout=60)

        async def add_prize_cb(i: discord.Interaction):
            opener_id = interaction.user.id if interaction else (ctx.author.id if ctx else None)
            if i.user.id != opener_id:
                await i.response.send_message("This manager is for the admin who opened it.", ephemeral=True)
                return
            modal = PrizeModal(cog=self, guild=guild, card_key=card_key)
            await i.response.send_modal(modal)

        async def edit_prize_cb(i: discord.Interaction):
            opener_id = interaction.user.id if interaction else (ctx.author.id if ctx else None)
            if i.user.id != opener_id:
                await i.response.send_message("This manager is for the admin who opened it.", ephemeral=True)
                return
            prizes = card.get("prizes", [])
            if not prizes:
                await i.response.send_message("No prizes to edit.", ephemeral=True)
                return
            sel = PrizeSelect(self, guild, card_key, prizes, i.user)
            sel_view = ui.View(timeout=60)
            sel_view.add_item(sel)
            follow_msg = await i.response.send_message("Select a prize to edit:", view=sel_view, ephemeral=True)
            asyncio.create_task(_disable_view_later(follow_msg, sel_view, 60))
            # return immediately so select interaction and modal open correctly

        async def remove_prize_cb(i: discord.Interaction):
            opener_id = interaction.user.id if interaction else (ctx.author.id if ctx else None)
            if i.user.id != opener_id:
                await i.response.send_message("This manager is for the admin who opened it.", ephemeral=True)
                return
            prizes = card.get("prizes", [])
            if not prizes:
                await i.response.send_message("No prizes to remove.", ephemeral=True)
                return
            opts = [discord.SelectOption(label=f"{p.get('name')} ({p.get('id')})", value=p.get('id')) for p in prizes]
            sel = ui.Select(placeholder="Select prize(s) to remove", options=opts, min_values=1, max_values=25)
            sel_view = ui.View(timeout=60)
            sel_view.add_item(sel)
            follow_msg = await i.response.send_message("Select prize(s) to remove:", view=sel_view, ephemeral=True)
            asyncio.create_task(_disable_view_later(follow_msg, sel_view, 60))
            await sel_view.wait()
            if not getattr(sel, "values", None):
                return
            remove_ids = set(sel.values)
            card["prizes"] = [p for p in prizes if p.get("id") not in remove_ids]
            gc = await self.get_guild_conf(guild)
            cards_local = gc.get("cards", {})
            cards_local[card_key] = card
            gc["cards"] = cards_local
            await self.config.guild(guild).set(gc)
            await i.followup.send(f"Removed {len(remove_ids)} prize(s).", ephemeral=True)

        async def view_details_cb(i: discord.Interaction):
            opener_id = interaction.user.id if interaction else (ctx.author.id if ctx else None)
            if i.user.id != opener_id:
                await i.response.send_message("This manager is for the admin who opened it.", ephemeral=True)
                return
            await i.response.send_message(box(build_desc()), ephemeral=True)

        add_btn = ui.Button(label="Add Prize", style=discord.ButtonStyle.green)
        edit_btn = ui.Button(label="Edit Prize", style=discord.ButtonStyle.blurple)
        remove_btn = ui.Button(label="Remove Prize(s)", style=discord.ButtonStyle.red)
        view_btn = ui.Button(label="View Details", style=discord.ButtonStyle.gray)

        add_btn.callback = add_prize_cb
        edit_btn.callback = edit_prize_cb
        remove_btn.callback = remove_prize_cb
        view_btn.callback = view_details_cb

        view.add_item(add_btn)
        view.add_item(edit_btn)
        view.add_item(remove_btn)
        view.add_item(view_btn)

        try:
            manager_msg = await interaction.followup.send(f"Card manager opened for {card_key}.", view=view, ephemeral=True)
            asyncio.create_task(_disable_view_later(manager_msg, view, 60))
        except Exception:
            try:
                # fallback to channel send if followup fails
                manager_msg = await interaction.channel.send(f"Card manager opened for {card_key}.", view=view)
                asyncio.create_task(_disable_view_later(manager_msg, view, 60))
            except Exception:
                pass

    @checks.mod_or_permissions(manage_guild=True)
    @scratch.command()
    async def setenabled(self, ctx: commands.Context, enabled: bool):
        gc = await self.get_guild_conf(ctx.guild)
        gc["enabled"] = bool(enabled)
        await self.config.guild(ctx.guild).set(gc)
        await ctx.send(f"Enabled set to {bool(enabled)}")

    @scratch.command()
    async def version(self, ctx: commands.Context):
        await ctx.send(COG_VERSION)
