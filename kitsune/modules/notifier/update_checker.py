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

                                      
_CHECK_INTERVAL = 3600
                                            
_FIRST_CHECK_DELAY = 300


class UpdateChecker:

    def __init__(self, client, db) -> None:
        self._client     = client
        self._db         = db
        self._check_task: asyncio.Task | None = None
        self._repo_path  = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )

    def start(self) -> None:
        self._check_task = asyncio.ensure_future(self._loop())

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
            remote_version = repo.git.show(f"origin/{branch}:kitsune/version.py")
            import re
            m = re.search(r"__version__\s*=\s*\((\d+),\s*(\d+),\s*(\d+)\)", remote_version)
            new_ver = f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else f"{__version_str__}+{count}"
        except Exception:
            new_ver = f"{__version_str__}+{count}"

        await self.notify_update(current=__version_str__, new=new_ver, changes=changes)

                                                                        
                                                               
                                                                        

    async def notify_update(self, current: str, new: str, changes: str = "") -> str | None:
        """
        Отправляет уведомление об обновлении через inline-бот в группу Kitsune.
        Возвращает название группы куда отправили, или None если не удалось.
        """
        token    = self._db.get(_DB_KEY, "bot_token", None)
        owner_id = self._db.get(_DB_KEY, "owner_id", None)
        if not token or not owner_id:
            logger.debug("UpdateChecker: no bot token/owner_id")
            return None

        text = (
            "🦊 <b>Kitsune Userbot</b>\n\n"
            "🆕 <b>Доступно обновление!</b>\n"
            f"📌 Версия: <code>{current}</code> → <code>{new}</code>\n\n"
            f"📋 <b>Изменения:</b>\n{changes}\n\n"
            "Нажми кнопку для обновления:"
        )

        try:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            from kitsune.modules.notifier.bot_runner import _make_bot

            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⬆️ Обновиться", callback_data="do_update"),
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
        """
        Ищет группу Kitsune «Kitsune <имя_пользователя>» среди диалогов.
        Приоритет: Kitsune <ник> > любая группа с «Kitsune» (НЕ KitsuneBackup).
        Возвращает (chat_id, title) или (None, None).
        """
                                                          
        owner_name: str | None = None
        try:
            me = await self._client.get_me()
            owner_name = me.first_name or ""
            if me.last_name:
                owner_name = f"{owner_name} {me.last_name}".strip()
        except Exception:
            pass

        candidates: list[tuple[int, str, int]] = []                         
        try:
            async for dialog in self._client.iter_dialogs():
                if not (dialog.is_group or (dialog.is_channel and dialog.is_group)):
                    continue
                t = dialog.title or ""
                if "kitsune" not in t.lower():
                    continue
                                                                     
                if t == "KitsuneBackup":
                    continue
                entity = dialog.entity
                cid    = getattr(entity, "id", None)
                if cid is None:
                    continue
                chat_id = int(f"-100{cid}") if getattr(entity, "megagroup", False) or getattr(entity, "broadcast", False) else -cid

                                                                 
                if owner_name and t == f"Kitsune {owner_name}":
                    candidates.append((chat_id, t, 0))
                elif t.startswith("Kitsune"):
                    candidates.append((chat_id, t, 1))
                else:
                    candidates.append((chat_id, t, 2))
        except Exception:
            logger.exception("UpdateChecker: error while searching for Kitsune group")
            return None, None

        if not candidates:
            return None, None

        candidates.sort(key=lambda x: x[2])
        return candidates[0][0], candidates[0][1]

    async def _ensure_bot_in_group(self, chat_id: int, token: str) -> None:
        """Добавляет бота в группу через Telethon если его там нет."""
        try:
            import aiohttp
                                       
            async with aiohttp.ClientSession() as sess:
                async with sess.get(
                    f"https://api.telegram.org/bot{token}/getMe",
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    data = await resp.json()
            if not data.get("ok"):
                return
            bot_username = data["result"]["username"]
            bot_id       = data["result"]["id"]

                                            
            async with aiohttp.ClientSession() as sess:
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

            bot_entity = await self._client.get_entity(bot_username)
            entity     = await self._client.get_entity(chat_id)

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

                                                                        
                                                             
                                                                        

    async def do_update_inline(self, chat_id: int = 0, msg_id: int = 0, edit_fn=None) -> None:
        import inspect as _inspect

        async def edit(text: str) -> None:
            if edit_fn:
                try:
                    r = edit_fn(text)
                    if _inspect.isawaitable(r):
                        await r
                except Exception:
                    pass

        await self._db.set(_DB_KEY, "update_msg_chat",   chat_id)
        await self._db.set(_DB_KEY, "update_msg_id",     msg_id)
        await self._db.set(_DB_KEY, "update_start_time", time.time())
        await self._db.force_save()
        await self._run_update(edit)

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
        await self._run_update(edit)

    async def _run_update(self, edit) -> None:
        await edit("⬇️ <b>Скачиваю обновление...</b>\n████░░░░░░░░  33%")

        try:
            import git
            repo   = git.Repo(self._repo_path)
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

            config_path   = os.path.join(self._repo_path, "config.toml")
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

        await edit("📦 <b>Устанавливаю зависимости...</b>\n████████░░░░  67%")

        is_termux = "com.termux" in os.environ.get("PREFIX", "") or os.path.isdir("/data/data/com.termux")
        req_file  = os.path.join(
            self._repo_path,
            "requirements-termux.txt" if is_termux else "requirements.txt",
        )
        if not os.path.exists(req_file):
            req_file = os.path.join(self._repo_path, "requirements.txt")

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "-r", req_file, "--quiet",
            cwd=self._repo_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode()[:300])

        await edit("🔄 <b>Перезапускаю...</b>\n████████████  100%")
        await asyncio.sleep(1)
        os.execl(sys.executable, sys.executable, "-m", "kitsune")


    async def notify_update_done(self) -> None:
        chat_id    = self._db.get(_DB_KEY, "update_msg_chat",  None)
        msg_id     = self._db.get(_DB_KEY, "update_msg_id",    None)
        start_time = self._db.get(_DB_KEY, "update_start_time", None)
        if not chat_id or not msg_id or not start_time:
            return

        await self._db.delete(_DB_KEY, "update_msg_chat")
        await self._db.delete(_DB_KEY, "update_msg_id")
        await self._db.delete(_DB_KEY, "update_start_time")

        await asyncio.sleep(3)
        elapsed      = time.time() - float(start_time)
        restart_time = _fmt_time(elapsed)

        loader    = getattr(self._client, "_kitsune_loader", None)
        mod_count = len(loader.modules) if loader else 0

        token    = self._db.get(_DB_KEY, "bot_token",  None)
        owner_id = self._db.get(_DB_KEY, "owner_id",   None)
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
                    f"⏱ Перезапуск: <code>{restart_time}</code>\n"
                    f"📦 Модули: <code>{mod_count}</code>"
                ),
                parse_mode="HTML",
            )
            await bot.session.close()
        except Exception:
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
        except Exception:
            logger.exception("UpdateChecker: failed to send restart report")


def _fmt_time(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} мс"
    elif seconds < 60:
        return f"{seconds:.1f} с"
    else:
        m, s = divmod(int(seconds), 60)
        return f"{m}м {s}с"
