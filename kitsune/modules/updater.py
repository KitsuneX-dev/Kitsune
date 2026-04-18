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
        "checking":   "🔍 Проверяю обновления...",
        "up_to_date": "✅ У тебя последняя версия.",
        "notify_sent": (
            "🆕 <b>Обнаружена новая версия!</b>\n\n"
            "Текущая: <code>{current}</code>\n"
            "Новая: <code>{new}</code>\n"
            "Коммитов впереди: <code>{count}</code>\n\n"
            "📬 Уведомление с кнопкой отправлено в <b>{group}</b>"
        ),
        "no_notifier": (
            "🆕 <b>Обнаружена новая версия!</b>\n\n"
            "Текущая: <code>{current}</code>\n"
            "Коммитов впереди: <code>{count}</code>\n\n"
            "<b>Изменения:</b>\n{changes}\n\n"
            "Напиши <code>.update confirm</code> для обновления."
        ),
        "confirm_direct": (
            "🔄 Обновляю до версии <code>{new}</code>...\n\n"
            "<b>Изменения:</b>\n{changes}"
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

        restart_start  = restart_data.get("start_time", 0)
        now            = time.time()
        total_elapsed  = now - restart_start
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

                                                                        
                     
                                                                        

    @command("update", required=OWNER)
    async def update_cmd(self, event) -> None:
        args = self.get_args(event).strip().lower()

                                                                   
        if args == "confirm":
            pending = self.db.get(_DB_OWNER, "pending_update", None)
            if not pending:
                await event.reply("❌ Нет ожидающего обновления. Сначала запусти <code>.update</code>", parse_mode="html")
                return
            await self.db.delete(_DB_OWNER, "pending_update")
            m = await event.reply("⬇️ <b>Обновляю...</b>", parse_mode="html")
            await self._do_update(repo_path=pending["repo_path"], chat_id=event.chat_id, msg_id=m.id)
            return

        m = await event.reply(self.strings("checking"), parse_mode="html")
        try:
            import git
        except ImportError:
            await m.edit("❌ GitPython не установлен.\n<code>pip install gitpython</code>", parse_mode="html")
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
            if len(behind) > 5:
                changes += f"\n<i>...и ещё {len(behind) - 5} коммитов</i>"

                                                      
            try:
                remote_version = repo.git.show(f"origin/{branch}:kitsune/version.py")
                import re as _re
                vm = _re.search(r"__version__\s*=\s*\((\d+),\s*(\d+),\s*(\d+)\)", remote_version)
                new_ver = f"{vm.group(1)}.{vm.group(2)}.{vm.group(3)}" if vm else f"{__version_str__}+{len(behind)}"
            except Exception:
                new_ver = f"{__version_str__}+{len(behind)}"

                                                                                  
            await self.db.set(_DB_OWNER, "pending_update", {
                "repo_path": repo_path,
                "chat_id":   event.chat_id,
                "msg_id":    m.id,
            })

                                                 
            await self.db.set(_DB_OWNER, "pending_update", {
                "repo_path": repo_path,
                "chat_id":   event.chat_id,
                "msg_id":    m.id,
            })

                                                         
            inline = getattr(self.client, "_kitsune_inline", None)
            shown_inline = False
            if inline:
                try:
                    preview_text = (
                        f"🆕 <b>Обнаружена новая версия!</b>\n\n"
                        f"Текущая: <code>{__version_str__}</code> → <code>{new_ver}</code>\n"
                        f"Коммитов: <code>{len(behind)}</code>\n\n"
                        f"<b>Изменения:</b>\n{changes}"
                    )
                    markup = [
                        [
                            {"text": "⬆️ Обновить",  "callback": self._cb_do_update,     "args": (repo_path,)},
                            {"text": "❌ Отмена",     "callback": self._cb_cancel_update},
                        ]
                    ]
                    await inline.form(preview_text, m, markup)
                    shown_inline = True
                except Exception:
                    shown_inline = False

            if not shown_inline:
                                                            
                notifier = self._get_notifier()
                sent_to = None
                if notifier and notifier._runner and notifier._runner.bot:
                    sent_to = await notifier._updater.notify_update(
                        current=__version_str__,
                        new=new_ver,
                        changes=changes,
                    )
                if sent_to:
                    await m.edit(
                        f"🆕 <b>Обнаружена новая версия!</b>\n\n"
                        f"Текущая: <code>{__version_str__}</code>\n"
                        f"Новая: <code>{new_ver}</code>\n"
                        f"Коммитов впереди: <code>{len(behind)}</code>\n\n"
                        f"📬 Уведомление с кнопкой отправлено в бота",
                        parse_mode="html",
                    )
                else:
                    await m.edit(
                        self.strings("no_notifier").format(
                            current=__version_str__,
                            count=len(behind),
                            changes=changes,
                        ),
                        parse_mode="html",
                    )

                                    
            asyncio.ensure_future(self._update_timeout(event.chat_id, m.id))

        except Exception as exc:
            await m.edit(self.strings("git_err").format(err=escape_html(str(exc))), parse_mode="html")

    async def _cb_do_update(self, call, repo_path: str) -> None:
        """Колбэк кнопки «Обновить» в inline-форме."""
        inline = getattr(self.client, "_kitsune_inline", None)
        pending = self.db.get(_DB_OWNER, "pending_update", None)
        if not pending:
            if inline:
                try:
                    await inline.edit(call, "❌ Нет ожидающего обновления. Запусти <code>.update</code> снова.", [])
                except Exception:
                    pass
            return
        await self.db.delete(_DB_OWNER, "pending_update")

                                                                             
                                                                        
        notifier = self._get_notifier()
        if notifier and notifier._updater:
            asyncio.ensure_future(notifier._updater.do_update(msg=call.message))
        else:
                                                
            chat_id = pending.get("chat_id", 0)
            msg_id  = pending.get("msg_id", 0)
            await self._do_update(repo_path=repo_path, chat_id=chat_id, msg_id=msg_id)

    async def _cb_cancel_update(self, call) -> None:
        """Колбэк кнопки «Отмена»."""
        await self.db.delete(_DB_OWNER, "pending_update")
        inline = getattr(self.client, "_kitsune_inline", None)
        if inline:
            try:
                await inline.edit(call, self.strings("cancelled"), [])
            except Exception:
                pass

    def _get_notifier(self):
        loader = getattr(self.client, "_kitsune_loader", None)
        return loader.modules.get("notifier") if loader else None

    async def _update_timeout(self, chat_id: int, msg_id: int) -> None:
        await asyncio.sleep(_TTL)
        pending = self.db.get(_DB_OWNER, "pending_update", None)
        if pending and pending.get("msg_id") == msg_id:
            await self.db.delete(_DB_OWNER, "pending_update")

    async def _do_update(self, repo_path: str, chat_id: int, msg_id: int) -> None:
        import shutil
        import tempfile

        async def edit(text: str) -> None:
            try:
                await self.client.edit_message(chat_id, msg_id, text, parse_mode="html", buttons=None)
            except Exception:
                pass

        await edit("⬇️ <b>Скачиваю обновление...</b>\n████░░░░░░░░  33%")
        try:
            import git
            repo = git.Repo(repo_path)
            try:
                branch = repo.active_branch.name
            except TypeError:
                branch = "main"

            config_path   = os.path.join(repo_path, "config.toml")
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

        await edit("📦 <b>Обновляю зависимости...</b>\n████████░░░░  67%")

        is_termux = "com.termux" in os.environ.get("PREFIX", "") or os.path.isdir("/data/data/com.termux")
        req_file  = os.path.join(repo_path, "requirements-termux.txt" if is_termux else "requirements.txt")
        if not os.path.exists(req_file):
            req_file = os.path.join(repo_path, "requirements.txt")

        pip_errors = []
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
                sys.executable, "-m", "pip", "install", "-r", req_file,
                "--quiet", "--no-warn-script-location",
                cwd=repo_path,
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

        await edit("🔄 <b>Перезапускаю...</b>\n████████████  100%")
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
