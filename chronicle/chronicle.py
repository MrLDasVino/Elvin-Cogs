from __future__ import annotations

import asyncio
import copy
import fnmatch
import io
import json
import os
import platform
import shutil
import socket
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import discord
from redbot.core import Config, commands, data_manager
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_list, pagify
from redbot.core.utils.predicates import MessagePredicate

try:
    from redbot.core import __version__ as RED_VERSION
except ImportError:
    RED_VERSION = "unknown"

SCAN_EXTENSIONS = {".json", ".yaml", ".yml", ".txt", ".cfg", ".ini"}
DEFAULT_EXCLUDE_PATTERNS = ["__pycache__", "*.pyc", "*.log", ".git", ".venv", "venv"]


class Chronicle(commands.Cog):
    """Backup, export, and restore your entire Red instance."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.data_path = data_manager.cog_data_path(self)
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.config = Config.get_conf(self, identifier=356214879123, force_registration=True)
        self.config.register_global(
            backup_directory=None,
            exclude_patterns=list(DEFAULT_EXCLUDE_PATTERNS),
        )

    async def red_get_data_for_user(self, *, user_id: int) -> Dict[str, Any]:
        return {}

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:
        pass

    @commands.group(name="chronicle")
    @commands.is_owner()
    async def chronicle(self, ctx: commands.Context) -> None:
        """Tools to back up and restore your entire Red instance.

        Typical flow: on the old machine, run `chronicle backup manifest`
        (and optionally `chronicle backup full`) and copy your data folder
        to the new machine. If this instance uses PostgreSQL storage, also
        run `chronicle backup database` / `chronicle restore database`,
        since neither `backup full` nor `restore all` touch the database.
        On the new machine, load this cog and run `chronicle restore all`
        with the exported files attached, then `chronicle restore paths`
        if anything still points at the old machine. See `chronicle
        backup` and `chronicle restore` for the individual steps.
        """

    @chronicle.command(name="info")
    async def chronicle_info(self, ctx: commands.Context) -> None:
        """Show information about this Red instance."""
        downloader = self._get_downloader()
        repos = await self._gather_repo_info(downloader) if downloader else []
        cogs = await self._gather_cog_info(downloader) if downloader else []
        instance_path = self._instance_data_path()
        loop = asyncio.get_running_loop()
        try:
            size = await loop.run_in_executor(None, self._dir_size, instance_path)
            size_text = self._humanize_bytes(size)
        except OSError:
            size_text = "unknown"
        try:
            storage_type = data_manager.storage_type()
        except Exception:
            storage_type = "unknown"
        local_ip = self._get_local_ip()
        public_ip = await self._get_public_ip()
        lines = [
            f"Instance name: {self._get_instance_name()}",
            f"Data path: {instance_path}",
            f"Data path size: {size_text}",
            f"Storage type: {storage_type}",
            f"Device IP: {local_ip}",
            f"ISP IP: {public_ip}",
            f"Red version: {RED_VERSION}",
            f"discord.py version: {discord.__version__}",
            f"Python version: {platform.python_version()}",
            f"Platform: {platform.platform()}",
            f"Loaded cogs: {len(self.bot.cogs)}",
            f"Downloader loaded: {'yes' if downloader else 'no'}",
            f"Downloader repos: {len(repos)}",
            f"Downloader-installed cogs: {len(cogs)}",
            f"git available: {'yes' if shutil.which('git') else 'no'}",
            f"pg_dump available: {'yes' if shutil.which('pg_dump') else 'no'}",
            f"psql available: {'yes' if shutil.which('psql') else 'no'}",
        ]
        if storage_type == "Postgres":
            try:
                details = data_manager.storage_details()
                lines.append(f"Postgres host: {details.get('host', 'unknown')}")
                lines.append(f"Postgres port: {details.get('port', 'unknown')}")
                lines.append(f"Postgres database: {details.get('database', 'unknown')}")
                lines.append(f"Postgres user: {details.get('user', 'unknown')}")
            except Exception:
                lines.append("Postgres details: could not be read")
        lines.append(
            "# Note: individual cogs may connect to their own separate "
            "database, independent of the above. Check each cog's own "
            "documentation."
        )
        for page in pagify("\n".join(lines)):
            await ctx.send(box(page, lang="yaml"))

    @chronicle.group(name="backup")
    async def chronicle_backup(self, ctx: commands.Context) -> None:
        """Create backups of this instance."""

    @chronicle_backup.command(name="manifest")
    async def chronicle_backup_manifest(self, ctx: commands.Context) -> None:
        """Export a manifest of repos, cogs, and pip dependencies as two files.

        If this instance uses PostgreSQL storage, the manifest also
        records the host, port, database name, and user for reference —
        never the password. It does not dump the database itself; use
        `chronicle backup database` for that.
        """
        async with ctx.typing():
            manifest = await self._build_manifest()
            try:
                freeze_lines = await self._pip_freeze()
            except Exception as exc:
                freeze_lines = []
                await ctx.send(f"Warning: could not run pip freeze ({exc}).")
            manifest_bytes = json.dumps(manifest, indent=2, default=str).encode("utf-8")
            requirements_bytes = ("\n".join(freeze_lines) + "\n").encode("utf-8")
        files = [
            discord.File(io.BytesIO(manifest_bytes), filename="chronicle_manifest.json"),
            discord.File(io.BytesIO(requirements_bytes), filename="chronicle_requirements.txt"),
        ]
        await ctx.send(
            "Here is your Chronicle manifest and dependency export. Keep both files "
            "together and use `chronicle restore` on the new machine to reinstall "
            "everything they describe.",
            files=files,
        )

    @chronicle_backup.command(name="database")
    async def chronicle_backup_database(
        self, ctx: commands.Context, connection: Optional[str] = None
    ) -> None:
        """Dump a PostgreSQL database to disk.

        With no arguments, dumps the database this Red instance itself is
        configured to use (only works if this instance's storage backend
        is Postgres). To back up a *different* Postgres database instead
        — for example one a specific cog connects to on its own,
        separately from Red's own storage — pass a connection string:
        `postgresql://user:password@host:port/dbname`

        Security note: if your connection string includes a password, run
        this in a DM rather than a server channel, since Discord keeps
        message history. Chronicle deletes your command message
        afterward where it can.

        Requires the `pg_dump` command line tool. Saves to your backups
        directory.
        """
        if connection:
            pg_target = [connection, "--no-password"]
            env = os.environ.copy()
            label = "the provided database"
        else:
            try:
                storage_type = data_manager.storage_type()
            except Exception:
                storage_type = "unknown"
            if storage_type != "Postgres":
                await ctx.send(
                    f"This instance uses the `{storage_type}` storage backend, "
                    "not Postgres, so there's nothing to auto-detect. If a "
                    "specific cog uses its own separate Postgres database, run "
                    "this again with a connection string: "
                    "`postgresql://user:password@host:port/dbname`"
                )
                return
            try:
                details = data_manager.storage_details()
            except Exception as exc:
                await ctx.send(f"Could not read the database connection details: {exc}")
                return
            pg_target = self._pg_connection_args(details)
            env = self._pg_env(details)
            label = "this instance's database"

        if shutil.which("pg_dump") is None:
            await ctx.send(
                "The `pg_dump` command was not found on this machine. Install "
                "the PostgreSQL client tools to use this command."
            )
            return

        backups_dir = await self._backups_dir()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dump_path = backups_dir / f"chronicle_database_{timestamp}.sql"
        args = [
            "pg_dump",
            *pg_target,
            "--format=plain",
            "--clean",
            "--if-exists",
            "--file",
            str(dump_path),
        ]
        async with ctx.typing():
            code, out, err = await self._run_command(*args, env=env)

        if connection and ctx.guild is not None:
            try:
                await ctx.message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass

        if code != 0:
            await ctx.send(f"`pg_dump` failed with exit code {code}.")
            output = (out + "\n" + err).strip() or "No output."
            for page in pagify(output, page_length=1900):
                await ctx.send(box(page))
            return

        size = dump_path.stat().st_size
        await ctx.send(
            f"Dumped {label} to `{dump_path}` ({self._humanize_bytes(size)})."
        )

    @chronicle_backup.command(name="full")
    async def chronicle_backup_full(self, ctx: commands.Context, *cog_names: str) -> None:
        """Archive the whole data folder, or only the given cogs' data, to disk.

        With no arguments this archives your entire data folder, which can
        be large and slow. Pass one or more cog names to archive only
        those cogs' data instead. You will be asked to confirm before
        anything is written. The finished archive is always saved to disk
        under your backups directory (see `chronicle set backupdir`) — it
        is never uploaded here, since a full instance archive is almost
        always far too large for Discord's attachment limit. Transfer the
        file to the new machine yourself (scp, rsync, a USB drive, cloud
        storage, whatever you have available). If this instance uses
        PostgreSQL storage, this does not include your database contents
        — use `chronicle backup database` for that separately.

        Example: `[p]chronicle backup full Audio Trivia`
        """
        try:
            storage_type = data_manager.storage_type()
        except Exception:
            storage_type = "unknown"
        if storage_type == "Postgres":
            await ctx.send(
                "This instance uses Postgres storage. This archive will not "
                "include your database contents, only files on disk. Run "
                "`chronicle backup database` separately to cover the database."
            )
        instance_path = self._instance_data_path()
        exclude_patterns = await self.config.exclude_patterns()
        loop = asyncio.get_running_loop()

        if cog_names:
            targets = []
            for name in cog_names:
                path = instance_path / "cogs" / name
                if not path.exists():
                    await ctx.send(f"No data folder found for cog `{name}`, skipping.")
                    continue
                targets.append(path)
            if not targets:
                await ctx.send("No valid cog data folders found.")
                return
        else:
            targets = [instance_path]

        approx_size = 0
        for target in targets:
            approx_size += await loop.run_in_executor(None, self._dir_size, target)

        if not await self._confirm(
            ctx,
            f"This will archive about {self._humanize_bytes(approx_size)} of data. Continue?",
        ):
            await ctx.send("Cancelled.")
            return

        backups_dir = await self._backups_dir()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        archive_name = f"chronicle_backup_{timestamp}.zip"
        tmp_dir = Path(tempfile.mkdtemp())
        tmp_zip = tmp_dir / archive_name

        async with ctx.typing():
            manifest = await self._build_manifest()
            try:
                freeze_lines = await self._pip_freeze()
            except Exception:
                freeze_lines = []
            await loop.run_in_executor(
                None,
                self._write_zip,
                tmp_zip,
                targets,
                instance_path,
                exclude_patterns,
                manifest,
                freeze_lines,
            )
            final_path = backups_dir / archive_name
            shutil.move(str(tmp_zip), str(final_path))
            shutil.rmtree(tmp_dir, ignore_errors=True)

        size = final_path.stat().st_size
        await ctx.send(
            f"Backup saved to `{final_path}` ({self._humanize_bytes(size)}).\n"
            "Copy this file to the new machine yourself, then extract it into "
            "that instance's data folder and use `chronicle restore` for the rest."
        )

    @chronicle_backup.command(name="list")
    async def chronicle_backup_list(self, ctx: commands.Context) -> None:
        """List saved backup archives."""
        backups_dir = await self._backups_dir()
        entries = sorted(backups_dir.glob("*.zip"))
        if not entries:
            await ctx.send("No backups saved yet.")
            return
        lines = []
        for entry in entries:
            stat = entry.stat()
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            lines.append(f"{entry.name}  {self._humanize_bytes(stat.st_size)}  {modified}")
        for page in pagify("\n".join(lines)):
            await ctx.send(box(page, lang="yaml"))

    @chronicle_backup.command(name="delete")
    async def chronicle_backup_delete(self, ctx: commands.Context, filename: str) -> None:
        """Delete a saved backup archive.

        Use `chronicle backup list` to see available filenames. You will
        be asked to confirm before the file is removed.
        """
        backups_dir = await self._backups_dir()
        target = (backups_dir / filename).resolve()
        if target.parent != backups_dir.resolve() or not target.exists():
            await ctx.send("That backup file was not found.")
            return
        if not await self._confirm(ctx, f"Delete `{filename}`? This cannot be undone."):
            await ctx.send("Cancelled.")
            return
        target.unlink()
        await ctx.send(f"Deleted `{filename}`.")

    @chronicle.group(name="restore")
    async def chronicle_restore(self, ctx: commands.Context) -> None:
        """Restore dependencies, repos, cogs, and paths on a new machine."""

    @chronicle_restore.command(name="dependencies")
    async def chronicle_restore_dependencies(self, ctx: commands.Context) -> None:
        """Install pip dependencies from an attached requirements text file.

        Attach the file to this command, or reply to a message that has
        one attached. Lines starting with `#` or `-` (comments and pip
        options) are skipped. You will be asked to confirm the package
        count before anything installs.
        """
        attachment = await self._find_attachment(ctx, ".txt")
        if attachment is None:
            await ctx.send(
                "Attach a requirements text file to this command, or reply to a "
                "message that has one attached."
            )
            return
        data = await attachment.read()
        lines = self._parse_requirement_lines(data)
        if not lines:
            await ctx.send("That file has no installable packages listed.")
            return
        if not await self._confirm(
            ctx, f"Install {len(lines)} package(s) via pip? This may take a while."
        ):
            await ctx.send("Cancelled.")
            return
        async with ctx.typing():
            await self._install_dependencies(ctx, lines)

    @chronicle_restore.command(name="repos")
    async def chronicle_restore_repos(self, ctx: commands.Context) -> None:
        """Re-add Downloader repos listed in an attached manifest file.

        Requires the Downloader cog to be loaded. Repos already present
        (matched by name) are skipped automatically. Run this before
        `chronicle restore cogs`, which needs the repos to already exist.
        """
        downloader = self._get_downloader()
        if downloader is None:
            await ctx.send("The Downloader cog must be loaded first: `[p]load downloader`.")
            return
        manifest = await self._read_manifest_attachment(ctx)
        if manifest is None:
            return
        await self._restore_repos(ctx, downloader, manifest.get("repos", []))

    @chronicle_restore.command(name="cogs")
    async def chronicle_restore_cogs(self, ctx: commands.Context) -> None:
        """Install cogs listed in an attached manifest file.

        Requires the Downloader cog to be loaded, and the cogs' repos to
        already be added (run `chronicle restore repos` first if needed).
        Cogs already installed are skipped automatically. You still need
        to `[p]load` each cog afterward.
        """
        downloader = self._get_downloader()
        if downloader is None:
            await ctx.send("The Downloader cog must be loaded first: `[p]load downloader`.")
            return
        manifest = await self._read_manifest_attachment(ctx)
        if manifest is None:
            return
        await self._restore_cogs(ctx, downloader, manifest.get("cogs", []))

    @chronicle_restore.command(name="database")
    async def chronicle_restore_database(
        self, ctx: commands.Context, connection: Optional[str] = None
    ) -> None:
        """Restore a PostgreSQL dump into a database.

        Attach a `.sql` file produced by `chronicle backup database`.
        With no other arguments, restores into this instance's own
        configured database (only works if this instance's storage
        backend is Postgres). To restore into a *different* Postgres
        database instead — for example one a specific cog uses on its
        own — pass a connection string:
        `postgresql://user:password@host:port/dbname`

        This overwrites existing data in the target database and cannot
        be undone, so you will be asked to confirm first. Requires the
        `psql` command line tool. Restart your bot once it finishes.

        Security note: if your connection string includes a password, run
        this in a DM rather than a server channel, since Discord keeps
        message history. Chronicle deletes your command message
        afterward where it can.
        """
        if shutil.which("psql") is None:
            await ctx.send(
                "The `psql` command was not found on this machine. Install "
                "the PostgreSQL client tools to use this command."
            )
            return
        attachment = await self._find_attachment(ctx, ".sql")
        if attachment is None:
            await ctx.send("Attach a `.sql` database dump file to this command.")
            return

        if connection:
            psql_target = [connection, "--no-password"]
            env = os.environ.copy()
            target_label = "the provided database"
        else:
            try:
                storage_type = data_manager.storage_type()
            except Exception:
                storage_type = "unknown"
            if storage_type != "Postgres":
                await ctx.send(
                    f"This instance is configured to use the `{storage_type}` "
                    "storage backend, not Postgres. If you're restoring into a "
                    "different Postgres database, pass a connection string: "
                    "`postgresql://user:password@host:port/dbname`"
                )
                return
            try:
                details = data_manager.storage_details()
            except Exception as exc:
                await ctx.send(f"Could not read the database connection details: {exc}")
                return
            psql_target = self._pg_connection_args(details)
            env = self._pg_env(details)
            database_name = details.get("database") or "(default)"
            host = details.get("host") or "(default)"
            target_label = f"database `{database_name}` on `{host}`"

        if not await self._confirm(
            ctx,
            f"This will overwrite existing data in {target_label}. This "
            "cannot be undone. Continue?",
        ):
            await ctx.send("Cancelled.")
            return

        data = await attachment.read()
        tmp_dir = Path(tempfile.mkdtemp())
        dump_path = tmp_dir / "restore.sql"
        dump_path.write_bytes(data)
        args = [
            "psql",
            *psql_target,
            "--set",
            "ON_ERROR_STOP=1",
            "--file",
            str(dump_path),
        ]
        async with ctx.typing():
            code, out, err = await self._run_command(*args, env=env)
        shutil.rmtree(tmp_dir, ignore_errors=True)

        if connection and ctx.guild is not None:
            try:
                await ctx.message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass

        status = "completed" if code == 0 else f"failed with exit code {code}"
        await ctx.send(f"Database restore {status}. Restart your bot to pick up the changes.")
        output = (out + "\n" + err).strip()
        if output:
            for page in pagify(output, page_length=1900):
                await ctx.send(box(page))

    @chronicle_restore.command(name="paths")
    async def chronicle_restore_paths(
        self,
        ctx: commands.Context,
        old_path: Optional[str] = None,
        new_path: Optional[str] = None,
        apply: bool = False,
    ) -> None:
        """Find and fix hardcoded absolute paths left over from the old machine.

        This defaults to a dry run: it only lists the files that still
        contain the old path and changes nothing. To actually rewrite
        those files, run the command again with `True` as the last
        argument. A `.bak` backup is kept next to each changed file.

        If old_path is omitted, attach a chronicle manifest file and its
        recorded data path is used instead. If new_path is omitted, this
        instance's current data path is used.

        Examples:
        `[p]chronicle restore paths /old/data/path`
        `[p]chronicle restore paths /old/data/path /new/data/path True`
        """
        if old_path is None:
            if not ctx.message.attachments and not (
                ctx.message.reference
                and isinstance(ctx.message.reference.resolved, discord.Message)
                and ctx.message.reference.resolved.attachments
            ):
                await ctx.send(
                    "Provide the old data path as an argument, or attach a "
                    "chronicle manifest file to read it from."
                )
                return
            manifest = await self._read_manifest_attachment(ctx)
            if manifest is None:
                return
            old_path = manifest.get("data_path")
            if not old_path:
                await ctx.send("The attached manifest does not contain a data path.")
                return
            await ctx.send(f"Using old path from manifest: `{old_path}`")
        target_new = Path(new_path) if new_path else self._instance_data_path()
        old_path_str = old_path.rstrip("/\\")
        new_path_str = str(target_new).rstrip("/\\")
        if old_path_str == new_path_str:
            await ctx.send("Old and new paths are the same, nothing to do.")
            return

        instance_path = self._instance_data_path()
        loop = asyncio.get_running_loop()
        matches = await loop.run_in_executor(
            None, self._scan_for_path, instance_path, old_path_str
        )
        if not matches:
            await ctx.send("No files containing the old path were found.")
            return

        if not apply:
            lines = [str(m.relative_to(instance_path)) for m in matches]
            await ctx.send(
                f"Found {len(matches)} file(s) containing the old path. Re-run this "
                "command with `True` as the last argument to apply the fix. Files:"
            )
            for page in pagify("\n".join(lines)):
                await ctx.send(box(page))
            return

        if not await self._confirm(
            ctx,
            f"Rewrite {len(matches)} file(s), replacing the old path with the new one? "
            "A `.bak` backup will be kept next to each changed file.",
        ):
            await ctx.send("Cancelled.")
            return

        changed, failed = [], []
        for fp in matches:
            try:
                content = fp.read_text(encoding="utf-8")
                backup_path = fp.with_suffix(fp.suffix + ".bak")
                if not backup_path.exists():
                    shutil.copy2(fp, backup_path)
                fp.write_text(content.replace(old_path_str, new_path_str), encoding="utf-8")
                changed.append(str(fp.relative_to(instance_path)))
            except OSError as exc:
                failed.append(f"{fp}: {exc}")

        await ctx.send(f"Updated {len(changed)} file(s).")
        for page in pagify("\n".join(changed)):
            await ctx.send(box(page))
        if failed:
            await ctx.send("Some files could not be updated:")
            for page in pagify("\n".join(failed)):
                await ctx.send(box(page))

    @chronicle_restore.command(name="all")
    async def chronicle_restore_all(self, ctx: commands.Context) -> None:
        """Run dependency, repo, and cog restoration in one step.

        Attach both `chronicle_manifest.json` and
        `chronicle_requirements.txt` to this command. This runs
        `chronicle restore dependencies`, `repos`, and `cogs` in
        sequence, but does not touch file paths or a PostgreSQL database —
        run `chronicle restore paths` and/or `chronicle restore database`
        separately afterward if needed. Newly installed cogs still need
        `[p]load`.
        """
        manifest_attachment = await self._find_attachment(ctx, ".json")
        requirements_attachment = await self._find_attachment(ctx, ".txt")
        if manifest_attachment is None or requirements_attachment is None:
            await ctx.send(
                "Attach both `chronicle_manifest.json` and `chronicle_requirements.txt` "
                "to this command."
            )
            return
        try:
            manifest = json.loads(await manifest_attachment.read())
        except json.JSONDecodeError:
            await ctx.send("The manifest file is not valid JSON.")
            return
        requirements_data = await requirements_attachment.read()
        lines = self._parse_requirement_lines(requirements_data)

        await ctx.send(
            f"Starting full restore: {len(lines)} package(s), "
            f"{len(manifest.get('repos', []))} repo(s), "
            f"{len(manifest.get('cogs', []))} cog(s)."
        )
        if lines:
            async with ctx.typing():
                await self._install_dependencies(ctx, lines)

        downloader = self._get_downloader()
        if downloader is not None:
            await self._restore_repos(ctx, downloader, manifest.get("repos", []))
            await self._restore_cogs(ctx, downloader, manifest.get("cogs", []))
        else:
            await ctx.send(
                "Downloader is not loaded, skipping repo and cog restoration. Run "
                "`[p]load downloader`, then `chronicle restore repos` and "
                "`chronicle restore cogs`."
            )
        await ctx.send(
            "Restore finished. Review the messages above, then restart your bot to "
            "make sure any newly installed packages are picked up."
        )

    @chronicle.group(name="set")
    async def chronicle_set(self, ctx: commands.Context) -> None:
        """Configure Chronicle's backup behaviour."""

    @chronicle_set.command(name="backupdir")
    async def chronicle_set_backupdir(
        self, ctx: commands.Context, *, path: Optional[str] = None
    ) -> None:
        """View or set a custom directory for saved backups.

        Run with no path to see the current location. Provide a path to
        change it; the folder is created if it doesn't exist. Defaults to
        a `backups` folder inside this cog's own data directory.
        """
        if path is None:
            current = await self.config.backup_directory()
            location = current or str(self.data_path / "backups")
            await ctx.send(f"Backups are currently saved to `{location}`.")
            return
        target = Path(path).expanduser()
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            await ctx.send(f"That path could not be used: {exc}")
            return
        await self.config.backup_directory.set(str(target))
        await ctx.send(f"Backups will now be saved to `{target}`.")

    @chronicle_set.command(name="exclude")
    async def chronicle_set_exclude(
        self, ctx: commands.Context, action: str, *, pattern: Optional[str] = None
    ) -> None:
        """Manage glob patterns excluded from full backups: add, remove, or list.

        These patterns are matched against file and folder names (not
        full paths) during `chronicle backup full`. Defaults include
        things like `__pycache__` and `*.log`.

        Examples:
        `[p]chronicle set exclude add *.tmp`
        `[p]chronicle set exclude remove *.tmp`
        `[p]chronicle set exclude list`
        """
        action = action.lower()
        patterns = await self.config.exclude_patterns()
        if action == "list":
            await ctx.send(box("\n".join(patterns) or "No patterns set."))
            return
        if pattern is None:
            await ctx.send("Provide a pattern to add or remove.")
            return
        if action == "add":
            if pattern not in patterns:
                patterns.append(pattern)
                await self.config.exclude_patterns.set(patterns)
            await ctx.send(f"Added `{pattern}` to the exclude list.")
        elif action == "remove":
            if pattern in patterns:
                patterns.remove(pattern)
                await self.config.exclude_patterns.set(patterns)
                await ctx.send(f"Removed `{pattern}` from the exclude list.")
            else:
                await ctx.send("That pattern was not in the exclude list.")
        else:
            await ctx.send("Action must be `add`, `remove`, or `list`.")

    def _instance_data_path(self) -> Path:
        return data_manager.cog_data_path(self).parent.parent

    @staticmethod
    def _get_instance_name() -> str:
        try:
            value = data_manager.instance_name
            if callable(value):
                value = value()
            return str(value) if value else "unknown"
        except Exception:
            return "unknown"

    async def _backups_dir(self) -> Path:
        custom = await self.config.backup_directory()
        base = Path(custom) if custom else (self.data_path / "backups")
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _get_downloader(self):
        return self.bot.get_cog("Downloader")

    async def _gather_repo_info(self, downloader) -> List[Dict[str, Any]]:
        repos = []
        manager = getattr(downloader, "_repo_manager", None)
        if manager is None:
            return repos
        for repo in list(getattr(manager, "repos", [])):
            repos.append(
                {
                    "name": getattr(repo, "name", None),
                    "url": getattr(repo, "url", None),
                    "branch": getattr(repo, "branch", None),
                    "commit": getattr(repo, "commit", None),
                }
            )
        return repos

    async def _gather_cog_info(self, downloader) -> List[Dict[str, Any]]:
        cogs = []
        try:
            installed = await downloader.installed_cogs()
        except Exception:
            return cogs
        for module in installed:
            repo_name = getattr(module, "repo_name", None)
            if not repo_name:
                repo = getattr(module, "repo", None)
                repo_name = getattr(repo, "name", None) if repo else None
            cogs.append(
                {
                    "name": getattr(module, "name", None),
                    "repo_name": repo_name,
                    "commit": getattr(module, "commit", None),
                    "pinned": getattr(module, "pinned", False),
                }
            )
        return cogs

    async def _build_manifest(self) -> Dict[str, Any]:
        downloader = self._get_downloader()
        repos = await self._gather_repo_info(downloader) if downloader else []
        cogs = await self._gather_cog_info(downloader) if downloader else []
        try:
            storage_type = data_manager.storage_type()
        except Exception:
            storage_type = "unknown"
        storage_details_safe = None
        if storage_type == "Postgres":
            try:
                raw_details = data_manager.storage_details()
                storage_details_safe = {
                    k: v for k, v in raw_details.items() if k != "password"
                }
            except Exception:
                storage_details_safe = None
        return {
            "chronicle_version": "1.0",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "instance_name": self._get_instance_name(),
            "data_path": str(self._instance_data_path()),
            "storage_type": storage_type,
            "storage_details": storage_details_safe,
            "red_version": RED_VERSION,
            "discord_py_version": discord.__version__,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "loaded_cogs": sorted(self.bot.cogs.keys()),
            "repos": repos,
            "cogs": cogs,
        }

    async def _run_command(
        self, *args: str, env: Optional[Dict[str, str]] = None
    ) -> Tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await process.communicate()
        return (
            process.returncode,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )

    @staticmethod
    def _pg_connection_args(details: Dict[str, Any]) -> List[str]:
        args: List[str] = []
        if details.get("host"):
            args += ["--host", str(details["host"])]
        if details.get("port"):
            args += ["--port", str(details["port"])]
        if details.get("user"):
            args += ["--username", str(details["user"])]
        if details.get("database"):
            args += ["--dbname", str(details["database"])]
        args.append("--no-password")
        return args

    @staticmethod
    def _pg_env(details: Dict[str, Any]) -> Dict[str, str]:
        env = os.environ.copy()
        password = details.get("password")
        if password:
            env["PGPASSWORD"] = str(password)
        return env

    async def _pip_freeze(self) -> List[str]:
        code, out, err = await self._run_command(sys.executable, "-m", "pip", "freeze")
        if code != 0:
            raise RuntimeError(err.strip() or "pip freeze failed")
        return [line for line in out.splitlines() if line.strip()]

    async def _pip_install(self, requirements_path: Path) -> Tuple[int, str, str]:
        return await self._run_command(
            sys.executable, "-m", "pip", "install", "-r", str(requirements_path)
        )

    @staticmethod
    def _parse_requirement_lines(data: bytes) -> List[str]:
        text = data.decode("utf-8", errors="replace")
        lines = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            lines.append(line)
        return lines

    async def _invoke_as_command(self, ctx: commands.Context, command_text: str) -> None:
        new_message = copy.copy(ctx.message)
        new_message.content = f"{ctx.prefix}{command_text}"
        new_ctx = await self.bot.get_context(new_message)
        if new_ctx.command is None:
            await ctx.send(f"Could not resolve a command for: `{command_text}`")
            return
        await self.bot.invoke(new_ctx)

    async def _install_dependencies(self, ctx: commands.Context, lines: List[str]) -> None:
        pip_command = self.bot.get_command("pipinstall")
        if pip_command is not None:
            await self._invoke_as_command(ctx, "pipinstall " + " ".join(lines))
            return
        await ctx.send(
            "Downloader's `pipinstall` command was not found, falling back to a "
            "direct pip install."
        )
        tmp_dir = Path(tempfile.mkdtemp())
        req_path = tmp_dir / "requirements.txt"
        req_path.write_text("\n".join(lines), encoding="utf-8")
        code, out, err = await self._pip_install(req_path)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        output = (out + "\n" + err).strip() or "No output."
        status = "completed successfully" if code == 0 else f"failed with exit code {code}"
        await ctx.send(f"pip install {status}.")
        for page in pagify(output, page_length=1900):
            await ctx.send(box(page))

    async def _restore_repos(
        self, ctx: commands.Context, downloader, repos: List[Dict[str, Any]]
    ) -> None:
        if not repos:
            await ctx.send("No repos found in the manifest.")
            return
        manager = getattr(downloader, "_repo_manager", None)
        existing_names = set()
        if manager is not None:
            existing_names = {getattr(r, "name", None) for r in getattr(manager, "repos", [])}
        to_add = [
            repo
            for repo in repos
            if repo.get("name") and repo.get("url") and repo.get("name") not in existing_names
        ]
        skipped = [repo.get("name") for repo in repos if repo.get("name") in existing_names]
        if skipped:
            await ctx.send(f"Already present, skipping: {humanize_list(skipped)}")
        if not to_add:
            await ctx.send("No new repos to add.")
            return
        for repo in to_add:
            name, url, branch = repo["name"], repo["url"], repo.get("branch")
            command_text = f"repo add {name} {url}"
            if branch:
                command_text += f" {branch}"
            await ctx.send(f"Adding repo `{name}`...")
            await self._invoke_as_command(ctx, command_text)

    async def _restore_cogs(
        self, ctx: commands.Context, downloader, cogs: List[Dict[str, Any]]
    ) -> None:
        if not cogs:
            await ctx.send("No cogs found in the manifest.")
            return
        try:
            currently_installed = {m.name for m in await downloader.installed_cogs()}
        except Exception:
            currently_installed = set()
        by_repo: Dict[str, List[str]] = {}
        for cog in cogs:
            name = cog.get("name")
            repo_name = cog.get("repo_name")
            if not name or not repo_name or name in currently_installed:
                continue
            by_repo.setdefault(repo_name, []).append(name)
        if not by_repo:
            await ctx.send("All listed cogs are already installed.")
            return
        for repo_name, cog_names in by_repo.items():
            command_text = f"cog install {repo_name} " + " ".join(cog_names)
            await ctx.send(f"Installing from `{repo_name}`: {humanize_list(cog_names)}")
            await self._invoke_as_command(ctx, command_text)
        await ctx.send("Use `[p]load <cog>` to load newly installed cogs.")

    @staticmethod
    async def _find_attachment(
        ctx: commands.Context, suffix: str
    ) -> Optional[discord.Attachment]:
        candidates = list(ctx.message.attachments)
        if ctx.message.reference and isinstance(ctx.message.reference.resolved, discord.Message):
            candidates.extend(ctx.message.reference.resolved.attachments)
        for attachment in candidates:
            if attachment.filename.lower().endswith(suffix):
                return attachment
        return candidates[0] if candidates else None

    async def _read_manifest_attachment(
        self, ctx: commands.Context
    ) -> Optional[Dict[str, Any]]:
        attachment = await self._find_attachment(ctx, ".json")
        if attachment is None:
            await ctx.send("Attach a chronicle manifest JSON file to this command.")
            return None
        try:
            return json.loads(await attachment.read())
        except json.JSONDecodeError:
            await ctx.send("That file is not valid JSON.")
            return None

    async def _confirm(self, ctx: commands.Context, message: str) -> bool:
        await ctx.send(f"{message} (yes/no)")
        pred = MessagePredicate.yes_or_no(ctx)
        try:
            await self.bot.wait_for("message", check=pred, timeout=60)
        except asyncio.TimeoutError:
            await ctx.send("Timed out waiting for a response.")
            return False
        return pred.result

    @staticmethod
    def _dir_size(path: Path) -> int:
        total = 0
        for root, _dirs, files in os.walk(path):
            for name in files:
                fp = Path(root) / name
                try:
                    total += fp.stat().st_size
                except OSError:
                    pass
        return total

    @staticmethod
    def _humanize_bytes(num: float) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if abs(num) < 1024:
                return f"{num:.1f}{unit}"
            num /= 1024
        return f"{num:.1f}PB"

    @staticmethod
    def _get_local_ip() -> str:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return "unknown"
        finally:
            s.close()

    async def _get_public_ip(self) -> str:
        try:
            async with self.bot.session.get("https://api.ipify.org") as resp:
                return (await resp.text()).strip()
        except Exception:
            return "unknown"

    @staticmethod
    def _scan_for_path(instance_path: Path, old_path_str: str) -> List[Path]:
        matches = []
        for root, dirs, files in os.walk(instance_path):
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__"}]
            for name in files:
                if Path(name).suffix.lower() not in SCAN_EXTENSIONS:
                    continue
                fp = Path(root) / name
                try:
                    content = fp.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if old_path_str in content:
                    matches.append(fp)
        return matches

    @staticmethod
    def _write_zip(
        zip_path: Path,
        targets: List[Path],
        instance_path: Path,
        exclude_patterns: List[str],
        manifest: Dict[str, Any],
        freeze_lines: List[str],
    ) -> None:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "chronicle_manifest.json", json.dumps(manifest, indent=2, default=str)
            )
            zf.writestr("chronicle_requirements.txt", "\n".join(freeze_lines) + "\n")
            for target in targets:
                for root, dirs, files in os.walk(target):
                    dirs[:] = [
                        d
                        for d in dirs
                        if not any(fnmatch.fnmatch(d, pat) for pat in exclude_patterns)
                    ]
                    for name in files:
                        if any(fnmatch.fnmatch(name, pat) for pat in exclude_patterns):
                            continue
                        full_path = Path(root) / name
                        if full_path == zip_path:
                            continue
                        arcname = Path("data") / full_path.relative_to(instance_path)
                        try:
                            zf.write(full_path, arcname=str(arcname))
                        except OSError:
                            pass
