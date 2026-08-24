from __future__ import annotations
import asyncio
import contextlib
import logging
import os
import sys
import time
import typing
from .._internal import graceful_restart
from ..core.loader import KitsuneModule, command
from ..core.security import OWNER
from ..utils import escape_html
from ..utils import git_async
from ..utils.proc import run_cmd

logger = logging.getLogger(__name__)

_DB_OWNER = "kitsune.updater"

_TTL = 120


_PIP_TIMEOUT_ALL = 1200
_PIP_TIMEOUT_ONE = 600

class UpdaterModule(KitsuneModule):
    name        = "updater"
    description = "Обновление и перезапуск"
    version     = "1.3.0"
    author      = "Yushi"
    REPO_URL = "https://github.com/KitsuneX-dev/Kitsune"
    strings_ru = {
        "checking":   "🔍 Проверяю обновления...",
        "up_to_date": "✅ У тебя последняя версия.",
        "notify_sent": (
            "🦊 <b>KITSUNE // UPDATE_LOG</b>\n\n"
            "<b>[STATUS]</b> Доступна новая версия!\n"
            "<b>[BUILD ]</b> <code>{current}</code> → <code>{new}</code>\n"
            "Коммитов впереди: <code>{count}</code>\n\n"
            "📬 Уведомление с кнопкой отправлено в <b>{group}</b>"
        ),
        "no_notifier": (
            "🦊 <b>KITSUNE // UPDATE_LOG</b>\n\n"
            "<b>[STATUS]</b> Доступна новая версия!\n"
            "<b>[BUILD ]</b> <code>{current}</code>\n"
            "Коммитов впереди: <code>{count}</code>\n\n"
            "<b>CHANGELOG:</b>\n{changes}\n\n"
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
            "⏱ Перезапуск: <code>{restart_time}</code>\n"
            "📦 Модули: <code>{mod_count}</code>\n"
            "⚡ Полная загрузка: <code>{total_time}</code>"
        ),
        "update_done": (
            "✅ <b>Обновление успешно установлено!</b>\n\n"
            "⏱ Перезапуск: <code>{restart_time}</code>\n"
            "📦 Модули: <code>{mod_count}</code>\n"
            "⚡ Полная загрузка: <code>{total_time}</code>"
        ),
        "rollback_no_args": (
            "🦊 <b>KITSUNE // ROLLBACK</b>\n\n"
            "Выбери коммит, к которому нужно откатиться:"
        ),
        "rollback_ok":  "✅ <b>Откат выполнен. Перезапускаю...</b>",
        "rollback_err": "❌ <b>Не удалось откатиться к коммиту.</b>",
        "rollback_no_git": "❌ Git-репозиторий не найден или GitPython не установлен.",
        "cancel": "❌ Отмена",
    }
    async def on_load(self) -> None:
        restart_data = self.db.get(_DB_OWNER, "pending_restart", None)
        if not restart_data:
            return
        await self.db.delete(_DB_OWNER, "pending_restart")
        restart_start = restart_data.get("start_time", 0)
        now           = time.time()
        total_elapsed = now - restart_start
        restart_time  = _fmt_time(total_elapsed * 0.4)
        total_time    = _fmt_time(total_elapsed)
        loader    = getattr(self.client, "_kitsune_loader", None)
        mod_count = len(loader.modules) if loader else 0
        is_update  = restart_data.get("is_update", False)
        string_key = "update_done" if is_update else "boot_done"
        report = self.strings(string_key).format(
            restart_time=restart_time,
            mod_count=mod_count,
            total_time=total_time,
        )
        chat_id = restart_data.get("chat_id", 0)
        msg_id  = restart_data.get("msg_id", 0)
        if chat_id and msg_id:
            asyncio.ensure_future(
                self._post_restart_edit(chat_id, msg_id, report, loader, total_time, restart_time, mod_count, is_update)
            )
    async def _post_restart_edit(
        self,
        chat_id: int,
        msg_id: int,
        report: str,
        loader: typing.Any,
        total_time: str,
        restart_time: str,
        mod_count: int,
        is_update: bool = False,
    ) -> None:
        await asyncio.sleep(3)
        try:
            await self.client.edit_message(chat_id, msg_id, report, parse_mode="html")
        except Exception:
            try:
                await self.client.send_message(chat_id, report, parse_mode="html")
            except Exception:
                pass
        if is_update:
            return
        notifier = loader.modules.get("notifier") if loader else None
        if notifier:
            try:
                await notifier.send_restart_report(
                    restart_time=restart_time,
                    total_time=total_time,
                    mod_count=mod_count,
                )
            except Exception:
                pass
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
            repo = await git_async.open_repo(repo_path)
        except Exception:
            await m.edit(self.strings("no_git"), parse_mode="html")
            return
        try:


            await git_async.fetch(repo, "origin")
            branch = await git_async.active_branch(repo)
            behind = await git_async.iter_commits(repo, f"HEAD..origin/{branch}")
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
                remote_version = await git_async.git_show(repo, f"origin/{branch}:kitsune/version.py")
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
            inline = getattr(self.client, "_kitsune_inline", None)
            shown_inline = False
            version_changed_local = str(__version_str__).strip() != str(new_ver).strip()
            if inline:
                try:
                    if version_changed_local:
                        preview_text = (
                            f"🦊 <b>KITSUNE // UPDATE_LOG</b>\n\n"
                            f"<b>[STATUS]</b> Доступна новая версия!\n"
                            f"<b>[BUILD ]</b> <code>{__version_str__}</code> → <code>{new_ver}</code>\n\n"
                            f"<b>CHANGELOG:</b>\n{changes}\n\n"
                            f"🔘 Запустить процесс обновления?"
                        )
                        apply_label = "⬆️ Обновить"
                    else:
                        preview_text = (
                            f"🦊 <b>KITSUNE // HOTFIX</b>\n\n"
                            f"<b>[STATUS]</b> Обнаружены улучшения!\n"
                            f"<b>[PATCH ]</b> Локальные исправления кода\n\n"
                            f"<b>CHANGELOG:</b>\n{changes}\n\n"
                            f"<b>SYSTEM:</b>\n"
                            f"Версия остается прежней, требуется перезагрузка для применения патчей.\n\n"
                            f"🔘 Применить изменения?"
                        )
                        apply_label = "🛠 Применить"
                    markup = [
                        [
                            {"text": apply_label,  "callback": self._cb_do_update,     "args": (repo_path,)},
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
                        f"🦊 <b>KITSUNE // UPDATE_LOG</b>\n\n"
                        f"<b>[STATUS]</b> Доступна новая версия!\n"
                        f"<b>[BUILD ]</b> <code>{__version_str__}</code> → <code>{new_ver}</code>\n"
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
        chat_id = getattr(call, "chat_id", 0) or pending.get("chat_id", 0)
        msg_id  = getattr(call, "message_id", 0) or pending.get("msg_id", 0)
        inline_message_id = getattr(call, "inline_message_id", "") or ""
        async def _edit(text: str) -> None:
            if inline:
                try:
                    await inline.edit(call, text, [])
                except Exception:
                    pass
        notifier = self._get_notifier()
        if notifier and notifier._updater:
            asyncio.ensure_future(
                notifier._updater.do_update_inline(
                    chat_id=chat_id,
                    msg_id=msg_id,
                    edit_fn=_edit,
                    inline_message_id=inline_message_id,
                )
            )
        else:
            await self._do_update(repo_path=repo_path, chat_id=chat_id, msg_id=msg_id)
    async def _cb_cancel_update(self, call) -> None:
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
        config_path   = os.path.join(repo_path, "config.toml")
        config_backup = None
        config_restored = False


        config_mode: int | None = None
        try:
            repo = await git_async.open_repo(repo_path)
            branch = await git_async.active_branch(repo)
            if os.path.exists(config_path):


                fd, config_backup = tempfile.mkstemp(suffix=".toml", prefix="kitsune_cfg_")
                os.close(fd)
                config_mode = os.stat(config_path).st_mode & 0o777


                shutil.copyfile(config_path, config_backup)


            await git_async.fetch(repo, "origin")
            try:
                await git_async.git_rm(repo, "--cached", "config.toml", "--ignore-unmatch")
            except Exception:
                pass
            await git_async.git_reset(repo, "--hard", f"origin/{branch}")
            if config_backup and os.path.exists(config_backup):
                shutil.copyfile(config_backup, config_path)
                if config_mode is not None:
                    with contextlib.suppress(OSError):
                        os.chmod(config_path, config_mode)
                config_restored = True
        except Exception as exc:
            await edit(self.strings("git_err").format(err=escape_html(str(exc))))
            return
        finally:


            if config_backup and os.path.exists(config_backup):


                if not config_restored:
                    try:
                        shutil.copyfile(config_backup, config_path)
                        if config_mode is not None:
                            with contextlib.suppress(OSError):
                                os.chmod(config_path, config_mode)
                        config_restored = True
                    except OSError as _restore_exc:
                        logger.error(
                            "updater: не удалось восстановить config.toml из %s — %s; "
                            "копия НЕ удаляется, восстанови её вручную",
                            config_backup, _restore_exc,
                        )
                if config_restored:
                    try:
                        os.unlink(config_backup)
                    except OSError as _unlink_exc:
                        logger.warning(
                            "updater: не удалось удалить временную копию конфига %s — %s",
                            config_backup, _unlink_exc,
                        )
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


                    rc, _out, err = await run_cmd(
                        [
                            sys.executable, "-m", "pip", "install", pkg,
                            "--quiet", "--no-warn-script-location",
                            "--prefer-binary", "--no-build-isolation",
                        ],
                        timeout=_PIP_TIMEOUT_ONE,
                        cwd=repo_path,
                    )
                    if rc != 0:
                        err_txt = err.decode(errors="replace").strip() or f"pip rc={rc}"
                        if "platform android is not supported" not in err_txt.lower():
                            pip_errors.append(f"{pkg}: {err_txt[:120]}")
            except Exception as exc:
                pip_errors.append(str(exc))
        else:
            rc, _out, stderr = await run_cmd(
                [
                    sys.executable, "-m", "pip", "install", "-r", req_file,
                    "--quiet", "--no-warn-script-location",
                ],
                timeout=_PIP_TIMEOUT_ALL,
                cwd=repo_path,
            )
            if rc != 0:
                pip_errors.append(
                    stderr.decode(errors="replace")[:500] or f"pip rc={rc}"
                )
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
        await self._save_restart_start(chat_id=chat_id, msg_id=msg_id, is_update=True)
        await asyncio.sleep(1)
        await graceful_restart(self.client, self.db)
        os.execl(sys.executable, sys.executable, "-m", "kitsune")
    def _repo_path(self) -> str:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    async def _get_recent_commits(self, count: int = 4) -> list:


        try:
            repo = await git_async.open_repo(self._repo_path())
            return await git_async.iter_commits(repo, "HEAD", max_count=count)
        except Exception:
            return []

    async def _rollback_to_commit(self, commit: str) -> bool:
        try:
            repo = await git_async.open_repo(self._repo_path())
            await git_async.git_reset(repo, "--hard", commit)
            return True
        except Exception:
            return False

    async def _cb_rollback(self, call, commit: str) -> None:
        inline = getattr(self.client, "_kitsune_inline", None)
        if await self._rollback_to_commit(commit):
            if inline:
                try:
                    await inline.edit(call, self.strings("rollback_ok"), [])
                except Exception:
                    pass
            await self._save_restart_start(
                chat_id=getattr(call, "chat_id", 0) or 0,
                msg_id=getattr(call, "message_id", 0) or 0,
                is_update=True,
            )
            await asyncio.sleep(1)
            await graceful_restart(self.client, self.db)
            os.execl(sys.executable, sys.executable, "-m", "kitsune")
        elif inline:
            try:
                await inline.edit(call, self.strings("rollback_err"), [])
            except Exception:
                pass

    @command("rollback", required=OWNER)
    async def rollback_cmd(self, event) -> None:
        args = self.get_args(event).strip()
        try:
            import git  # noqa: F401
        except ImportError:
            await event.reply(self.strings("rollback_no_git"), parse_mode="html")
            return

        if args:
            m = await event.reply("🔄 Откатываюсь...", parse_mode="html")
            if await self._rollback_to_commit(args):
                await m.edit(self.strings("rollback_ok"), parse_mode="html")
                await self._save_restart_start(chat_id=event.chat_id, msg_id=m.id, is_update=True)
                await asyncio.sleep(1)
                await graceful_restart(self.client, self.db)
                os.execl(sys.executable, sys.executable, "-m", "kitsune")
            else:
                await m.edit(self.strings("rollback_err"), parse_mode="html")
            return

        commits = await self._get_recent_commits(5)
        if len(commits) <= 1:
            await event.reply(self.strings("rollback_no_git"), parse_mode="html")
            return
        commits = commits[1:]

        m = await event.reply(self.strings("rollback_no_args"), parse_mode="html")
        inline = getattr(self.client, "_kitsune_inline", None)
        if not inline:
            listing = "\n".join(
                f"• <code>{c.hexsha[:7]}</code> — {escape_html(c.summary)}"
                for c in commits
            )
            await m.edit(
                self.strings("rollback_no_args") + "\n\n" + listing
                + "\n\n<i>Откат: <code>.rollback &lt;hash&gt;</code></i>",
                parse_mode="html",
            )
            return

        markup = [
            [{
                "text": (c.summary or c.hexsha[:7])[:60],
                "callback": self._cb_rollback,
                "args": (c.hexsha,),
            }]
            for c in commits
        ] + [[{"text": self.strings("cancel"), "action": "close"}]]
        try:
            await inline.form(self.strings("rollback_no_args"), m, markup)
        except Exception:
            await m.edit(self.strings("rollback_err"), parse_mode="html")

    @command("restart", required=OWNER)
    async def restart_cmd(self, event) -> None:
        m = await event.reply("🔄 Перезапускаю...", parse_mode="html")
        await self._save_restart_start(chat_id=event.chat_id, msg_id=m.id)
        await asyncio.sleep(1)
        await graceful_restart(self.client, self.db)
        os.execl(sys.executable, sys.executable, "-m", "kitsune")
    async def _save_restart_start(self, chat_id: int = 0, msg_id: int = 0, is_update: bool = False) -> None:
        now = time.time()
        await self.db.set(_DB_OWNER, "pending_restart", {
            "start_time": now,
            "chat_id":    chat_id,
            "msg_id":     msg_id,
            "is_update":  is_update,
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
