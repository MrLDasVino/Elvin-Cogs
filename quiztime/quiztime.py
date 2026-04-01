import asyncio
import json
import os
import random
from typing import Optional, Dict

import discord
from discord import Embed
from discord.ui import View, Button
from redbot.core import commands, Config, checks
from redbot.core.utils.chat_formatting import box
from redbot.core import bank

BASE_PATH = os.path.dirname(__file__)
QUIZ_JSON_PATH = os.path.join(BASE_PATH, "quiz.json")

DEFAULT_CONFIG = {
    "channel_id": None,
    "interval_minutes": 60,
    "enabled": True,
    "reward_min": 50,
    "reward_max": 50,
    "leaderboard": {}
}

LABELS = ["A", "B", "C", "D"]


class QuizButton(Button):
    def __init__(self, label: str, answer_text: str, is_correct: bool):
        super().__init__(style=discord.ButtonStyle.primary, label=label)
        self.answer_text = answer_text
        self.is_correct = is_correct


class QuizView(View):
    def __init__(self, cog, correct_answer_text: str, timeout: int = 60):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.correct_answer_text = correct_answer_text
        self.answered = False
        self.message: Optional[discord.Message] = None
        self._expired_handled = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return not interaction.user.bot

    async def on_timeout(self):
        # Called when view times out. If nobody answered, mark expired and edit message.
        if self._expired_handled:
            return
        self._expired_handled = True
        # disable all buttons
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                # build expired embed revealing the correct answer
                embed = self._expired_embed()
                await self.message.edit(embed=embed, view=self)
            except Exception:
                pass
        # remove from active quizzes tracking
        try:
            channel_id = self.message.channel.id if self.message else None
            if channel_id and channel_id in self.cog._active_quizzes:
                stored = self.cog._active_quizzes.get(channel_id)
                if stored is self:
                    del self.cog._active_quizzes[channel_id]
        except Exception:
            pass

    def _expired_embed(self) -> Embed:
        color = discord.Color.dark_grey()
        embed = Embed(
            title="Quiz Expired",
            description=f"**Time's up!** No one answered in time.\n\n**Answer:** {self.correct_answer_text}",
            color=color
        )
        embed.set_footer(text="This question expired. A new quiz will be posted soon.")
        return embed

    async def handle_click(self, interaction: discord.Interaction, button: QuizButton):
        if self.answered:
            await interaction.response.send_message("Someone already answered this question.", ephemeral=True)
            return

        self.answered = True
        # disable all buttons
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

        # remove from active quizzes tracking
        try:
            channel_id = self.message.channel.id if self.message else None
            if channel_id and channel_id in self.cog._active_quizzes:
                stored = self.cog._active_quizzes.get(channel_id)
                if stored is self:
                    del self.cog._active_quizzes[channel_id]
        except Exception:
            pass

        if button.is_correct:
            amount = await self.cog._get_reward_amount()
            try:
                await bank.deposit_credits(interaction.user, amount)
                await self.cog._increment_leaderboard(interaction.user)
                embed = Embed(
                    title="Correct Answer!",
                    description=f"{interaction.user.mention} answered correctly and won **{amount}** credits!",
                    color=discord.Color.green()
                )
                embed.add_field(name="Answer", value=f"**{button.answer_text}**", inline=False)
                embed.set_footer(text="Well done! Keep an eye out for the next quiz.")
            except Exception:
                embed = Embed(
                    title="Correct Answer!",
                    description=f"{interaction.user.mention} answered correctly but I couldn't award currency (bank error).",
                    color=discord.Color.green()
                )
                embed.add_field(name="Answer", value=f"**{button.answer_text}**", inline=False)
        else:
            embed = Embed(
                title="Incorrect",
                description=f"{interaction.user.mention} answered but that was incorrect.",
                color=discord.Color.red()
            )
            embed.add_field(name="Correct Answer", value=f"**{self.correct_answer_text}**", inline=False)
            embed.set_footer(text="Better luck next time!")

        await interaction.response.send_message(embed=embed)


class QuizTime(commands.Cog):
    """Periodic multiple-choice quiz with bank rewards and leaderboard."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xA1B2C3D4E5F60709, force_registration=True)
        self.config.register_global(**DEFAULT_CONFIG)
        self._task: Optional[asyncio.Task] = None
        self._load_quiz_file()
        # track active quiz view per channel so we can expire previous when posting a new one
        self._active_quizzes: Dict[int, QuizView] = {}
        self._ensure_task_running()

    def cog_unload(self):
        if self._task:
            self._task.cancel()

    # -------------------------
    # Quiz JSON handling
    # -------------------------
    def _load_quiz_file(self):
        if not os.path.exists(QUIZ_JSON_PATH):
            with open(QUIZ_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "default_thumbnail": "",
                    "category_thumbnails": {},
                    "questions": []
                }, f, indent=2, ensure_ascii=False)
        with open(QUIZ_JSON_PATH, "r", encoding="utf-8") as f:
            try:
                self.quiz_data = json.load(f)
            except Exception:
                self.quiz_data = {"default_thumbnail": "", "category_thumbnails": {}, "questions": []}

    def _save_quiz_file(self):
        with open(QUIZ_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(self.quiz_data, f, indent=2, ensure_ascii=False)

    # -------------------------
    # Background task
    # -------------------------
    def _ensure_task_running(self):
        if self._task is None or self._task.done():
            self._task = self.bot.loop.create_task(self._quiz_loop())

    async def _quiz_loop(self):
        await self.bot.wait_until_ready()
        while True:
            cfg = await self.config.all()
            enabled = cfg.get("enabled", True)
            channel_id = cfg.get("channel_id")
            base_minutes = cfg.get("interval_minutes", 60)
            if not enabled or not channel_id:
                await asyncio.sleep(30)
                continue

            # Wait base interval then add a random offset between 5 and 10 minutes
            offset = random.randint(5 * 60, 10 * 60)
            wait_seconds = base_minutes * 60 + offset
            jitter = random.randint(-60, 60)
            wait_seconds = max(30, wait_seconds + jitter)
            try:
                await asyncio.sleep(wait_seconds)
            except asyncio.CancelledError:
                return

            cfg = await self.config.all()
            if not cfg.get("enabled", True):
                continue

            channel = self.bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    continue
            await self._post_random_quiz(channel)

    # -------------------------
    # Quiz posting and handling
    # -------------------------
    async def _expire_previous_quiz_in_channel(self, channel: discord.abc.Messageable):
        """If a previous quiz is active in this channel and unanswered, expire it immediately."""
        try:
            channel_id = channel.id
        except Exception:
            return
        prev_view = self._active_quizzes.get(channel_id)
        if not prev_view:
            return
        # If already answered or expired, nothing to do
        if prev_view.answered or prev_view._expired_handled:
            # cleanup
            try:
                del self._active_quizzes[channel_id]
            except KeyError:
                pass
            return
        # mark expired and edit message to show expired embed
        prev_view._expired_handled = True
        prev_view.answered = True  # prevent further answers
        for child in prev_view.children:
            child.disabled = True
        if prev_view.message:
            try:
                embed = Embed(
                    title="Quiz Expired",
                    description=f"**This quiz was closed because a new quiz is being posted.**\n\n**Answer:** {prev_view.correct_answer_text}",
                    color=discord.Color.dark_grey()
                )
                embed.set_footer(text="Expired — a new quiz has been posted.")
                await prev_view.message.edit(embed=embed, view=prev_view)
            except Exception:
                pass
        # remove from tracking
        try:
            del self._active_quizzes[channel_id]
        except KeyError:
            pass

    async def _post_random_quiz(self, channel: discord.abc.Messageable):
        self._load_quiz_file()
        questions = self.quiz_data.get("questions", [])
        if not questions:
            try:
                await channel.send("No quiz questions available. Admins can add questions with `[p]quiztime add`.")
            except Exception:
                pass
            return

        # expire previous quiz in this channel if present
        await self._expire_previous_quiz_in_channel(channel)

        q = random.choice(questions)
        category = q.get("category", "General")
        question_text = q.get("question", "No question text")
        correct = q.get("correct")
        wrongs = q.get("wrong", [])
        if len(wrongs) < 3:
            while len(wrongs) < 3:
                wrongs.append("N/A")
        answers = [correct] + wrongs[:3]
        random.shuffle(answers)
        correct_text = correct

        # build a nicer embed
        color = random.randint(0, 0xFFFFFF)
        embed = Embed(
            title=f"📚 Quiz — {category}",
            description=f"**{question_text}**",
            color=color
        )
        # add choices as a field with emojis/labels
        choice_lines = []
        for i, ans in enumerate(answers):
            choice_lines.append(f"**{LABELS[i]}** — {ans}")
        embed.add_field(name="Choices", value="\n".join(choice_lines), inline=False)

        # footer with reward range and time limit
        cfg = await self.config.all()
        rmin = cfg.get("reward_min", 50)
        rmax = cfg.get("reward_max", 50)
        time_limit = 60
        embed.set_footer(text=f"Be the first to click the correct button to win ({rmin}–{rmax} credits). You have {time_limit} seconds.")
        embed.timestamp = discord.utils.utcnow()

        # thumbnail
        thumb = self.quiz_data.get("category_thumbnails", {}).get(category) or self.quiz_data.get("default_thumbnail") or None
        if thumb:
            try:
                embed.set_thumbnail(url=thumb)
            except Exception:
                pass

        view = QuizView(self, correct_answer_text=correct_text, timeout=time_limit)
        # add buttons (labels A-D) with shuffled answers
        for i, ans in enumerate(answers):
            is_correct = (ans == correct)
            btn = QuizButton(label=LABELS[i], answer_text=ans, is_correct=is_correct)

            # create callback closure capturing btn
            def make_callback(b):
                async def callback(interaction: discord.Interaction):
                    await view.handle_click(interaction, b)
                return callback

            btn.callback = make_callback(btn)
            view.add_item(btn)

        try:
            msg = await channel.send(embed=embed, view=view)
            view.message = msg
            # track active quiz for this channel
            try:
                self._active_quizzes[channel.id] = view
            except Exception:
                pass
        except Exception:
            try:
                await channel.send(embed=embed)
            except Exception:
                pass

    # -------------------------
    # Leaderboard helpers
    # -------------------------
    async def _increment_leaderboard(self, member: discord.Member):
        cfg = await self.config.all()
        lb = cfg.get("leaderboard", {}) or {}
        key = str(member.id)
        lb[key] = lb.get(key, 0) + 1
        await self.config.leaderboard.set(lb)

    async def _get_reward_amount(self) -> int:
        cfg = await self.config.all()
        rmin = cfg.get("reward_min", 50)
        rmax = cfg.get("reward_max", 50)
        if rmin > rmax:
            rmin, rmax = rmax, rmin
        return random.randint(int(rmin), int(rmax))

    # -------------------------
    # Commands
    # -------------------------
    @commands.group()
    async def quiztime(self, ctx: commands.Context):
        """QuizTime commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    # Admin-only commands
    @quiztime.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def set(self, ctx: commands.Context, channel: discord.TextChannel, interval_minutes: int = 60, reward_min: int = 50, reward_max: int = 50):
        """
        Set the quiz channel, how often a quiz gets posted (in minutes), and reward range.
        Example: [p]quiztime set #quiz 60 50 100
        """
        await self.config.channel_id.set(channel.id)
        await self.config.interval_minutes.set(max(1, interval_minutes))
        await self.config.reward_min.set(max(0, reward_min))
        await self.config.reward_max.set(max(0, reward_max))
        await ctx.send(f"Quiz channel set to {channel.mention}. Interval set to {interval_minutes} minutes (random offset 5–10 minutes). Reward range set to **{reward_min}–{reward_max}** credits.")
        self._ensure_task_running()

    @quiztime.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def enable(self, ctx: commands.Context, toggle: Optional[bool] = True):
        """Enable or disable automatic quizzes. Use `false` to disable."""
        await self.config.enabled.set(bool(toggle))
        await ctx.send(f"Quizzes {'enabled' if toggle else 'disabled'}.")
        if toggle:
            self._ensure_task_running()

    @quiztime.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def add(self, ctx: commands.Context, category: str, question: str, correct: str, wrong1: str, wrong2: str, wrong3: str):
        """
        Add a question.
        Usage: [p]quiztime add "Category" "Question text" "Correct" "Wrong1" "Wrong2" "Wrong3"
        """
        self._load_quiz_file()
        q = {
            "category": category,
            "question": question,
            "correct": correct,
            "wrong": [wrong1, wrong2, wrong3]
        }
        self.quiz_data.setdefault("questions", []).append(q)
        self.quiz_data.setdefault("category_thumbnails", {}).setdefault(category, "")
        self._save_quiz_file()
        await ctx.send(f"Added question to category **{category}**.")

    @quiztime.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def delete(self, ctx: commands.Context, index: int):
        """
        Delete a question by index. Use [p]quiztime list to view indexes.
        """
        self._load_quiz_file()
        questions = self.quiz_data.get("questions", [])
        if not questions:
            await ctx.send("No questions to delete.")
            return
        if index < 1 or index > len(questions):
            await ctx.send("Index out of range. Use [p]quiztime list to see valid indexes.")
            return
        removed = questions.pop(index - 1)
        self.quiz_data["questions"] = questions
        self._save_quiz_file()
        await ctx.send(f"Removed question: **{removed.get('question')}**")

    @quiztime.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def list(self, ctx: commands.Context):
        """
        List all questions with indexes so admins can delete by index.
        """
        self._load_quiz_file()
        questions = self.quiz_data.get("questions", [])
        if not questions:
            await ctx.send("No questions available.")
            return
        lines = []
        for i, q in enumerate(questions, start=1):
            lines.append(f"{i}. [{q.get('category')}] {q.get('question')}")
        msg = box("\n".join(lines), lang="text")
        await ctx.send(msg)

    @quiztime.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def reset(self, ctx: commands.Context):
        """Reset the leaderboard."""
        await self.config.leaderboard.set({})
        await ctx.send("Leaderboard has been reset.")

    @quiztime.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def setthumbnail(self, ctx: commands.Context, category: str, url: str):
        """
        Set a thumbnail URL for a category. Use 'default' as category to set the default thumbnail.
        """
        self._load_quiz_file()
        if category.lower() == "default":
            self.quiz_data["default_thumbnail"] = url
            self._save_quiz_file()
            await ctx.send("Default thumbnail set.")
            return
        self.quiz_data.setdefault("category_thumbnails", {})[category] = url
        self._save_quiz_file()
        await ctx.send(f"Thumbnail for category **{category}** set.")

    @quiztime.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def settings(self, ctx: commands.Context):
        """
        Show all current settings for the QuizTime cog.
        """
        cfg = await self.config.all()
        channel_id = cfg.get("channel_id")
        channel = self.bot.get_channel(channel_id) if channel_id else None
        enabled = cfg.get("enabled", True)
        interval = cfg.get("interval_minutes", 60)
        rmin = cfg.get("reward_min", 50)
        rmax = cfg.get("reward_max", 50)
        lb = cfg.get("leaderboard", {}) or {}
        qcount = len(self.quiz_data.get("questions", []))
        embed = Embed(title="⚙️ QuizTime Settings", color=random.randint(0, 0xFFFFFF))
        embed.add_field(name="Channel", value=channel.mention if channel else "Not set", inline=False)
        embed.add_field(name="Enabled", value=str(enabled), inline=True)
        embed.add_field(name="Interval (minutes)", value=str(interval), inline=True)
        embed.add_field(name="Reward range", value=f"{rmin} — {rmax}", inline=True)
        embed.add_field(name="Questions stored", value=str(qcount), inline=True)
        embed.add_field(name="Leaderboard entries", value=str(len(lb)), inline=True)
        thumb = self.quiz_data.get("default_thumbnail")
        if thumb:
            try:
                embed.set_thumbnail(url=thumb)
            except Exception:
                pass
        await ctx.send(embed=embed)

    @quiztime.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def test(self, ctx: commands.Context):
        """
        Post a quiz in the current channel for testing purposes.
        """
        channel = ctx.channel
        await self._post_random_quiz(channel)
        await ctx.tick()

    # Public commands
    @quiztime.command()
    async def leaderboard(self, ctx: commands.Context, top: int = 10):
        """Show the quiz leaderboard."""
        cfg = await self.config.all()
        lb = cfg.get("leaderboard", {}) or {}
        if not lb:
            await ctx.send("No leaderboard data yet.")
            return
        items = sorted(lb.items(), key=lambda kv: kv[1], reverse=True)[:top]
        embed = Embed(title="🏆 Quiz Leaderboard", color=random.randint(0, 0xFFFFFF))
        desc_lines = []
        for user_id, score in items:
            member = ctx.guild.get_member(int(user_id)) if ctx.guild else None
            name = member.display_name if member else f"<@{user_id}>"
            desc_lines.append(f"**{name}** — {score}")
        embed.description = "\n".join(desc_lines)
        embed.set_footer(text="Top responders")
        thumb = self.quiz_data.get("default_thumbnail")
        if thumb:
            try:
                embed.set_thumbnail(url=thumb)
            except Exception:
                pass
        await ctx.send(embed=embed)
