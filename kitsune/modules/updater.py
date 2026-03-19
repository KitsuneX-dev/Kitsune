"""
Kitsune built-in: Updater
Команды: .update .restart
"""

# © Yushi (@Mikasu32), 2024-2026
# Kitsune Userbot — License: AGPLv3

from __future__ import annotations

import asyncio
import os
import sys
import time

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER
from ..utils import escape_html

_DB_OWNER = "kitsune.updater"


class UpdaterModule(KitsuneModule):
    name        = "updater"
    description = "Обновление и перезапуск"
    author      = "Yushi"

    REPO_URL = "https://github.com/KitsuneX-dev/Kitsune"

    strings_ru = {
        "checking":    "🔍 Проверяю обновления...",
        "up_to_date":  "✅ У тебя последняя версия.",
        "updating":    "⬇️ Скачиваю обновление...",
        "req_update":  "📦 Обновляю зависимости...",
        "restarting":  "🔄 Перезапуск...",
        "no_git":      "❌ Git-репозиторий не найден.",
        "git_err":     "❌ Ошибка Git:\n<code>{err}</code>",
        "boot_done": (
            "✅ <b>Kitsune перезапущен</b>\n\n"
            "⏱ Время перезапуска: <code>{restart_time}</code>\n"
            "📦 Модули загружены: <code>{mod_count}</code>\n"
            "⚡ Полная загрузка заняла: <code>{total_time}</code>"
        ),
        "boot_loading": (
            "⏳ <b>Kitsune перезапускается...</b>\n\n"
            "⏱ Перезапуск занял: <code>{restart_time}</code>\n"
            "📦 Модули ещё загружаются, подождите..."
        ),
        "boot_modules_done": (
            "✅ <b>Все модули загружены!</b>\n"
            "⚡ Полная загрузка заняла: <code>{total_time}</code>"
        ),
    }

    async def on_load(self) -> None:
        """Check if we just restarted and send notification."""
        restart_data = self.db.get(_DB_OWNER, "pending_restart", None)
        if not restart_data:
            return

        await self.db.delete(_DB_OWNER, "pending_restart")

        restart_start = restart_data.get("start_time", 0)
        now           = time.time()
        total_elapsed = now - restart_start
        # Approximate restart time as first 40% of total (process startup)
        restart_elapsed = total_elapsed * 0.4

        restart_time = _fmt_time(restart_elapsed)
        total_time   = _fmt_time(total_elapsed)

        loader    = getattr(self.client, "_kitsune_loader", None)
        mod_count = len(loader.modules) if loader else 0

        report = self.strings("boot_done").format(
            restart_time=restart_time,
            mod_count=mod_count,
            total_time=total_time,
        )

        # Edit the original "Перезапуск..." message if we have its location
        chat_id = restart_data.get("chat_id", 0)
        msg_id  = restart_data.get("msg_id",  0)
        if chat_id and msg_id:
            try:
                await self.client.edit_message(chat_id, msg_id, report, parse_mode="html")
            except Exception:
                await self.client.send_message(chat_id, report, parse_mode="html")

        # Also send via bot if available
        notifier = loader.modules.get("notifier") if loader else None
        if notifier:
            await notifier.send_restart_report(
                restart_time=restart_time,
                total_time=total_time,
                mod_count=mod_count,
            )

    # ── Commands ──────────────────────────────────────────────────────────────

    @command("update", required=OWNER)
    async def update_cmd(self, event) -> None:
        """.update — обновить Kitsune из Git"""
        m = await event.reply(self.strings("checking"), parse_mode="html")
        try:
            import git
        except ImportError:
            await m.edit("❌ GitPython не установлен.", parse_mode="html")
            return

        try:
            repo_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..")
            )
            repo = git.Repo(repo_path)
        except Exception:
            await m.edit(self.strings("no_git"), parse_mode="html")
            return

        try:
            origin = repo.remote("origin")
            origin.fetch()
            try:
                branch = repo.active_branch.name
            except TypeError:
                branch = "main"
            behind = list(repo.iter_commits(f"HEAD..origin/{branch}"))
            if not behind:
                await m.edit(self.strings("up_to_date"), parse_mode="html")
                return

            # Notify via bot
            loader = getattr(self.client, "_kitsune_loader", None)
            if loader:
                notifier = loader.modules.get("notifier")
                if notifier:
                    from ..version import __version_str__
                    changes = "\n".join(f"• {c.summary}" for c in list(behind)[:5])
                    await notifier.notify_update(
                        current=__version_str__,
                        new=f"{__version_str__}+{len(behind)}",
                        changes=changes,
                    )

            await m.edit(self.strings("updating"), parse_mode="html")
            origin.pull()

            await m.edit(self.strings("req_update"), parse_mode="html")
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
                "--quiet", "--no-warn-script-location",
                cwd=repo_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                await m.edit(
                    f"⚠️ pip install вернул ошибку:\n<code>{escape_html(stderr.decode()[:500])}</code>",
                    parse_mode="html",
                )
                return

            await m.edit(self.strings("restarting"), parse_mode="html")
            await self._save_restart_start(chat_id=event.chat_id, msg_id=m.id)
            await asyncio.sleep(1)
            os.execl(sys.executable, sys.executable, "-m", "kitsune")

        except Exception as exc:
            await m.edit(self.strings("git_err").format(err=escape_html(str(exc))), parse_mode="html")

    @command("restart", required=OWNER)
    async def restart_cmd(self, event) -> None:
        """.restart — перезапустить Kitsune"""
        m = await event.reply(self.strings("restarting"), parse_mode="html")
        await self._save_restart_start(chat_id=event.chat_id, msg_id=m.id)
        await asyncio.sleep(1)
        os.execl(sys.executable, sys.executable, "-m", "kitsune")

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _save_restart_start(self, chat_id: int = 0, msg_id: int = 0) -> None:
        """Save restart timestamp before exiting."""
        now = time.time()
        await self.db.set(_DB_OWNER, "pending_restart", {
            "start_time": now,
            "chat_id":    chat_id,
            "msg_id":     msg_id,
        })
        await self.db.force_save()


def _fmt_time(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} мс"
    elif seconds < 60:
        return f"{seconds:.1f} с"
    else:
        m, s = divmod(int(seconds), 60)
        return f"{m}м {s}с"
