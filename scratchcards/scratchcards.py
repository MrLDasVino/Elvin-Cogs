from redbot.core import commands, Config, checks, bank
from redbot.core.utils.chat_formatting import box
import discord
from discord import ui
import asyncio
import uuid
import random
import typing

CONFIG_ID = 0xBADA55C0FFEE1234
COG_VERSION = "1.2.4"

DEFAULT_GUILD = {
    "enabled": True,
    "max_daily": 10,
    "instant_reveal": True,
    "cards": {}
}


def disable_view_items(view: ui.View):
    """Compatibility helper: mark all view children as disabled if possible."""
    if view is None:
        return
    for item in getattr(view, "children", []):
        try:
            if hasattr(item, "disabled"):
                item.disabled = True
        except Exception:
            pass


async def _auto_disable_view_after(view: ui.View, message: typing.Optional[discord.Message], timeout: int):
    """Sleep then disable the view and edit a fresh message; safe against ephemeral / stale message objects."""
    await asyncio.sleep(timeout)
    if view.is_finished():
        return
    try:
        disable_view_items(view)
    except Exception:
        pass
    if message is not None:
        try:
            if getattr(message, "channel", None):
                fresh = await message.channel.fetch_message(message.id)
                await fresh.edit(view=view)
                try:
                    view.stop()
                except Exception:
                    pass
                return
        except Exception:
            pass
        try:
            await message.edit(view=view)
        except Exception:
            pass
    try:
        view.stop()
    except Exception:
        pass


class TimedView(ui.View):
    """A View that stores an associated message and can be auto-disabled via helper."""

    def __init__(self, timeout: int = 60):
        super().__init__(timeout=timeout)
        self.message: typing.Optional[discord.Message] = None

    async def on_timeout(self):
        try:
            disable_view_items(self)
        except Exception:
            pass
        if not getattr(self, "message", None):
            try:
                self.stop()
            except Exception:
                pass
            return
        try:
            if getattr(self.message, "channel", None):
                fresh = await self.message.channel.fetch_message(self.message.id)
                await fresh.edit(view=self)
            else:
                await self.message.edit(view=self)
        except Exception:
            pass
        try:
            self.stop()
        except Exception:
            pass


class ConfirmView(TimedView):
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
        try:
            disable_view_items(self)
        except Exception:
            pass
        if getattr(self, "message", None):
            try:
                await self.message.edit(view=self)
            except Exception:
                pass
        try:
            self.stop()
        except Exception:
            pass

    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        self.result = False
        await interaction.response.defer()
        try:
            disable_view_items(self)
        except Exception:
            pass
        if getattr(self, "message", None):
            try:
                await self.message.edit(view=self)
            except Exception:
                pass
        try:
            self.stop()
        except Exception:
            pass


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
        if self.view:
            try:
                disable_view_items(self.view)
            except Exception:
                pass
            if getattr(self.view, "message", None):
                try:
                    await self.view.message.edit(view=self.view)
                except Exception:
                    pass
            try:
                self.view.stop()
            except Exception:
                pass


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
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        asyncio.create_task(self.cog._card_manager(interaction, None, chosen_key))


class CardModal(ui.Modal, title="Create Card"):
    key = ui.TextInput(label="Card key (internal, no spaces)", placeholder="basic", required=True, max_length=32)
    display = ui.TextInput(label="Display name", placeholder="Basic Scratch", required=True, max_length=64)
    price = ui.TextInput(label="Price (int)", placeholder="100", required=True, max_length=20)
    max_daily = ui.TextInput(label="Max buys per day (optional)", placeholder="Leave empty for no per-card limit", required=False, max_length=10)
    thumbnail = ui.TextInput(label="Thumbnail URL (optional)", placeholder="https://example.com/image.png", required=False, max_length=200)

    def __init__(self, cog=None, guild: discord.Guild = None, existing: dict = None):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.existing = existing

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price_val = int(self.price.value.strip())
        except Exception:
            await interaction.response.send_message("Invalid numeric input for price.", ephemeral=True)
            return

        max_daily_val = None
        if self.max_daily.value and self.max_daily.value.strip():
            try:
                md = int(self.max_daily.value.strip())
                if md < 0:
                    raise ValueError()
                max_daily_val = md
            except Exception:
                await interaction.response.send_message("Invalid numeric input for max buys per day. Use a non-negative integer or leave empty.", ephemeral=True)
                return

        thumb_val = None
        if self.thumbnail.value and self.thumbnail.value.strip():
            thumb_val = self.thumbnail.value.strip()

        if not self.cog or not self.guild:
            await interaction.response.send_message("Internal error: missing context.", ephemeral=True)
            return

        payload = {
            "key": self.key.value.strip(),
            "name": self.display.value.strip(),
            "price": max(0, price_val),
            "max_daily": max_daily_val,
            "thumbnail": thumb_val
        }

        gc = await self.cog.get_guild_conf(self.guild)
        cards_local = gc.get("cards", {})
        key = payload["key"]
        if key in cards_local:
            await interaction.response.send_message("Card key already exists.", ephemeral=True)
            return

        cards_local[key] = {
            "name": payload["name"],
            "price": payload["price"],
            "prizes": [],
            "max_daily": payload["max_daily"],
            "thumbnail": payload["thumbnail"]
        }
        gc["cards"] = cards_local
        await self.cog.config.guild(self.guild).set(gc)
        await interaction.response.send_message(f"Created card {key}.", ephemeral=True)

        # Open the card manager immediately for the newly created card
        try:
            asyncio.create_task(self.cog._card_manager(interaction, None, key))
        except Exception:
            pass


class PrizeModal(ui.Modal, title="Create / Edit Prize"):
    name = ui.TextInput(label="Prize name", placeholder="Small Win", required=True, max_length=64)
    value = ui.TextInput(label="Prize value (int)", placeholder="50", required=True, max_length=20)
    chance = ui.TextInput(label="Chance (%)", placeholder="1.0", required=True, max_length=20)
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
            chance_val = float(self.chance.value.strip())
        except Exception:
            await interaction.response.send_message("Invalid numeric input for value or chance.", ephemeral=True)
            return

        if not (0.0 <= chance_val <= 100.0):
            await interaction.response.send_message("Chance must be between 0 and 100.", ephemeral=True)
            return

        if not self.cog or not self.guild or not self.card_key:
            await interaction.response.send_message("Internal error: missing context.", ephemeral=True)
            return

        prize_id = str(uuid.uuid4())[:8]
        prize = {
            "id": prize_id,
            "name": self.name.value.strip(),
            "value": max(0, val),
            "weight": float(round(chance_val, 6)),
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
    chance = ui.TextInput(label="Chance (%)", required=True, max_length=20)
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
        self.chance.default = str(existing.get("weight", 0.0))
        self.tag.default = existing.get("tag") or ""

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.value.value.strip())
            chance_val = float(self.chance.value.strip())
        except Exception:
            await interaction.response.send_message("Invalid numeric input for value or chance.", ephemeral=True)
            return

        if not (0.0 <= chance_val <= 100.0):
            await interaction.response.send_message("Chance must be between 0 and 100.", ephemeral=True)
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
                p["weight"] = float(round(chance_val, 6))
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


def _format_chance(chance: typing.Optional[float]) -> str:
    if chance is None:
        return "—"
    s = f"{chance:.3f}".rstrip("0").rstrip(".")
    return f"{s}%"


def _rarity_emoji(tag: typing.Optional[str]) -> str:
    if not tag:
        return "🎟️"
    t = str(tag).lower()
    if "legend" in t or "legendary" in t:
        return "🌟"
    if "epic" in t:
        return "💠"
    if "rare" in t:
        return "🔷"
    if "uncommon" in t:
        return "🟢"
    if "common" in t:
        return "⚪"
    return "🎁"


def _thumbnail_url_for_card(card: dict) -> typing.Optional[str]:
    # Return configured thumbnail URL if present and non-empty, otherwise None
    if not card:
        return None
    thumb = card.get("thumbnail")
    if not thumb:
        return None
    return str(thumb)


def _author_icon_for_member(member: typing.Optional[discord.Member]) -> typing.Optional[str]:
    if not member:
        return None
    try:
        return member.avatar.url
    except Exception:
        try:
            return member.avatar_url
        except Exception:
            return None


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
            max_daily = v.get("max_daily")
            md_text = f" ; max/day {max_daily}" if max_daily is not None else ""
            label = f"{v.get('name')} — {v.get('price')}{md_text}"
            desc = f"prizes: {len(v.get('prizes', []))}; price {v.get('price')}"
            opts.append(discord.SelectOption(label=label[:100], value=k, description=desc[:100]))
        return opts

    def _weighted_prize_choice(self, prizes: typing.List[dict]) -> dict:
        """Select prize using stored percent chances in 'weight'. If total < 100, remaining chance is 'No Prize'."""
        if not prizes:
            return {"name": "No Prize", "value": 0, "weight": 0.0, "tag": None, "id": "none"}
        entries = []
        total = 0.0
        for p in prizes:
            try:
                chance = float(p.get("weight", 0.0))
            except Exception:
                chance = 0.0
            chance = max(0.0, min(100.0, chance))
            entries.append((p, chance))
            total += chance
        pick = random.random() * 100.0
        cum = 0.0
        for p, chance in entries:
            cum += chance
            if pick < cum:
                return p
        return {"name": "No Prize", "value": 0, "weight": 0.0, "tag": None, "id": "none"}

    def _random_embed_color(self) -> int:
        """Return a visually pleasing random color as an integer."""
        palette = [0x1ABC9C, 0x2ECC71, 0x3498DB, 0x9B59B6, 0xE91E63, 0xE67E22, 0xF1C40F, 0x95A5A6, 0x34495E]
        return random.choice(palette)

    def _buy_result_embed(self, guild: discord.Guild, card: dict, price: int, prize: dict, currency: str, buyer: typing.Optional[discord.Member] = None) -> discord.Embed:
        """Richer, emoji-forward embed for buy results using the server currency and random color."""
        won = int(prize.get("value", 0)) > 0
        prize_name = prize.get("name", "No Prize")
        prize_value = int(prize.get("value", 0))
        chance = prize.get("weight", None)

        title = "🎉 You Won!" if won else "😢 Better Luck Next Time"
        color = self._random_embed_color()
        embed = discord.Embed(title=title, color=color)

        card_name = card.get("name") or "Scratch Card"
        embed.description = f"**{card_name}** — Cost: **{price} {currency}**"

        if won:
            embed.add_field(name=f"{_rarity_emoji(prize.get('tag'))} Prize", value=f"**{prize_name}**\n💰 {prize_value} {currency}", inline=False)
            embed.add_field(name="Chance", value=_format_chance(chance), inline=True)
            embed.add_field(name="Card Price", value=f"{price} {currency}", inline=True)
        else:
            embed.add_field(name="Prize", value="No payout this time", inline=False)
            embed.add_field(name="Chance", value=_format_chance(chance), inline=True)
            embed.add_field(name="Card Price", value=f"{price} {currency}", inline=True)

        thumb = _thumbnail_url_for_card(card)
        if thumb:
            try:
                embed.set_thumbnail(url=thumb)
            except Exception:
                pass

        if buyer:
            icon = _author_icon_for_member(buyer)
            try:
                embed.set_author(name=str(buyer), icon_url=icon)
            except Exception:
                try:
                    embed.set_author(name=str(buyer))
                except Exception:
                    pass

        footer_text = f"{guild.name} • Scratchcard"
        try:
            embed.set_footer(text=footer_text, icon_url=guild.icon.url if getattr(guild, "icon", None) else None)
        except Exception:
            try:
                embed.set_footer(text=footer_text)
            except Exception:
                pass

        if won:
            try:
                embed.colour = 0x2ECC71
            except Exception:
                pass

        return embed

    def _view_details_embed(self, guild: discord.Guild, card_key: str, card: dict) -> discord.Embed:
        # Header and basic info
        card_name = card.get("name") or "Scratch Card"
        color = 0x3498DB
        embed = discord.Embed(title=f"{card_name} — Card Details", color=color)
    
        # Top-line metadata as inline fields
        price = card.get("price", 0)
        max_daily = card.get("max_daily")
        md_text = str(max_daily) if max_daily is not None else "Guild default / unlimited"
        embed.add_field(name="Internal Key", value=f"`{card_key}`", inline=True)
        embed.add_field(name="Price", value=f"{price}", inline=True)
        embed.add_field(name="Max buys / day", value=md_text, inline=True)
    
        # Prizes: build a compact, aligned list with emoji, name, value and chance
        prizes = card.get("prizes", []) or []
        if not prizes:
            embed.add_field(name="Prizes", value="No prizes configured", inline=False)
        else:
            lines = []
            # Column widths chosen for readability in Discord embeds
            for p in prizes:
                pid = p.get("id")
                name = p.get("name") or "Unnamed"
                val = int(p.get("value", 0))
                chance = p.get("weight", 0.0)
                tag = p.get("tag") or "-"
                emoji = _rarity_emoji(tag)
                # Format: emoji name — value | chance% (id)
                lines.append(f"{emoji} **{name}** — `{val}` ⸱ {_format_chance(chance)}\n`{pid}` • {tag}")
    
            # If many prizes, keep the field compact by joining with double newlines
            embed.add_field(name=f"Prizes ({len(prizes)})", value="\n\n".join(lines), inline=False)
    
        # Thumbnail and footer
        thumb = _thumbnail_url_for_card(card)
        if thumb:
            try:
                embed.set_thumbnail(url=thumb)
            except Exception:
                pass
    
        footer_text = f"{guild.name} • Scratchcard"
        try:
            embed.set_footer(text=footer_text)
        except Exception:
            pass
    
        return embed


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
            max_daily = v.get("max_daily")
            md_text = f" | max/day {max_daily}" if max_daily is not None else ""
            lines.append(f"{k} | {v.get('name')} | Price: {v.get('price')}{md_text} | Prizes: {prize_count}")
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
        view = TimedView(timeout=60)
        view.add_item(select)
        msg = await ctx.send("Choose a scratch card to buy:", view=view)
        view.message = msg
        asyncio.create_task(_auto_disable_view_after(view, msg, view.timeout or 60))
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
        confirm.message = confirm_msg
        asyncio.create_task(_auto_disable_view_after(confirm, confirm_msg, confirm.timeout or 60))
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
            embed = self._buy_result_embed(ctx.guild, card, price, chosen, currency, buyer=ctx.author)
            await ctx.send(embed=embed)

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

        view = TimedView(timeout=60)

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

            gc = await self.get_guild_conf(ctx.guild)
            cards_local = gc.get("cards", {})
            if not cards_local:
                await interaction.response.send_message("No cards to remove.", ephemeral=True)
                return

            opts = [discord.SelectOption(label=f"{v.get('name')} ({k})", value=k) for k, v in cards_local.items()]
            sel = ui.Select(placeholder="Select a card to remove", options=opts, min_values=1, max_values=1)
            sel_view = TimedView(timeout=60)
            sel_view.add_item(sel)

            async def sel_callback(sel_interaction: discord.Interaction):
                if sel_interaction.user.id != interaction.user.id:
                    await sel_interaction.response.send_message("This menu isn't for you.", ephemeral=True)
                    return
                await sel_interaction.response.defer()
                try:
                    disable_view_items(sel_view)
                except Exception:
                    pass
                if getattr(sel_view, "message", None):
                    try:
                        await sel_view.message.edit(view=sel_view)
                    except Exception:
                        pass
                try:
                    sel_view.stop()
                except Exception:
                    pass

            sel.callback = sel_callback

            try:
                await interaction.response.send_message("Select a card to remove:", view=sel_view, ephemeral=True)
                follow_msg = await interaction.original_response()
            except Exception:
                try:
                    follow_msg = await interaction.channel.send("Select a card to remove:", view=sel_view)
                except Exception:
                    try:
                        await interaction.followup.send("Failed to open removal menu.", ephemeral=True)
                    except Exception:
                        pass
                    return

            if follow_msg:
                sel_view.message = follow_msg
                asyncio.create_task(_auto_disable_view_after(sel_view, follow_msg, sel_view.timeout or 60))

            await sel_view.wait()
            if not getattr(sel, "values", None):
                try:
                    await interaction.followup.send("No selection made (timed out).", ephemeral=True)
                except Exception:
                    pass
                return

            key = sel.values[0]
            cards_local.pop(key, None)
            gc["cards"] = cards_local
            await self.config.guild(ctx.guild).set(gc)

            try:
                await interaction.followup.send(f"Removed card {key}.", ephemeral=True)
            except Exception:
                pass

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
        view.message = panel_msg
        asyncio.create_task(_auto_disable_view_after(view, panel_msg, view.timeout or 60))
        await view.wait()

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
                    lines.append(f"- {p.get('id')} | {p.get('name')} | value {p.get('value')} | chance {p.get('weight')}% | tag {p.get('tag')}")
            return "\n".join(lines)

        view = TimedView(timeout=60)

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
            sel_view = TimedView(timeout=60)
            sel_view.add_item(sel)

            try:
                await i.response.send_message("Select a prize to edit:", view=sel_view, ephemeral=True)
                follow_msg = await i.original_response()
            except Exception:
                try:
                    follow_msg = await i.channel.send("Select a prize to edit:", view=sel_view)
                except Exception:
                    try:
                        await i.followup.send("Failed to open prize editor.", ephemeral=True)
                    except Exception:
                        pass
                    return

            if follow_msg:
                sel_view.message = follow_msg
                asyncio.create_task(_auto_disable_view_after(sel_view, follow_msg, sel_view.timeout or 60))

            await sel_view.wait()
            # when PrizeSelect triggers a modal, it will handle it itself; no further action required here

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
            sel = ui.Select(placeholder="Select prize(s) to remove", options=opts, min_values=1, max_values=min(25, len(opts)))
            sel_view = TimedView(timeout=60)
            sel_view.add_item(sel)

            # Attach callback to handle selection immediately (fixes delayed posting)
            async def sel_callback(sel_interaction: discord.Interaction):
                if sel_interaction.user.id != i.user.id:
                    await sel_interaction.response.send_message("This menu isn't for you.", ephemeral=True)
                    return
                await sel_interaction.response.defer()
                try:
                    disable_view_items(sel_view)
                except Exception:
                    pass
                if getattr(sel_view, "message", None):
                    try:
                        await sel_view.message.edit(view=sel_view)
                    except Exception:
                        pass
                try:
                    sel_view.stop()
                except Exception:
                    pass

            sel.callback = sel_callback

            try:
                await i.response.send_message("Select prize(s) to remove:", view=sel_view, ephemeral=True)
                follow_msg = await i.original_response()
            except Exception:
                try:
                    follow_msg = await i.channel.send("Select prize(s) to remove:", view=sel_view)
                except Exception:
                    try:
                        await i.followup.send("Failed to open remove-prize menu.", ephemeral=True)
                    except Exception:
                        pass
                    return

            if follow_msg:
                sel_view.message = follow_msg
                asyncio.create_task(_auto_disable_view_after(sel_view, follow_msg, sel_view.timeout or 60))

            await sel_view.wait()
            if not getattr(sel, "values", None):
                try:
                    await i.followup.send("No selection made (timed out).", ephemeral=True)
                except Exception:
                    pass
                return

            remove_ids = set(sel.values)
            card["prizes"] = [p for p in prizes if p.get("id") not in remove_ids]
            gc = await self.get_guild_conf(guild)
            cards_local = gc.get("cards", {})
            cards_local[card_key] = card
            gc["cards"] = cards_local
            await self.config.guild(guild).set(gc)
            try:
                await i.followup.send(f"Removed {len(remove_ids)} prize(s).", ephemeral=True)
            except Exception:
                pass

        async def view_details_cb(i: discord.Interaction):
            opener_id = interaction.user.id if interaction else (ctx.author.id if ctx else None)
            if i.user.id != opener_id:
                await i.response.send_message("This manager is for the admin who opened it.", ephemeral=True)
                return
            embed = self._view_details_embed(i.guild, card_key, card)
            try:
                await i.response.send_message(embed=embed, ephemeral=True)
            except Exception:
                try:
                    await i.channel.send(embed=embed)
                except Exception:
                    pass

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

        manager_msg = None
        try:
            manager_msg = await interaction.followup.send(f"Card manager opened for {card_key}.", view=view, ephemeral=False)
        except Exception:
            try:
                manager_msg = await interaction.channel.send(f"Card manager opened for {card_key}.", view=view)
            except Exception:
                pass

        if manager_msg:
            view.message = manager_msg
            asyncio.create_task(_auto_disable_view_after(view, manager_msg, view.timeout or 60))
            await view.wait()

    @checks.mod_or_permissions(manage_guild=True)
    @scratch.command()
    async def setenabled(self, ctx: commands.Context, enabled: bool):
        gc = await self.get_guild_conf(ctx.guild)
        gc["enabled"] = bool(enabled)
        await self.config.guild(ctx.guild).set(gc)
        await ctx.send(f"Enabled set to {bool(enabled)}")
