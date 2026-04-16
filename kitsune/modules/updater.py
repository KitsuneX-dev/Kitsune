from __future__ import annotations

import asyncio
import os
import sys
import time

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER
from ..utils import escape_html

_DB_OWNER = "kitsune.updater"
_TTL = 120  

class UpdaterModule(KitsuneModule):
    name        = "updater"
    description = "Обновление и перезапуск"
    author      = "Yushi"

    REPO_URL = "https://github.com/KitsuneX-dev/Kitsune"

    strings_ru = {
        "checking":    "🔍 Проверяю обновления...",
        "up_to_date":  "✅ У тебя последняя версия.",
        "confirm": (
            "🆕 <b>Обнаружена новая версия!</b>\n\n"
            "Текущая: <code>{current}</code>\n"
            "Коммитов впереди: <code>{count}</code>\n\n"
            "<b>Изменения:</b>\n{changes}\n\n"
            "Хотите обновиться?"
        ),
        "cancelled":  "❌ Обновление отменено.",
        "no_git":     "❌ Git-репозиторий не найден.",
        "git_err":    "❌ Ошибка Git:\n<code>{err}</code>",
        "timeout":    "⏱ Время вышло. Запусти <code>.update</code> снова.",
        "boot_done": (
            "✅ <b>Kitsune перезапущен</b>\n\n"
            "⏱ Время перезапуска: <code>{restart_time}</code>\n"
            "📦 Модули загружены: <code>{mod_count}</code>\n"
            "⚡ Полная загрузка заняла: <code>{total_time}</code>"
        ),
    }

    async def on_load(self) -> None:
        restart_data = self.db.get(_DB_OWNER, "pending_restart", None)
        if not restart_data:
            return

        await self.db.delete(_DB_OWNER, "pending_restart")

        restart_start = restart_data.get("start_time", 0)
        now = time.time()
        total_elapsed = now - restart_start
        restart_elapsed = total_elapsed * 0.4

        restart_time = _fmt_time(restart_elapsed)
        total_time   = _fmt_time(total_elapsed)

        loader    = getattr(self.client, "_kitsune_loader", None)
        mod_count = len(loader.modules) if loader else 0

        from telethon import events as _events
        self.client.add_event_handler(self._on_callback, _events.CallbackQuery)

        report = self.strings("boot_done").format(
            restart_time=restart_time,
            mod_count=mod_count,
            total_time=total_time,
        )

        chat_id = restart_data.get("chat_id", 0)
        msg_id  = restart_data.get("msg_id", 0)
        if chat_id and msg_id:
            try:
                await self.client.edit_message(chat_id, msg_id, report, parse_mode="html")
            except Exception:
                await self.client.send_message(chat_id, report, parse_mode="html")

        notifier = loader.modules.get("notifier") if loader else None
        if notifier:
            await notifier.send_restart_report(
                restart_time=restart_time,
                total_time=total_time,
                mod_count=mod_count,
            )

    async def _on_callback(self, event) -> None:
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
                    buttons=None,
                )
            except Exception:
                pass

    @command("update", required=OWNER)
    async def update_cmd(self, event) -> None:
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

            last_err = self.db.get(_DB_OWNER, "last_update_error", None)
            if last_err:
                await self.db.delete(_DB_OWNER, "last_update_error")
                await m.edit(
                    f"⚠️ <b>Последнее обновление завершилось с ошибками:</b>\n"
                    f"<code>{escape_html(last_err)}</code>\n\n"
                    f"Код обновлён, но зависимости могут быть неполными.",
                    parse_mode="html",
                )
                return

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

            await self.db.set(_DB_OWNER, "pending_update", {
                "repo_path": repo_path,
                "chat_id":   event.chat_id,
                "msg_id":    m.id,
            })

            from telethon import events as _events
            self.client.add_event_handler(self._on_callback, _events.CallbackQuery)

            from telethon.tl.types import KeyboardButtonCallback
            from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonRow

            markup = ReplyInlineMarkup(rows=[
                KeyboardButtonRow(buttons=[
                    KeyboardButtonCallback(text="✅ Установить", data=b"update_yes"),
                    KeyboardButtonCallback(text="❌ Отмена",    data=b"update_no"),
                ])
            ])

            await m.edit(confirm_text, parse_mode="html", buttons=markup)
            asyncio.ensure_future(self._update_timeout(event.chat_id, m.id))

        except Exception as exc:
            await m.edit(self.strings("git_err").format(err=escape_html(str(exc))), parse_mode="html")

    async def _update_timeout(self, chat_id: int, msg_id: int) -> None:
        await asyncio.sleep(_TTL)
        pending = self.db.get(_DB_OWNER, "pending_update", None)
        if pending and pending.get("msg_id") == msg_id:
            await self.db.delete(_DB_OWNER, "pending_update")
            try:
                await self.client.edit_message(
                    chat_id, msg_id,
                    self.strings("timeout"), parse_mode="html", buttons=None,
                )
            except Exception:
                pass

    async def _do_update(self, repo_path: str, chat_id: int, msg_id: int) -> None:
        import shutil
        import tempfile

        async def edit(text: str) -> None:
            try:
                await self.client.edit_message(chat_id, msg_id, text, parse_mode="html", buttons=None)
            except Exception:
                pass

        bar1 = "████░░░░░░░░  33%"
        await edit(f"⬇️ <b>Скачиваю обновление...</b>\n{bar1}")
        try:
            import git
            repo = git.Repo(repo_path)
            try:
                branch = repo.active_branch.name
            except TypeError:
                branch = "main"

            config_path = os.path.join(repo_path, "config.toml")
            config_backup = None
            if os.path.exists(config_path):
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".toml")
                shutil.copy2(config_path, tmp.name)
                config_backup = tmp.name
                tmp.close()

            origin = repo.remote("origin")
            origin.fetch()

            try:
                repo.git.rm("--cached", "config.toml", "--ignore-unmatch")
            except Exception:
                pass

            repo.git.reset("--hard", f"origin/{branch}")

            if config_backup and os.path.exists(config_backup):
                shutil.copy2(config_backup, config_path)
                os.unlink(config_backup)

        except Exception as exc:
            await edit(self.strings("git_err").format(err=escape_html(str(exc))))
            return

        bar2 = "████████░░░░  67%"
        await edit(f"📦 <b>Обновляю зависимости...</b>\n{bar2}")

        is_termux = "com.termux" in os.environ.get("PREFIX", "") or os.path.isdir("/data/data/com.termux")
        req_file  = os.path.join(repo_path, "requirements-termux.txt" if is_termux else "requirements.txt")
        if not os.path.exists(req_file):
            req_file = os.path.join(repo_path, "requirements.txt")

        pip_errors = []
        pip_args = [sys.executable, "-m", "pip", "install", "-r", req_file,
                    "--quiet", "--no-warn-script-location"]
        if is_termux:
            pip_args += ["--prefer-binary", "--no-build-isolation"]

        if is_termux:
            try:
                with open(req_file, encoding="utf-8") as f:
                    pkgs = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
                for pkg in pkgs:
                    p = await asyncio.create_subprocess_exec(
                        sys.executable, "-m", "pip", "install", pkg,
                        "--quiet", "--no-warn-script-location",
                        "--prefer-binary", "--no-build-isolation",
                        cwd=repo_path,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, err = await p.communicate()
                    if p.returncode != 0:
                        err_txt = err.decode(errors="replace").strip()
                        if "platform android is not supported" not in err_txt.lower():
                            pip_errors.append(f"{pkg}: {err_txt[:120]}")
            except Exception as exc:
                pip_errors.append(str(exc))
        else:
            proc = await asyncio.create_subprocess_exec(
                *pip_args, cwd=repo_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                pip_errors.append(stderr.decode(errors="replace")[:500])

        if pip_errors:
            err_text = "\n".join(pip_errors[:3])
            await edit(
                f"⚠️ <b>Часть зависимостей не установилась:</b>\n"
                f"<code>{escape_html(err_text)}</code>\n\nПродолжаю перезапуск..."
            )
            await asyncio.sleep(3)
            err_summary = "; ".join(pip_errors[:2])
            await self.db.set(_DB_OWNER, "last_update_error", err_summary[:300])
            await self.db.force_save()

        bar3 = "████████████  100%"
        await edit(f"🔄 <b>Перезапускаю...</b>\n{bar3}")
        await self._save_restart_start(chat_id=chat_id, msg_id=msg_id)
        await asyncio.sleep(1)
        os.execl(sys.executable, sys.executable, "-m", "kitsune")

    @command("restart", required=OWNER)
    async def restart_cmd(self, event) -> None:
        m = await event.reply("🔄 Перезапускаю...", parse_mode="html")
        await self._save_restart_start(chat_id=event.chat_id, msg_id=m.id)
        await asyncio.sleep(1)
        os.execl(sys.executable, sys.executable, "-m", "kitsune")

    async def _save_restart_start(self, chat_id: int = 0, msg_id: int = 0) -> None:
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
