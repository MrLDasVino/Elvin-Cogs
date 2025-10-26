from redbot.core import commands, Config, checks, bank
from redbot.core.utils.chat_formatting import box
import discord
from discord import ui
import asyncio
import uuid
import random
import typing

# Unique identifier for this cog's Config
CONFIG_ID = 0xBADA55C0FFEE1234

COG_VERSION = "1.1.2"

DEFAULT_GUILD = {
    "enabled": True,
    "max_daily": 10,
    "instant_reveal": True,
    "cards": {}
}


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
    def __init__(self, author: discord.User, options: typing.List[discord.SelectOption]):
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


class CardModal(ui.Modal, title="Create / Edit Card"):
    key = ui.TextInput(label="Card key (internal, no spaces)", placeholder="basic", required=True, max_length=32)
    display = ui.TextInput(label="Display name", placeholder="Basic Scratch", required=True, max_length=64)
    price = ui.TextInput(label="Price (int)", placeholder="100", required=True, max_length=20)

    def __init__(self, existing: dict = None):
        super().__init__()
        self.existing = existing
        self.result_payload: typing.Optional[dict] = None

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price_val = int(self.price.value.strip())
        except Exception:
            await interaction.response.send_message("Invalid numeric input.", ephemeral=True)
            return
        self.result_payload = {
            "key": self.key.value.strip(),
            "name": self.display.value.strip(),
            "price": max(0, price_val)
        }
        await interaction.response.defer()
        self.stop()


class PrizeModal(ui.Modal, title="Create / Edit Prize"):
    name = ui.TextInput(label="Prize name", placeholder="Small Win", required=True, max_length=64)
    value = ui.TextInput(label="Prize value (int)", placeholder="50", required=True, max_length=20)
    weight = ui.TextInput(label="Weight (int)", placeholder="100", required=True, max_length=10)
    tag = ui.TextInput(label="Rarity tag (optional)", placeholder="common", required=False, max_length=32)

    def __init__(self, existing: dict = None):
        super().__init__()
        self.existing = existing
        self.result_payload: typing.Optional[dict] = None

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.value.value.strip())
            w = int(self.weight.value.strip())
        except Exception:
            await interaction.response.send_message("Invalid numeric input.", ephemeral=True)
            return
        self.result_payload = {
            "name": self.name.value.strip(),
            "value": max(0, val),
            "weight": max(1, w),
            "tag": self.tag.value.strip() or None
        }
        await interaction.response.defer()
        self.stop()


class ScratchCardExtended(commands.Cog):
    """Scratch Card extended cog — multi-prize cards with admin UI and bank integration"""

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
        """List available scratch cards"""
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
        """Buy a scratch card — choose from a dropdown and confirm"""
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
        await ctx.send("Choose a scratch card to buy:", view=view)
        await view.wait()
        if select.selected_key is None:
            await ctx.send("No selection made, cancelled.")
            return

        card_key = select.selected_key
        card = cards.get(card_key)
        if card is None:
            await ctx.send("Selected card not found, cancelled.")
            return
        price = int(card.get("price", 0))
        currency = await bank.get_currency_name(ctx.guild)

        can_spend = await bank.can_spend(ctx.author, price)
        if not can_spend:
            bal = await bank.get_balance(ctx.author)
            await ctx.send(f"You need {price} {currency} but have {bal} {currency}.")
            return

        confirm = ConfirmView(ctx.author)
        await ctx.send(f"Confirm purchase of **{card.get('name')}** for **{price} {currency}**?", view=confirm)
        await confirm.wait()
        if not confirm.result:
            await ctx.send("Purchase cancelled.")
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
        """Open the admin panel to create/edit cards and manage prizes"""
        guild_conf = await self.get_guild_conf(ctx.guild)
        cards = guild_conf.get("cards", {})

        desc_lines = ["Admin panel — create or edit cards and manage prizes."]
        if cards:
            desc_lines.append("Existing cards:")
            for k, v in cards.items():
                desc_lines.append(f"- {k}: {v.get('name')} (Price {v.get('price')}) Prizes: {len(v.get('prizes', []))}")
        msg = "\n".join(desc_lines)

        view = ui.View(timeout=300)

        async def create_card_cb(interaction: discord.Interaction, button: ui.Button):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("This panel is for the invoker only.", ephemeral=True)
                return
            modal = CardModal()
            await interaction.response.send_modal(modal)
            await modal.wait()
            if not getattr(modal, "result_payload", None):
                await interaction.followup.send("Creation cancelled or timed out.", ephemeral=True)
                return
            payload = modal.result_payload
            key = payload["key"]
            gc = await self.get_guild_conf(ctx.guild)
            cards_local = gc.get("cards", {})
            if key in cards_local:
                await interaction.followup.send("Card key already exists.", ephemeral=True)
                return
            cards_local[key] = {
                "name": payload["name"],
                "price": payload["price"],
                "prizes": []
            }
            gc["cards"] = cards_local
            await self.config.guild(ctx.guild).set(gc)
            await interaction.followup.send(f"Created card {key}.", ephemeral=True)

        async def manage_card_cb(interaction: discord.Interaction, button: ui.Button):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("This panel is for the invoker only.", ephemeral=True)
                return
            gc = await self.get_guild_conf(ctx.guild)
            cards_local = gc.get("cards", {})
            if not cards_local:
                await interaction.response.send_message("No cards to edit.", ephemeral=True)
                return
            opts = [discord.SelectOption(label=f"{v.get('name')} ({k})", value=k) for k, v in cards_local.items()]
            sel = ui.Select(placeholder="Select a card to manage", options=opts, min_values=1, max_values=1)
            sel_view = ui.View(timeout=60)
            sel_view.add_item(sel)
            await interaction.response.send_message("Select a card to manage:", view=sel_view, ephemeral=True)
            await sel_view.wait()
            if not getattr(sel, "values", None):
                await interaction.followup.send("Selection timed out.", ephemeral=True)
                return
            chosen_key = sel.values[0]
            await interaction.followup.send(f"Opening card manager for {chosen_key}...", ephemeral=True)
            await self._card_manager(interaction, ctx, chosen_key)

        async def remove_card_cb(interaction: discord.Interaction, button: ui.Button):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("This panel is for the invoker only.", ephemeral=True)
                return
            gc = await self.get_guild_conf(ctx.guild)
            cards_local = gc.get("cards", {})
            if not cards_local:
                await interaction.response.send_message("No cards to remove.", ephemeral=True)
                return
            opts = [discord.SelectOption(label=f"{v.get('name')} ({k})", value=k) for k, v in cards_local.items()]
            sel = ui.Select(placeholder="Select a card to remove", options=opts, min_values=1, max_values=1)
            sel_view = ui.View(timeout=60)
            sel_view.add_item(sel)
            await interaction.response.send_message("Select a card to remove:", view=sel_view, ephemeral=True)
            await sel_view.wait()
            if not getattr(sel, "values", None):
                await interaction.followup.send("Selection timed out.", ephemeral=True)
                return
            key = sel.values[0]
            cards_local.pop(key, None)
            gc["cards"] = cards_local
            await self.config.guild(ctx.guild).set(gc)
            await interaction.followup.send(f"Removed card {key}.", ephemeral=True)

        create_btn = ui.Button(label="Create Card", style=discord.ButtonStyle.green)
        manage_btn = ui.Button(label="Manage Card", style=discord.ButtonStyle.blurple)
        remove_btn = ui.Button(label="Remove Card", style=discord.ButtonStyle.red)

        create_btn.callback = create_card_cb
        manage_btn.callback = manage_card_cb
        remove_btn.callback = remove_card_cb

        view.add_item(create_btn)
        view.add_item(manage_btn)
        view.add_item(remove_btn)

        await ctx.send(msg, view=view)

    async def _card_manager(self, interaction: discord.Interaction, ctx: commands.Context, card_key: str):
        gc = await self.get_guild_conf(ctx.guild)
        cards_local = gc.get("cards", {})
        card = cards_local.get(card_key)
        if not card:
            await interaction.followup.send("Card not found.", ephemeral=True)
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

        view = ui.View(timeout=300)

        async def add_prize_cb(i: discord.Interaction, button: ui.Button):
            if i.user.id != ctx.author.id:
                await i.response.send_message("This manager is for the admin who opened it.", ephemeral=True)
                return
            modal = PrizeModal()
            await i.response.send_modal(modal)
            await modal.wait()
            if not getattr(modal, "result_payload", None):
                await i.followup.send("Prize creation cancelled.", ephemeral=True)
                return
            payload = modal.result_payload
            prize_id = str(uuid.uuid4())[:8]
            prize = {"id": prize_id, "name": payload["name"], "value": payload["value"], "weight": payload["weight"], "tag": payload["tag"]}
            card.setdefault("prizes", []).append(prize)
            cards_local[card_key] = card
            gc["cards"] = cards_local
            await self.config.guild(ctx.guild).set(gc)
            await i.followup.send(f"Added prize {prize_id}.", ephemeral=True)

        async def edit_prize_cb(i: discord.Interaction, button: ui.Button):
            if i.user.id != ctx.author.id:
                await i.response.send_message("This manager is for the admin who opened it.", ephemeral=True)
                return
            prizes = card.get("prizes", [])
            if not prizes:
                await i.response.send_message("No prizes to edit.", ephemeral=True)
                return
            opts = [discord.SelectOption(label=f"{p.get('name')} ({p.get('id')})", value=p.get('id')) for p in prizes]
            sel = ui.Select(placeholder="Select prize to edit", options=opts, min_values=1, max_values=1)
            sel_view = ui.View(timeout=60)
            sel_view.add_item(sel)
            await i.response.send_message("Select a prize to edit:", view=sel_view, ephemeral=True)
            await sel_view.wait()
            if not getattr(sel, "values", None):
                await i.followup.send("Timed out.", ephemeral=True)
                return
            chosen_id = sel.values[0]
            prize = next((p for p in prizes if p.get("id") == chosen_id), None)
            if not prize:
                await i.followup.send("Prize not found.", ephemeral=True)
                return
            modal = PrizeModal(existing=prize)
            modal.name.default = prize.get("name", "")
            modal.value.default = str(prize.get("value", 0))
            modal.weight.default = str(prize.get("weight", 1))
            modal.tag.default = prize.get("tag") or ""
            try:
                await i.followup.send_modal(modal)
            except Exception:
                await i.response.send_modal(modal)
            await modal.wait()
            if not getattr(modal, "result_payload", None):
                await i.followup.send("Edit cancelled.", ephemeral=True)
                return
            payload = modal.result_payload
            prize.update({"name": payload["name"], "value": payload["value"], "weight": payload["weight"], "tag": payload["tag"]})
            gc = await self.get_guild_conf(ctx.guild)
            cards_local = gc.get("cards", {})
            cards_local[card_key] = card
            gc["cards"] = cards_local
            await self.config.guild(ctx.guild).set(gc)
            await i.followup.send(f"Updated prize {chosen_id}.", ephemeral=True)

        async def remove_prize_cb(i: discord.Interaction, button: ui.Button):
            if i.user.id != ctx.author.id:
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
            await i.response.send_message("Select prize(s) to remove:", view=sel_view, ephemeral=True)
            await sel_view.wait()
            if not getattr(sel, "values", None):
                await i.followup.send("Timed out.", ephemeral=True)
                return
            remove_ids = set(sel.values)
            card["prizes"] = [p for p in prizes if p.get("id") not in remove_ids]
            gc = await self.get_guild_conf(ctx.guild)
            cards_local = gc.get("cards", {})
            cards_local[card_key] = card
            gc["cards"] = cards_local
            await self.config.guild(ctx.guild).set(gc)
            await i.followup.send(f"Removed {len(remove_ids)} prize(s).", ephemeral=True)

        async def view_details_cb(i: discord.Interaction, button: ui.Button):
            if i.user.id != ctx.author.id:
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

        await interaction.followup.send(f"Card manager opened for {card_key}.", view=view, ephemeral=True)

    @scratch.command(name="manage_remove")
    @checks.mod_or_permissions(manage_guild=True)
    async def manage_remove(self, ctx: commands.Context, key: str):
        """Remove a card by key (admin)"""
        gc = await self.get_guild_conf(ctx.guild)
        cards = gc.get("cards", {})
        if key not in cards:
            await ctx.send("Card key not found.")
            return
        cards.pop(key)
        gc["cards"] = cards
        await self.config.guild(ctx.guild).set(gc)
        await ctx.send(f"Removed card {key}.")


    @scratch.command()
    @checks.mod_or_permissions(manage_guild=True)
    async def setenabled(self, ctx: commands.Context, enabled: bool):
        """Enable or disable scratch cards on this guild"""
        gc = await self.get_guild_conf(ctx.guild)
        gc["enabled"] = bool(enabled)
        await self.config.guild(ctx.guild).set(gc)
        await ctx.send(f"Enabled set to {bool(enabled)}")

    @scratch.command()
    async def version(self, ctx: commands.Context):
        """Show cog version"""
        await ctx.send(COG_VERSION)
