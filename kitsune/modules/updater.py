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

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER
from ..utils import escape_html


class UpdaterModule(KitsuneModule):
    name        = "updater"
    description = "Обновление и перезапуск"
    author      = "Yushi"

    REPO_URL = "https://github.com/KitsuneX-dev/Kitsune"   # поменяй на свой репо

    strings_ru = {
        "checking":    "🔍 Проверяю обновления...",
        "up_to_date":  "✅ У тебя последняя версия.",
        "updating":    "⬇️ Скачиваю обновление...",
        "req_update":  "📦 Обновляю зависимости...",
        "restarting":  "🔄 Перезапуск...",
        "no_git":      "❌ Git-репозиторий не найден.",
        "git_err":     "❌ Ошибка Git:\n<code>{err}</code>",
    }

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

            # Notify via bot if notifier module is loaded
            loader = getattr(self.client, "_kitsune_loader", None)
            if loader:
                notifier = loader.modules.get("notifier")
                if notifier:
                    from ..version import __version_str__
                    changes = "\n".join(
                        f"• {c.summary}" for c in list(behind)[:5]
                    )
                    await notifier.notify_update(
                        current=__version_str__,
                        new=f"{__version_str__}+{len(behind)}",
                        changes=changes,
                    )

            await m.edit(self.strings("updating"), parse_mode="html")
            origin.pull()

            # Update requirements
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
            await asyncio.sleep(1)
            os.execl(sys.executable, sys.executable, "-m", "kitsune")

        except Exception as exc:
            await m.edit(self.strings("git_err").format(err=escape_html(str(exc))), parse_mode="html")

    @command("restart", required=OWNER)
    async def restart_cmd(self, event) -> None:
        """.restart — перезапустить Kitsune"""
        await event.reply(self.strings("restarting"), parse_mode="html")
        await asyncio.sleep(1)
        os.execl(sys.executable, sys.executable, "-m", "kitsune")
