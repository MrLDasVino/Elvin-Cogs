from __future__ import annotations

import logging
from typing import List, Optional

import discord

log = logging.getLogger("red.memeforge")


def _template_name(template: dict) -> str:
    return template.get("name") or template.get("id") or "Unknown"


def _template_key(template: dict) -> str:
    return template.get("id") or _template_name(template)


def _line_count(template: dict) -> int:
    value = template.get("lines", 0)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


class MemeTextModal(discord.ui.Modal):
    def __init__(self, cog, template: dict, start_index: int, total_lines: int, collected: dict) -> None:
        chunk_size = min(5, total_lines - start_index)
        super().__init__(title=_template_name(template)[:45])
        self.cog = cog
        self.template = template
        self.start_index = start_index
        self.total_lines = total_lines
        self.collected = collected
        self.inputs: List[discord.ui.TextInput] = []
        examples = (template.get("example") or {}).get("text") or []
        for i in range(chunk_size):
            line_no = start_index + i
            placeholder = examples[line_no] if line_no < len(examples) else None
            text_input = discord.ui.TextInput(
                label=f"Line {line_no + 1}",
                placeholder=placeholder,
                required=False,
                max_length=200,
            )
            self.inputs.append(text_input)
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        for i, text_input in enumerate(self.inputs):
            self.collected[self.start_index + i] = text_input.value
        next_index = self.start_index + len(self.inputs)
        if next_index < self.total_lines:
            next_modal = MemeTextModal(self.cog, self.template, next_index, self.total_lines, self.collected)
            await interaction.response.send_modal(next_modal)
        else:
            await self.cog.finalize_meme(interaction, self.template, self.collected)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Error in MemeForge text modal", exc_info=error)
        message = "Something went wrong building that meme. Please run the command again."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class SearchModal(discord.ui.Modal, title="Search Templates"):
    query: discord.ui.TextInput = discord.ui.TextInput(
        label="Template name contains...",
        max_length=100,
        required=True,
    )

    def __init__(self, browse_view: "TemplateBrowseView") -> None:
        super().__init__()
        self.browse_view = browse_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        needle = self.query.value.lower().strip()
        filtered = [t for t in self.browse_view.cog.templates if needle in _template_name(t).lower()]
        if not filtered:
            await interaction.response.send_message(f"No templates matched `{self.query.value}`.", ephemeral=True)
            return
        self.browse_view.templates = filtered
        self.browse_view.page = 0
        self.browse_view.max_page = max(0, (len(filtered) - 1) // self.browse_view.per_page)
        self.browse_view.refresh_components()
        await interaction.response.edit_message(embed=self.browse_view.build_embed(), view=self.browse_view)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Error in MemeForge search modal", exc_info=error)
        message = "Something went wrong with that search. Please try again."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class TemplateBrowseView(discord.ui.View):
    def __init__(self, cog, author: discord.abc.User, templates: list, per_page: int = 25, timeout: float = 300) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.author = author
        self.templates = templates
        self.per_page = per_page
        self.page = 0
        self.message: Optional[discord.Message] = None
        self.max_page = max(0, (len(templates) - 1) // per_page)
        self.refresh_components()

    def get_page_templates(self) -> list:
        start = self.page * self.per_page
        return self.templates[start:start + self.per_page]

    def refresh_components(self) -> None:
        page_templates = self.get_page_templates()
        if page_templates:
            options = []
            seen_values = set()
            for t in page_templates:
                value = _template_key(t)[:100]
                if value in seen_values:
                    continue
                seen_values.add(value)
                options.append(
                    discord.SelectOption(
                        label=_template_name(t)[:100],
                        value=value,
                        description=f"{_line_count(t)} text line(s)"[:100],
                    )
                )
            self.template_select.options = options or [discord.SelectOption(label="No templates found", value="_none")]
            self.template_select.disabled = not options
        else:
            self.template_select.options = [discord.SelectOption(label="No templates found", value="_none")]
            self.template_select.disabled = True
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.max_page

    def build_embed(self) -> discord.Embed:
        page_templates = self.get_page_templates()
        description = "\n".join(
            f"**{i + 1 + self.page * self.per_page}.** {_template_name(t)}"
            for i, t in enumerate(page_templates)
        ) or "No templates found."
        embed = discord.Embed(
            title="MemeForge \u2014 Template Browser",
            description=description[:4000],
            color=discord.Color.blurple(),
        )
        embed.set_footer(
            text=(
                f"Page {self.page + 1}/{self.max_page + 1} \u2022 {len(self.templates)} templates \u2022 "
                "Pick one from the dropdown below"
            )
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "This menu isn't for you \u2014 run the command yourself to get your own.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is None:
            return
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        log.exception("Error handling MemeForge component %r", item, exc_info=error)
        message = "Something went wrong with that action. Please try again, or run the command again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass

    @discord.ui.select(placeholder="Choose a template to create a meme...", min_values=1, max_values=1, row=0)
    async def template_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        if not select.values:
            await interaction.response.send_message("Nothing was selected, please try again.", ephemeral=True)
            return
        template_id = select.values[0]
        if template_id == "_none":
            await interaction.response.send_message("There's nothing to pick here.", ephemeral=True)
            return
        template = next((t for t in self.templates if _template_key(t) == template_id), None)
        if not template:
            await interaction.response.send_message("That template couldn't be found anymore.", ephemeral=True)
            return
        lines = _line_count(template)
        if lines <= 0:
            await self.cog.finalize_meme(interaction, template, {})
        else:
            modal = MemeTextModal(self.cog, template, 0, lines, {})
            await interaction.response.send_modal(modal)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="\u25c0\ufe0f", row=1)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            self.page = max(0, self.page - 1)
            self.refresh_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        except Exception:
            log.exception("Failed to go to the previous page")
            for item in self.children:
                item.disabled = True
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "Couldn't turn the page. Please run the command again.", ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "Couldn't turn the page. Please run the command again.", ephemeral=True
                    )
            except discord.HTTPException:
                pass
            if self.message is not None:
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    pass

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="\u25b6\ufe0f", row=1)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            self.page = min(self.max_page, self.page + 1)
            self.refresh_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        except Exception:
            log.exception("Failed to go to the next page")
            for item in self.children:
                item.disabled = True
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "Couldn't turn the page. Please run the command again.", ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "Couldn't turn the page. Please run the command again.", ephemeral=True
                    )
            except discord.HTTPException:
                pass
            if self.message is not None:
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    pass

    @discord.ui.button(style=discord.ButtonStyle.primary, emoji="\U0001f50d", label="Search", row=1)
    async def search_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(SearchModal(self))

    @discord.ui.button(style=discord.ButtonStyle.secondary, label="Reset", row=1)
    async def reset_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.templates = self.cog.templates
        self.page = 0
        self.max_page = max(0, (len(self.templates) - 1) // self.per_page)
        self.refresh_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji="\u2716\ufe0f", row=1)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()
