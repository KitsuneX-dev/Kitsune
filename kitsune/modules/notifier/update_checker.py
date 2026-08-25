from __future__ import annotations
import asyncio
import contextlib
import logging
import os
import shutil
import sys
import tempfile
import time

from ..._internal import exec_restart, graceful_restart
from ...utils import git_async
from ...utils import pyver
from ...utils import update_guard
from ...utils.proc import run_cmd

logger = logging.getLogger(__name__)

_DB_KEY = "kitsune.notifier"

_GUARD_OWNERS = ("kitsune.notifier", "kitsune.updater")

_CHECK_INTERVAL = 3600


_FIRST_CHECK_DELAY = 300


_PIP_TIMEOUT = 1200

class UpdateChecker:
    def __init__(self, client, db) -> None:
        self._client     = client
        self._db         = db
        self._check_task: asyncio.Task | None = None
        self._repo_path  = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
    def start(self) -> None:
        self._check_task = update_guard.spawn_guarded(
            self._loop(),
            db=self._db,
            owners=_GUARD_OWNERS,
            store_error=False,
        )
    def stop(self) -> None:
        if self._check_task and not self._check_task.done():
            self._check_task.cancel()
    async def _loop(self) -> None:
        await asyncio.sleep(_FIRST_CHECK_DELAY)
        while True:
            try:
                await self._check()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("UpdateChecker: check failed")
            await asyncio.sleep(_CHECK_INTERVAL)
    async def _check(self) -> None:


        try:
            repo = await git_async.open_repo(self._repo_path)
            branch = await git_async.active_branch(repo)
        except Exception as exc:
            logger.debug("UpdateChecker: git repo unavailable — %s", exc)
            return
        try:
            await git_async.fetch(repo, None)
        except Exception as exc:
            logger.debug("UpdateChecker: fetch failed — %s", exc)
            return
        try:
            diff = await git_async.git_log(repo, [f"HEAD..origin/{branch}", "--oneline"])
        except Exception as exc:
            logger.debug("UpdateChecker: git log failed — %s", exc)
            return
        if not diff:
            return
        try:
            commits = await git_async.iter_commits(repo, f"origin/{branch}", max_count=1)
            remote_sha = commits[0].hexsha
        except Exception:
            return
        if remote_sha == self._db.get(_DB_KEY, "last_notified_commit", None):
            return
        await self._db.set(_DB_KEY, "last_notified_commit", remote_sha)
        log_lines = diff.splitlines()[:8]
        count     = len(diff.splitlines())
        changes   = "\n".join(
            f"• <b>{line.split()[0]}</b>: {' '.join(line.split()[1:])}"
            for line in log_lines if line.strip()
        ) or "—"
        if count > 8:
            changes += f"\n<i>...и ещё {count - 8} коммитов</i>"
        from kitsune.version import __version_str__
        try:
            remote_version = await git_async.git_show(repo, f"origin/{branch}:kitsune/version.py")
            import re
            m = re.search(r"__version__\s*=\s*\((\d+),\s*(\d+),\s*(\d+)\)", remote_version)
            new_ver = f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else f"{__version_str__}+{count}"
        except Exception:
            new_ver = f"{__version_str__}+{count}"
        await self.notify_update(current=__version_str__, new=new_ver, changes=changes)
    async def notify_update(self, current: str, new: str, changes: str = "") -> str | None:
        token    = self._db.get(_DB_KEY, "bot_token", None)
        owner_id = self._db.get(_DB_KEY, "owner_id", None)
        if not token or not owner_id:
            logger.debug("UpdateChecker: no bot token/owner_id")
            return None
        version_changed = bool(current and new and str(current).strip() != str(new).strip())
        if version_changed:
            text = (
                "🦊 <b>KITSUNE // UPDATE_LOG</b>\n\n"
                "<b>[STATUS]</b> Доступна новая версия!\n"
                f"<b>[BUILD ]</b> <code>{current}</code> → <code>{new}</code>\n\n"
                f"<b>CHANGELOG:</b>\n{changes}\n\n"
                "🔘 Запустить процесс обновления?"
            )
        else:
            text = (
                "🦊 <b>KITSUNE // HOTFIX</b>\n\n"
                "<b>[STATUS]</b> Обнаружены улучшения!\n"
                "<b>[PATCH ]</b> Локальные исправления кода\n\n"
                f"<b>CHANGELOG:</b>\n{changes}\n\n"
                "<b>SYSTEM:</b>\n"
                "Версия остается прежней, требуется перезагрузка для применения патчей.\n\n"
                "🔘 Применить изменения?"
            )
        try:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            from kitsune.modules.notifier.bot_runner import _make_bot
            apply_btn_text = "⬆️ Обновиться" if version_changed else "🛠 Применить"
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=apply_btn_text, callback_data="do_update"),
                InlineKeyboardButton(text="❌ Отмена",      callback_data="update_no"),
            ]])
            bot = _make_bot(str(token))
            group_id, group_name = await self._find_kitsune_group()
            await bot.send_message(chat_id=int(owner_id), text=text, reply_markup=kb)
            if group_id:
                await self._ensure_bot_in_group(group_id, token)
                try:
                    await bot.send_message(chat_id=group_id, text=text, reply_markup=kb)
                    logger.info("UpdateChecker: notification also sent to group '%s'", group_name)
                except Exception as exc:
                    logger.warning("UpdateChecker: could not send to group — %s", exc)
            await bot.session.close()
            logger.info("UpdateChecker: notification sent to owner DM (owner_id=%s)", owner_id)
            return "бота"
        except Exception:
            logger.exception("UpdateChecker: failed to send update notification")
            return None
    async def _find_kitsune_group(self) -> tuple[int | None, str | None]:
        return None, None
    async def _ensure_bot_in_group(self, chat_id: int, token: str) -> None:
        try:
            import aiohttp
            from kitsune.rkn_bypass import get_aiohttp_connector_with_proxy
            async with aiohttp.ClientSession(
                connector=get_aiohttp_connector_with_proxy(),
            ) as sess:
                async with sess.get(
                    f"https://api.telegram.org/bot{token}/getMe",
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    data = await resp.json()
            if not data.get("ok"):
                return
            bot_username = data["result"]["username"]
            bot_id       = data["result"]["id"]
            async with aiohttp.ClientSession(
                connector=get_aiohttp_connector_with_proxy(),
            ) as sess:
                async with sess.get(
                    f"https://api.telegram.org/bot{token}/getChatMember",
                    params={"chat_id": chat_id, "user_id": bot_id},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    member_data = await resp.json()
            status = member_data.get("result", {}).get("status", "")
            if status in ("member", "administrator", "creator"):
                return
            from telethon.tl.functions.channels import InviteToChannelRequest
            from telethon.tl.functions.messages import AddChatUserRequest
            bot_entity = await asyncio.wait_for(self._client.get_entity(bot_username), timeout=15)
            entity     = await asyncio.wait_for(self._client.get_entity(chat_id), timeout=15)
            try:
                if getattr(entity, "megagroup", False) or getattr(entity, "broadcast", False):
                    await self._client(InviteToChannelRequest(channel=entity, users=[bot_entity]))
                else:
                    await self._client(AddChatUserRequest(chat_id=entity.id, user_id=bot_entity, fwd_limit=0))
                logger.info("UpdateChecker: bot @%s added to group", bot_username)
            except Exception as exc:
                logger.debug("UpdateChecker: could not add bot to group — %s", exc)
        except Exception:
            logger.debug("UpdateChecker: _ensure_bot_in_group failed", exc_info=True)
    async def do_update_inline(self, chat_id: int = 0, msg_id: int = 0, edit_fn=None, inline_message_id: str = "") -> None:
        import inspect as _inspect
        async def edit(text: str) -> None:
            if edit_fn:
                try:
                    r = edit_fn(text)
                    if _inspect.isawaitable(r):
                        await r
                except Exception:
                    pass
        await self._db.set(_DB_KEY, "update_msg_chat",      chat_id)
        await self._db.set(_DB_KEY, "update_msg_id",        msg_id)
        await self._db.set(_DB_KEY, "update_msg_inline_id", inline_message_id)
        await self._db.set(_DB_KEY, "update_msg_via_telethon", not inline_message_id)
        await self._db.set(_DB_KEY, "update_start_time",    time.time())
        await self._db.force_save()
        await update_guard.guarded_update(
            lambda: self._run_update(edit),
            db=self._db,
            owners=_GUARD_OWNERS,
            notify=edit,
        )
    async def do_update(self, msg=None) -> None:
        async def edit(text: str) -> None:
            if msg:
                try:
                    await msg.edit_text(text, parse_mode="HTML")
                except Exception:
                    pass
        chat_id = getattr(getattr(msg, "chat", None), "id", 0) if msg else 0
        msg_id  = getattr(msg, "message_id", 0) if msg else 0
        await self._db.set(_DB_KEY, "update_msg_chat",   chat_id)
        await self._db.set(_DB_KEY, "update_msg_id",     msg_id)
        await self._db.set(_DB_KEY, "update_start_time", time.time())
        await self._db.force_save()
        await update_guard.guarded_update(
            lambda: self._run_update(edit),
            db=self._db,
            owners=_GUARD_OWNERS,
            notify=edit,
        )
    async def _ensure_python(self, edit) -> str:
        required = pyver.read_requires_python(self._repo_path)
        if pyver.version_ok(required):
            return sys.executable
        await edit(
            "🐍 <b>Обновляю Python...</b>\n"
            f"Нужен <code>{pyver.format_version(required)}+</code>, "
            f"установлен <code>{pyver.format_version(pyver.current_version())}</code>\n"
            "██████░░░░░░  50%"
        )
        result = await pyver.ensure_python_async(
            self._repo_path,
            required=required,
            log=edit,
        )
        new_python = result.get("python") or sys.executable
        logger.info(
            "UpdateChecker: переключаюсь на Python %s (%s)",
            pyver.format_version(result.get("version")), new_python,
        )
        return new_python
    async def _restart_on(self, python: str) -> None:
        await graceful_restart(self._client, self._db)
        exec_restart(python=python)
    async def _run_update(self, edit) -> None:
        await edit("⬇️ <b>Скачиваю обновление...</b>\n████░░░░░░░░  33%")
        try:
            repo = await git_async.open_repo(self._repo_path)
            for attempt in range(3):
                try:
                    await git_async.fetch(repo, "origin")
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(10)
            branch = await git_async.active_branch(repo)
            config_path   = os.path.join(self._repo_path, "config.toml")
            config_backup = None
            if os.path.exists(config_path):
                backup_dir = os.path.join(self._repo_path, ".kitsune_update_backup")
                try:


                    os.makedirs(backup_dir, mode=0o700, exist_ok=True)
                    config_backup = os.path.join(backup_dir, "config.toml")
                except OSError:
                    fd, config_backup = tempfile.mkstemp(suffix=".toml")
                    os.close(fd)
                try:
                    with open(config_path, "rb") as _src, open(config_backup, "wb") as _dst:
                        _dst.write(_src.read())


                    with contextlib.suppress(OSError):
                        os.chmod(config_backup, 0o600)
                except OSError as _e:
                    logger.warning(
                        "UpdateChecker: failed to backup config.toml (%s) \u2014 skipping backup",
                        _e,
                    )
                    config_backup = None
            await git_async.git_reset(repo, "--hard", f"origin/{branch}")
            if config_backup and os.path.exists(config_backup):
                _restored = False
                try:
                    with open(config_backup, "rb") as _src, open(config_path, "wb") as _dst:
                        _dst.write(_src.read())
                    _restored = True
                except OSError as _e:
                    logger.error(
                        "UpdateChecker: failed to restore config.toml (%s) \u2014 "
                        "backup kept at %s, restore it manually",
                        _e, config_backup,
                    )
                finally:


                    if _restored:
                        try:
                            os.unlink(config_backup)
                        except OSError:
                            pass
                        backup_dir = os.path.join(self._repo_path, ".kitsune_update_backup")
                        if os.path.isdir(backup_dir):
                            try:
                                os.rmdir(backup_dir)
                            except OSError:
                                pass
        except Exception as exc:
            raise RuntimeError(f"Git update failed: {exc}") from exc
        python = await self._ensure_python(edit)
        if os.path.realpath(python) != os.path.realpath(sys.executable):
            await edit("🔄 <b>Перезапускаю на новом Python...</b>\n████████████  100%")
            await asyncio.sleep(1)
            await self._restart_on(python)
            return
        await edit("📦 <b>Устанавливаю зависимости...</b>\n████████░░░░  67%")
        req_file = pyver.default_requirements(self._repo_path)
        if not os.path.exists(req_file):
            req_file = os.path.join(self._repo_path, "requirements.txt")
        rc, _out, stderr = await run_cmd(
            [python, "-m", "pip", "install", "-r", req_file, "--quiet"],
            timeout=_PIP_TIMEOUT,
            cwd=self._repo_path,
        )
        if rc != 0:
            raise RuntimeError(stderr.decode(errors="replace")[:300] or f"pip rc={rc}")
        await edit("🔄 <b>Перезапускаю...</b>\n████████████  100%")
        await asyncio.sleep(1)
        await self._restart_on(python)
    async def notify_update_done(self) -> None:
        chat_id     = self._db.get(_DB_KEY, "update_msg_chat",  None)
        msg_id      = self._db.get(_DB_KEY, "update_msg_id",    None)
        inline_id   = self._db.get(_DB_KEY, "update_msg_inline_id", None)
        start_time  = self._db.get(_DB_KEY, "update_start_time", None)
        if not start_time or (not inline_id and (not chat_id or not msg_id)):
            return
        await self._db.delete(_DB_KEY, "update_msg_chat")
        await self._db.delete(_DB_KEY, "update_msg_id")
        await self._db.delete(_DB_KEY, "update_msg_inline_id")
        await self._db.delete(_DB_KEY, "update_start_time")
        await asyncio.sleep(3)
        elapsed      = time.time() - float(start_time)
        restart_time = _fmt_time(elapsed)
        loader    = getattr(self._client, "_kitsune_loader", None)
        mod_count = len(loader.modules) if loader else 0
        done_text = (
            "✅ <b>Обновление успешно установлено!</b>\n"
            f"⏱ Перезапуск: <code>{restart_time}</code>\n"
            f"📦 Модули: <code>{mod_count}</code>"
        )
        edited = False
        via_telethon = self._db.get(_DB_KEY, "update_msg_via_telethon", False)
        await self._db.delete(_DB_KEY, "update_msg_via_telethon")
        token    = self._db.get(_DB_KEY, "bot_token", None)
        owner_id = self._db.get(_DB_KEY, "owner_id",  None)
        if token and inline_id:
            try:
                from kitsune.modules.notifier.bot_runner import _make_bot
                bot = _make_bot(str(token))
                await bot.edit_message_text(
                    inline_message_id=str(inline_id),
                    text=done_text,
                    parse_mode="HTML",
                )
                await bot.session.close()
                edited = True
                logger.info("UpdateChecker: update message edited via inline_message_id")
            except Exception as _inline_edit_exc:
                logger.debug("UpdateChecker: inline edit failed (%s)", _inline_edit_exc)
        if not edited and token and chat_id and msg_id:
            try:
                from kitsune.modules.notifier.bot_runner import _make_bot
                bot = _make_bot(str(token))
                await bot.edit_message_text(
                    chat_id=int(chat_id),
                    message_id=int(msg_id),
                    text=done_text,
                    parse_mode="HTML",
                )
                await bot.session.close()
                edited = True
                logger.info("UpdateChecker: update message edited via bot")
            except Exception as _bot_edit_exc:
                logger.debug("UpdateChecker: bot edit failed (%s), trying Telethon", _bot_edit_exc)
        if not edited and via_telethon and chat_id and msg_id:
            try:
                tl_chat = int(chat_id)
                if str(tl_chat).startswith("-100"):
                    tl_chat = int(str(tl_chat)[4:])
                await self._client.edit_message(
                    tl_chat,
                    int(msg_id),
                    done_text,
                    parse_mode="html",
                )
                edited = True
                logger.info("UpdateChecker: update message edited via Telethon")
            except Exception as _tl_exc:
                logger.debug("UpdateChecker: Telethon edit failed (%s)", _tl_exc)
        if not edited and token and owner_id:
            try:
                from kitsune.modules.notifier.bot_runner import _make_bot
                bot = _make_bot(str(token))
                await bot.send_message(
                    chat_id=int(owner_id),
                    text=done_text,
                    parse_mode="HTML",
                )
                await bot.session.close()
                logger.info("UpdateChecker: update done sent as new DM message")
            except Exception as _exc2:
                if "Forbidden" in type(_exc2).__name__ or "forbidden" in str(_exc2).lower():
                    logger.warning(
                        "UpdateChecker: бот не может начать диалог. "
                        "Напиши /start боту в Telegram. (%s)", _exc2,
                    )
                else:
                    logger.exception("UpdateChecker: failed to send update_done message")
    async def send_restart_report(self, restart_time: str, total_time: str, mod_count: int) -> None:
        token    = self._db.get(_DB_KEY, "bot_token", None)
        owner_id = self._db.get(_DB_KEY, "owner_id",  None)
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
        except Exception as _exc:
            if "Forbidden" in type(_exc).__name__ or "forbidden" in str(_exc).lower():
                logger.warning(
                    "UpdateChecker: бот не может начать диалог с пользователем. "
                    "Напиши /start боту в Telegram — и уведомления о рестарте заработают. (%s)",
                    _exc,
                )
            else:
                logger.exception("UpdateChecker: failed to send restart report")
def _fmt_time(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} мс"
    elif seconds < 60:
        return f"{seconds:.1f} с"
    else:
        m, s = divmod(int(seconds), 60)
        return f"{m}м {s}с"
