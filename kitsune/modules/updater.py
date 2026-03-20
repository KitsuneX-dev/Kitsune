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
from ..utils import escape_html, auto_delete, ProgressMessage

_DB_OWNER = "kitsune.updater"


class UpdaterModule(KitsuneModule):
    name        = "updater"
    description = "Обновление и перезапуск"
    author      = "Yushi"

    REPO_URL = "https://github.com/KitsuneX-dev/Kitsune"

    strings_ru = {
        "checking":    "🔍 Проверяю обновления...",
        "up_to_date":  "✅ У тебя последняя версия.",
        "confirm":     (
            "🆕 <b>Обнаружена новая версия!</b>\n\n"
            "Текущая: <code>{current}</code>\n"
            "Коммитов впереди: <code>{count}</code>\n\n"
            "<b>Изменения:</b>\n{changes}\n\n"
            "Хотите обновиться?"
        ),
        "cancelled":   "❌ Обновление отменено.",
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

        # Register callback handler for update confirmation buttons
        from telethon import events as _events
        self.client.add_event_handler(self._on_callback, _events.CallbackQuery)

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

    async def _on_callback(self, event) -> None:
        """Handle inline button callbacks for update confirmation."""
        data = event.data
        if data == b"update_yes":
            await event.answer()
            pending = self.db.get(_DB_OWNER, "pending_update", None)
            if not pending:
                return
            await self.db.delete(_DB_OWNER, "pending_update")
            asyncio.ensure_future(self._do_update(
                repo_path=pending["repo_path"],
                chat_id=pending["chat_id"],
                msg_id=pending["msg_id"],
            ))
        elif data == b"update_no":
            await event.answer("Отменено")
            await self.db.delete(_DB_OWNER, "pending_update")
            try:
                await self.client.edit_message(
                    event.chat_id, event.message_id,
                    self.strings("cancelled"), parse_mode="html",
                )
            except Exception:
                pass

    # ── Commands ──────────────────────────────────────────────────────────────

    @command("update", required=OWNER)
    async def update_cmd(self, event) -> None:
        """.update — проверить и установить обновление"""
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

            from ..version import __version_str__
            changes = "\n".join(f"• {escape_html(c.summary)}" for c in behind[:5])

            confirm_text = self.strings("confirm").format(
                current=__version_str__,
                count=len(behind),
                changes=changes,
            )

            # Store pending update info in db
            await self.db.set(_DB_OWNER, "pending_update", {
                "repo_path": repo_path,
                "chat_id":   event.chat_id,
                "msg_id":    m.id,
            })

            # Userbot accounts CANNOT send inline buttons — send via bot instead
            loader = getattr(self.client, "_kitsune_loader", None)
            notifier = loader.modules.get("notifier") if loader else None
            bot_sent = False
            if notifier and getattr(notifier, "_bot", None):
                try:
                    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                    kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="✅ Обновить", callback_data="update_yes"),
                        InlineKeyboardButton(text="❌ Отмена",   callback_data="update_no"),
                    ]])
                    owner_id = notifier.db.get("kitsune.notifier", "owner_id", None)
                    if owner_id:
                        await notifier._bot.send_message(
                            chat_id=int(owner_id),
                            text=confirm_text,
                            reply_markup=kb,
                            parse_mode="HTML",
                        )
                        bot_sent = True
                except Exception:
                    pass

            if bot_sent:
                await m.edit(
                    confirm_text + "\n\n<i>👆 Ответь кнопками в боте</i>",
                    parse_mode="html",
                )
            else:
                # Fallback: no bot — ask user to reply with yes/no
                await m.edit(
                    confirm_text + "\n\n<i>Ответь <code>да</code> или <code>нет</code> на это сообщение</i>",
                    parse_mode="html",
                )

        except Exception as exc:
            await m.edit(self.strings("git_err").format(err=escape_html(str(exc))), parse_mode="html")

    async def _do_update(self, repo_path: str, chat_id: int, msg_id: int) -> None:
        """Actually perform the update after confirmation."""
        import shutil
        import tempfile

        async def edit(text: str) -> None:
            try:
                await self.client.edit_message(chat_id, msg_id, text, parse_mode="html")
            except Exception:
                pass

        # Шаг 1 — git fetch + reset, config.toml защищаем
        bar1 = "████░░░░░░░░  33%"
        await edit(f"⬇️ <b>Скачиваю обновление...</b>\n{bar1}")
        try:
            import git
            repo = git.Repo(repo_path)
            try:
                branch = repo.active_branch.name
            except TypeError:
                branch = "main"

            # Сохраняем config.toml во временный файл перед reset
            config_path = os.path.join(repo_path, "config.toml")
            config_backup = None
            if os.path.exists(config_path):
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".toml")
                shutil.copy2(config_path, tmp.name)
                config_backup = tmp.name
                tmp.close()

            origin = repo.remote("origin")
            origin.fetch()

            # Убираем config.toml из индекса если он там есть (чтоб reset не трогал)
            try:
                repo.git.rm("--cached", "config.toml", "--ignore-unmatch")
            except Exception:
                pass

            repo.git.reset("--hard", f"origin/{branch}")

            # Восстанавливаем config.toml
            if config_backup and os.path.exists(config_backup):
                shutil.copy2(config_backup, config_path)
                os.unlink(config_backup)

        except Exception as exc:
            await edit(self.strings("git_err").format(err=escape_html(str(exc))))
            return

        # Шаг 2 — pip install
        bar2 = "████████░░░░  67%"
        await edit(f"📦 <b>Обновляю зависимости...</b>\n{bar2}")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
            "--quiet", "--no-warn-script-location",
            cwd=repo_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            await edit(f"⚠️ pip install вернул ошибку:\n<code>{escape_html(stderr.decode()[:500])}</code>")
            return

        # Шаг 3 — перезапуск
        bar3 = "████████████  100%"
        await edit(f"🔄 <b>Перезапускаю...</b>\n{bar3}")
        await self._save_restart_start(chat_id=chat_id, msg_id=msg_id)
        await asyncio.sleep(1)
        os.execl(sys.executable, sys.executable, "-m", "kitsune")

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
