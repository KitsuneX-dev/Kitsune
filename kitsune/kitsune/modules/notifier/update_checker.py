"""Проверка обновлений и выполнение git-обновления."""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import tempfile
import time

logger = logging.getLogger(__name__)

_DB_KEY = "kitsune.notifier"


class UpdateChecker:
    """Периодическая проверка обновлений + выполнение git pull."""

    def __init__(self, client, db) -> None:
        self._client = client
        self._db = db
        self._check_task: asyncio.Task | None = None
        self._repo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
        )

    def start(self) -> None:
        self._check_task = asyncio.ensure_future(self._loop())

    def stop(self) -> None:
        if self._check_task and not self._check_task.done():
            self._check_task.cancel()

    # ── Update loop ───────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        await asyncio.sleep(300)
        while True:
            try:
                await self._check()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("UpdateChecker: check failed")
            await asyncio.sleep(600)

    async def _check(self) -> None:
        try:
            import git
            repo = git.Repo(self._repo_path)
            try:
                branch = repo.active_branch.name
            except TypeError:
                branch = "main"
        except Exception as exc:
            logger.debug("UpdateChecker: git repo unavailable — %s", exc)
            return

        try:
            for remote in repo.remotes:
                remote.fetch()
        except Exception as exc:
            logger.debug("UpdateChecker: fetch failed — %s", exc)
            return

        try:
            diff = repo.git.log([f"HEAD..origin/{branch}", "--oneline"])
        except Exception as exc:
            logger.debug("UpdateChecker: git log failed — %s", exc)
            return

        if not diff:
            return

        try:
            remote_sha = next(repo.iter_commits(f"origin/{branch}", max_count=1)).hexsha
        except Exception:
            return

        if remote_sha == self._db.get(_DB_KEY, "last_notified_commit", None):
            return

        await self._db.set(_DB_KEY, "last_notified_commit", remote_sha)

        log_lines = diff.splitlines()[:10]
        count = len(diff.splitlines())
        changes = "\n".join(
            f"• <b>{line.split()[0]}</b>: {' '.join(line.split()[1:])}"
            for line in log_lines if line.strip()
        ) or "—"
        if count > 10:
            changes += f"\n<i>...и ещё {count - 10} коммитов</i>"

        from kitsune.version import __version_str__
        try:
            remote_version = repo.git.show(f"origin/{branch}:kitsune/version.py")
            import re
            m = re.search(r"__version__\s*=\s*\((\d+),\s*(\d+),\s*(\d+)\)", remote_version)
            new_ver = f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else f"{__version_str__}+{count}"
        except Exception:
            new_ver = f"{__version_str__}+{count}"

        await self.notify_update(current=__version_str__, new=new_ver, changes=changes)

    # ── Notify ────────────────────────────────────────────────────────────────

    async def notify_update(self, current: str, new: str, changes: str = "") -> None:
        token = self._db.get(_DB_KEY, "bot_token", None)
        owner_id = self._db.get(_DB_KEY, "owner_id", None)
        if not token or not owner_id:
            return
        try:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            from kitsune.modules.notifier.bot_runner import _make_bot
            bot = _make_bot(str(token))
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⬆️ Обновить / Update", callback_data="do_update"),
            ]])
            await bot.send_message(
                chat_id=int(owner_id),
                text=(
                    "🦊 <b>Kitsune Userbot</b>\n\n"
                    "🆕 <b>Доступно обновление!</b>\n"
                    f"📌 Версия: <code>{current}</code> → <code>{new}</code>\n\n"
                    f"📋 <b>Изменения:</b>\n{changes}"
                ),
                reply_markup=kb,
            )
            await bot.session.close()
        except Exception:
            logger.exception("UpdateChecker: failed to send update notification")

    # ── do_update ─────────────────────────────────────────────────────────────

    async def do_update(self, msg=None) -> None:
        async def edit(text: str) -> None:
            if msg:
                try:
                    await msg.edit_text(text, parse_mode="HTML")
                except Exception:
                    pass

        # Git pull
        try:
            import git
            repo = git.Repo(self._repo_path)
            origin = repo.remote("origin")
            for attempt in range(3):
                try:
                    origin.fetch()
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(10)
            try:
                branch = repo.active_branch.name
            except TypeError:
                branch = "main"

            # Сохраняем config.toml
            config_path = os.path.join(self._repo_path, "config.toml")
            config_backup = None
            if os.path.exists(config_path):
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".toml")
                shutil.copy2(config_path, tmp.name)
                config_backup = tmp.name
                tmp.close()

            repo.git.reset("--hard", f"origin/{branch}")

            if config_backup and os.path.exists(config_backup):
                shutil.copy2(config_backup, config_path)
                os.unlink(config_backup)

        except Exception as exc:
            raise RuntimeError(f"Git update failed: {exc}") from exc

        await edit("📦 <b>Устанавливаю обновление...</b>\nInstalling update...")

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
            "--quiet", cwd=self._repo_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode()[:300])

        await edit("🔄 <b>Перезапускаю бота...</b>\nRestarting bot...")

        loader = getattr(self._client, "_kitsune_loader", None)
        restart_start = time.time()
        await self._db.set(_DB_KEY, "update_msg_chat", msg.chat.id if msg else 0)
        await self._db.set(_DB_KEY, "update_msg_id", msg.message_id if msg else 0)
        await self._db.set(_DB_KEY, "update_start_time", restart_start)
        await self._db.force_save()

        await asyncio.sleep(1)
        os.execl(sys.executable, sys.executable, "-m", "kitsune")

    async def notify_update_done(self) -> None:
        chat_id = self._db.get(_DB_KEY, "update_msg_chat", None)
        msg_id = self._db.get(_DB_KEY, "update_msg_id", None)
        start_time = self._db.get(_DB_KEY, "update_start_time", None)
        if not chat_id or not msg_id or not start_time:
            return

        await self._db.delete(_DB_KEY, "update_msg_chat")
        await self._db.delete(_DB_KEY, "update_msg_id")
        await self._db.delete(_DB_KEY, "update_start_time")

        await asyncio.sleep(3)
        elapsed = time.time() - float(start_time)
        if elapsed < 1:
            restart_time = f"{elapsed * 1000:.0f} мс"
        elif elapsed < 60:
            restart_time = f"{elapsed:.1f} с"
        else:
            m, s = divmod(int(elapsed), 60)
            restart_time = f"{m}м {s}с"

        loader = getattr(self._client, "_kitsune_loader", None)
        mod_count = len(loader.modules) if loader else 0

        token = self._db.get(_DB_KEY, "bot_token", None)
        owner_id = self._db.get(_DB_KEY, "owner_id", None)
        if not token or not owner_id:
            return

        try:
            from kitsune.modules.notifier.bot_runner import _make_bot
            bot = _make_bot(str(token))
            await bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=int(msg_id),
                text=(
                    "✅ <b>Обновление успешно установлено!</b>\n"
                    f"⏱ Время перезапуска: <code>{restart_time}</code>\n"
                    f"📦 Модули загружены: <code>{mod_count}</code>"
                ),
                parse_mode="HTML",
            )
            await bot.session.close()
        except Exception:
            logger.exception("UpdateChecker: failed to send update_done message")

    async def send_restart_report(self, restart_time: str, total_time: str, mod_count: int) -> None:
        token = self._db.get(_DB_KEY, "bot_token", None)
        owner_id = self._db.get(_DB_KEY, "owner_id", None)
        if not token or not owner_id:
            return
        try:
            from kitsune.modules.notifier.bot_runner import _make_bot
            bot = _make_bot(str(token))
            await bot.send_message(
                chat_id=int(owner_id),
                text=(
                    "✅ <b>Kitsune перезапущен</b>\n\n"
                    f"⏱ Перезапуск: <code>{restart_time}</code>\n"
                    f"📦 Модули: <code>{mod_count}</code>\n"
                    f"⚡ Полная загрузка: <code>{total_time}</code>"
                ),
            )
            await bot.session.close()
        except Exception:
            logger.exception("UpdateChecker: failed to send restart report")
