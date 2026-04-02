import asyncio
import json
import os
import random
from typing import Optional, Dict, List

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
    "enabled": False,      # Disabled by default
    "reward_min": 50,
    "reward_max": 50,
    "offset_min": 0,       # minutes
    "offset_max": 0,       # minutes
    "leaderboard": {}
}

LABELS = ["A", "B", "C", "D"]


class QuizButton(Button):
    def __init__(self, label: str, answer_text: str, is_correct: bool):
        super().__init__(style=discord.ButtonStyle.primary, label=label)
        self.answer_text = answer_text
        self.is_correct = is_correct


class QuizView(View):
    """
    A View that stays active until explicitly expired by the cog when a new quiz is posted.
    We set timeout=None so Discord won't auto-timeout the view; expiration is handled
    by the cog when posting the next quiz in the same channel.
    """

    def __init__(self, cog, correct_answer_text: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.correct_answer_text = correct_answer_text
        self.answered = False
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return not interaction.user.bot

    async def handle_click(self, interaction: discord.Interaction, button: QuizButton):
        # If already answered or expired, inform user
        if self.answered:
            await interaction.response.send_message("Someone already answered this question.", ephemeral=True)
            return

        self.answered = True
        # disable all buttons visually
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

        # Build result embed with optional thumbnails for correct/incorrect
        if button.is_correct:
            amount = await self.cog._get_reward_amount()

            # Get currency name from bank using the guild context (interaction.guild)
            currency_name = "credits"
            try:
                if interaction.guild is not None:
                    maybe_currency = await bank.get_currency_name(interaction.guild)
                    if maybe_currency:
                        currency_name = maybe_currency
            except Exception:
                currency_name = "credits"

            try:
                await bank.deposit_credits(interaction.user, amount)
                await self.cog._increment_leaderboard(interaction.user)
                embed = Embed(
                    title="✅ Correct Answer!",
                    description=f"{interaction.user.mention} answered correctly and won **{amount} {currency_name}**!",
                    color=discord.Color.green()
                )
                embed.add_field(name="Answer", value=f"**{button.answer_text}**", inline=False)
                embed.set_footer(text="Well done! Keep an eye out for the next quiz.")
                # correct thumbnail from quiz.json if set
                thumb = self.cog.quiz_data.get("correct_thumbnail") or None
                if thumb:
                    try:
                        embed.set_thumbnail(url=thumb)
                    except Exception:
                        pass
            except Exception:
                embed = Embed(
                    title="✅ Correct Answer!",
                    description=f"{interaction.user.mention} answered correctly but I couldn't award currency (bank error).",
                    color=discord.Color.green()
                )
                embed.add_field(name="Answer", value=f"**{button.answer_text}**", inline=False)
        else:
            embed = Embed(
                title="❌ Incorrect",
                description=f"{interaction.user.mention} answered but that was incorrect.",
                color=discord.Color.red()
            )
            embed.add_field(name="Correct Answer", value=f"**{self.correct_answer_text}**", inline=False)
            embed.set_footer(text="Better luck next time!")
            # incorrect thumbnail from quiz.json if set
            thumb = self.cog.quiz_data.get("incorrect_thumbnail") or None
            if thumb:
                try:
                    embed.set_thumbnail(url=thumb)
                except Exception:
                    pass

        await interaction.response.send_message(embed=embed)


class QuizTime(commands.Cog):
    """Periodic multiple-choice quiz with bank rewards and leaderboard."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xA1B2C3D4E5F60709, force_registration=True)
        self.config.register_global(**DEFAULT_CONFIG)
        self._task: Optional[asyncio.Task] = None
        self._task_lock = asyncio.Lock()
        self._load_quiz_file()
        # track active quiz view per channel so we can expire previous when posting a new one
        self._active_quizzes: Dict[int, QuizView] = {}
        # schedule a safe startup check (non-blocking)
        try:
            asyncio.create_task(self._startup_ensure())
        except Exception:
            loop = getattr(self.bot, "loop", None)
            if loop:
                loop.create_task(self._startup_ensure())

    def cog_unload(self):
        try:
            asyncio.create_task(self._stop_background_task())
        except Exception:
            if self._task:
                try:
                    self._task.cancel()
                except Exception:
                    pass

    # -------------------------
    # Quiz JSON handling
    # -------------------------
    def _load_quiz_file(self):
        if not os.path.exists(QUIZ_JSON_PATH):
            with open(QUIZ_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "default_thumbnail": "",
                    "category_thumbnails": {},
                    "correct_thumbnail": "",
                    "incorrect_thumbnail": "",
                    "questions": []
                }, f, indent=2, ensure_ascii=False)
        with open(QUIZ_JSON_PATH, "r", encoding="utf-8") as f:
            try:
                self.quiz_data = json.load(f)
            except Exception:
                self.quiz_data = {
                    "default_thumbnail": "",
                    "category_thumbnails": {},
                    "correct_thumbnail": "",
                    "incorrect_thumbnail": "",
                    "questions": []
                }

    def _save_quiz_file(self):
        with open(QUIZ_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(self.quiz_data, f, indent=2, ensure_ascii=False)

    # -------------------------
    # Background task management (single-task guarantee)
    # -------------------------
    async def _startup_ensure(self):
        """Run once on cog load to start the background task if enabled."""
        await self.bot.wait_until_ready()
        cfg = await self.config.all()
        if cfg.get("enabled", False):
            await self._start_background_task()

    async def _start_background_task(self):
        """Start the quiz loop, ensuring any previous task is cancelled first."""
        async with self._task_lock:
            # If a task exists and is running, cancel it first to avoid duplicate posting
            if self._task and not self._task.done():
                try:
                    self._task.cancel()
                    await self._task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
                self._task = None

            # Create a single background task
            try:
                self._task = asyncio.create_task(self._quiz_loop())
            except Exception:
                loop = getattr(self.bot, "loop", None)
                if loop:
                    self._task = loop.create_task(self._quiz_loop())

    async def _stop_background_task(self):
        """Cancel the running background task if present."""
        async with self._task_lock:
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
                self._task = None

    # -------------------------
    # Quiz loop
    # -------------------------
    async def _quiz_loop(self):
        """
        Single background loop that reads config each iteration.
        Ensures wait_seconds is computed robustly and never falls below the base interval.
        """
        await self.bot.wait_until_ready()
        while True:
            cfg = await self.config.all()
            enabled = cfg.get("enabled", False)
            channel_id = cfg.get("channel_id")
            base_minutes = cfg.get("interval_minutes", 60)
            offset_min = cfg.get("offset_min", 0)
            offset_max = cfg.get("offset_max", 0)

            # If disabled or no channel set, sleep and re-check
            if not enabled or not channel_id:
                await asyncio.sleep(30)
                continue

            # compute base seconds (ensure non-negative)
            try:
                base_seconds = max(0, int(base_minutes) * 60)
            except Exception:
                base_seconds = 60

            # compute offset seconds (if both zero => no offset)
            offset_seconds = 0
            try:
                omn = int(offset_min)
                omx = int(offset_max)
                if omn > omx:
                    omn, omx = omx, omn
                if omn == 0 and omx == 0:
                    offset_seconds = 0
                else:
                    offset_seconds = random.randint(omn * 60, omx * 60)
            except Exception:
                offset_seconds = 0

            # small jitter but never reduce below base_seconds
            jitter = random.randint(-10, 10)  # +/- 10 seconds
            wait_seconds = base_seconds + offset_seconds + jitter
            if wait_seconds < base_seconds:
                wait_seconds = base_seconds

            # enforce a sensible minimum sleep to avoid rapid loops
            if wait_seconds < 5:
                wait_seconds = max(5, base_seconds)

            try:
                await asyncio.sleep(wait_seconds)
            except asyncio.CancelledError:
                return

            # re-check enabled flag after sleep
            cfg = await self.config.all()
            if not cfg.get("enabled", False):
                continue

            # fetch channel and post
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    # if fetching fails, wait a bit before retrying to avoid tight loop
                    await asyncio.sleep(30)
                    continue

            # Post quiz (this function is safe and idempotent)
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
        # If already answered or already handled, cleanup and return
        if prev_view.answered:
            try:
                del self._active_quizzes[channel_id]
            except KeyError:
                pass
            return

        # mark expired to prevent further answers
        prev_view.answered = True
        for child in prev_view.children:
            child.disabled = True
        if prev_view.message:
            try:
                embed = Embed(
                    title="⏸️ Quiz Closed",
                    description=f"**This quiz was closed because a new quiz is being posted.**\n\n**Answer:** {prev_view.correct_answer_text}",
                    color=discord.Color.dark_grey()
                )
                embed.set_footer(text="Expired — a new quiz has been posted.")
                thumb = self.quiz_data.get("incorrect_thumbnail") or self.quiz_data.get("default_thumbnail") or None
                if thumb:
                    try:
                        embed.set_thumbnail(url=thumb)
                    except Exception:
                        pass
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

        # expire previous quiz in this channel if present (only expire when posting a new quiz)
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
        # add choices as a field
        choice_lines = []
        for i, ans in enumerate(answers):
            choice_lines.append(f"**{LABELS[i]}** — {ans}")
        embed.add_field(name="Choices", value="\n".join(choice_lines), inline=False)

        # footer: only the requested short text
        embed.set_footer(text="Be the first to click the correct button to win")
        embed.timestamp = discord.utils.utcnow()

        # thumbnail: category -> default fallback
        thumb = self.quiz_data.get("category_thumbnails", {}).get(category) or self.quiz_data.get("default_thumbnail") or None
        if thumb:
            try:
                embed.set_thumbnail(url=thumb)
            except Exception:
                pass

        # create a view that does NOT auto-timeout; it will be expired when the next quiz posts
        view = QuizView(self, correct_answer_text=correct_text)
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
    # Utility: safe long message sender
    # -------------------------
    async def _send_long_message(self, ctx: commands.Context, text: str, *, box_lang: Optional[str] = "text"):
        """
        Send `text` in chunks that fit Discord's message size limits.
        Uses redbot.core.utils.chat_formatting.box for formatting each chunk.
        """
        if not text:
            await ctx.send("")
            return

        # Discord message content limit is 2000 characters; be conservative and use 1900
        limit = 1900
        lines = text.splitlines(keepends=True)
        chunks: List[str] = []
        current = ""
        for line in lines:
            if len(current) + len(line) > limit:
                chunks.append(current)
                current = line
            else:
                current += line
        if current:
            chunks.append(current)

        for chunk in chunks:
            try:
                await ctx.send(box(chunk, lang=box_lang))
            except Exception:
                # fallback: send plain chunk if box fails
                try:
                    await ctx.send(chunk[:1900])
                except Exception:
                    pass

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
        await self.config.interval_minutes.set(max(0, interval_minutes))
        await self.config.reward_min.set(max(0, reward_min))
        await self.config.reward_max.set(max(0, reward_max))
        await ctx.send(f"Quiz channel set to {channel.mention}. Interval set to {interval_minutes} minutes (plus configured offset). Reward range set to **{reward_min}–{reward_max}** credits.")

        # If enabled, restart the background task so it picks up the new channel immediately.
        cfg = await self.config.all()
        if cfg.get("enabled", False):
            await self._start_background_task()

    @quiztime.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def enable(self, ctx: commands.Context, toggle: Optional[bool] = None):
        """
        Enable or disable automatic quizzes.
        Usage:
          [p]quiztime enable        -> toggles current state
          [p]quiztime enable true   -> enable
          [p]quiztime enable false  -> disable
        """
        current = (await self.config.enabled())
        if toggle is None:
            new_state = not current
        else:
            new_state = bool(toggle)
        await self.config.enabled.set(new_state)
        await ctx.send(f"Quizzes {'enabled' if new_state else 'disabled'}.")
        if new_state:
            await self._start_background_task()
        else:
            await self._stop_background_task()

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
        This command will chunk output to avoid Discord message length limits.
        """
        self._load_quiz_file()
        questions = self.quiz_data.get("questions", [])
        if not questions:
            await ctx.send("No questions available.")
            return

        lines = []
        for i, q in enumerate(questions, start=1):
            cat = q.get('category', 'General')
            qtext = q.get('question', 'No question text')
            lines.append(f"{i}. [{cat}] {qtext}")

        # Join with newlines and send in chunks using helper
        full_text = "\n".join(lines)
        await self._send_long_message(ctx, full_text, box_lang="text")

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
    async def setembedthumbs(self, ctx: commands.Context, which: str, url: str):
        """
        Set the thumbnail URL used for result embeds.
        Usage: [p]quiztime setembedthumbs correct <url>
               [p]quiztime setembedthumbs incorrect <url>
        """
        self._load_quiz_file()
        key = which.lower()
        if key not in ("correct", "incorrect"):
            await ctx.send("Invalid option. Use 'correct' or 'incorrect'.")
            return
        if key == "correct":
            self.quiz_data["correct_thumbnail"] = url
            self._save_quiz_file()
            await ctx.send("Correct-answer embed thumbnail set.")
        else:
            self.quiz_data["incorrect_thumbnail"] = url
            self._save_quiz_file()
            await ctx.send("Incorrect-answer embed thumbnail set.")

    @quiztime.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def offset(self, ctx: commands.Context, min_minutes: int, max_minutes: int):
        """
        Set the random offset range (in minutes) added to the base interval.
        Use `0 0` to disable any offset.
        Example: [p]quiztime offset 1 5
        """
        if min_minutes < 0 or max_minutes < 0:
            await ctx.send("Offset values must be zero or positive integers.")
            return
        await self.config.offset_min.set(min_minutes)
        await self.config.offset_max.set(max_minutes)
        await ctx.send(f"Offset range set to **{min_minutes}–{max_minutes}** minutes. (Use `0 0` for no offset.)")

    @quiztime.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def settings(self, ctx: commands.Context):
        """
        Show all current settings for the QuizTime cog.
        """
        cfg = await self.config.all()
        channel_id = cfg.get("channel_id")
        channel = self.bot.get_channel(channel_id) if channel_id else None
        enabled = cfg.get("enabled", False)
        interval = cfg.get("interval_minutes", 60)
        rmin = cfg.get("reward_min", 50)
        rmax = cfg.get("reward_max", 50)
        offset_min = cfg.get("offset_min", 0)
        offset_max = cfg.get("offset_max", 0)
        lb = cfg.get("leaderboard", {}) or {}
        qcount = len(self.quiz_data.get("questions", []))
        embed = Embed(title="⚙️ QuizTime Settings", color=random.randint(0, 0xFFFFFF))
        embed.add_field(name="Channel", value=channel.mention if channel else "Not set", inline=False)
        embed.add_field(name="Enabled", value=str(enabled), inline=True)
        embed.add_field(name="Interval (minutes)", value=str(interval), inline=True)
        embed.add_field(name="Offset range (minutes)", value=f"{offset_min} — {offset_max}", inline=True)
        embed.add_field(name="Reward range", value=f"{rmin} — {rmax}", inline=True)
        embed.add_field(name="Questions stored", value=str(qcount), inline=True)
        embed.add_field(name="Leaderboard entries", value=str(len(lb)), inline=True)
        # show whether embed thumbnails are set
        correct_thumb = bool(self.quiz_data.get("correct_thumbnail"))
        incorrect_thumb = bool(self.quiz_data.get("incorrect_thumbnail"))
        embed.add_field(name="Correct embed thumbnail set", value=str(correct_thumb), inline=True)
        embed.add_field(name="Incorrect embed thumbnail set", value=str(incorrect_thumb), inline=True)
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
