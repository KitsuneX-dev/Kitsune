"""
Kitsune built-in: Notifier
Автоматически создаёт бота через @BotFather и присылает уведомления об обновлениях.
Команды: .resetbot
"""

# © Yushi (@Mikasu32), 2024-2026
# Kitsune Userbot — License: AGPLv3

from __future__ import annotations

import asyncio
import logging
import re
import os

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER

logger = logging.getLogger(__name__)

_DB_OWNER = "kitsune.notifier"
_CHECK_INTERVAL = 30  # проверять каждые 30 секунд


class NotifierModule(KitsuneModule):
    name        = "notifier"
    description = "Авто-создание бота и уведомления об обновлениях"
    author      = "Yushi"
    version     = "1.1"

    strings_ru = {
        "creating":      "🤖 Создаю бота через @BotFather...",
        "already":       "✅ Бот уже настроен: <b>{name}</b>\nЧтобы сбросить и пересоздать: <code>.resetbot</code>",
        "done":          "✅ Бот <b>{name}</b> создан и подключён!\nТокен сохранён автоматически.",
        "botfather_err": "❌ Не удалось создать бота:\n<code>{err}</code>",
        "reset_done":    "♻️ Бот сброшен. Перезапусти Kitsune — бот создастся заново.",
        "frozen_hint":   (
            "⚠️ <b>Бот заморожен Telegram.</b>\n\n"
            "Создай нового бота у @BotFather и замени токен в config.toml:\n\n"
            "<code>bot_token = \"новый_токен\"</code>\n\n"
            "Затем перезапусти Kitsune."
        ),
        "update_notify": (
            "🦊 <b>Kitsune Userbot</b>\n\n"
            "🆕 Доступно обновление!\n"
            "Текущая версия: <code>{current}</code>\n"
            "Новая версия: <code>{new}</code>\n\n"
            "<b>Изменения:</b>\n{changes}"
        ),
        "updating":    "⏳ Обновляю Kitsune...",
        "update_done": "✅ Обновление завершено! Перезапускаю...",
        "update_err":  "❌ Ошибка:\n<code>{err}</code>",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._bot          = None
        self._dp           = None
        self._polling_task = None
        self._check_task   = None

    async def on_load(self) -> None:
        # 1. Check if config.toml has a manually set token (for frozen bot recovery)
        config_token = self._load_token_from_config()
        if config_token:
            await self.db.set(_DB_OWNER, "bot_token", config_token)
            logger.info("Notifier: token loaded from config.toml")

        token = self.db.get(_DB_OWNER, "bot_token", None)

        if token:
            # Already have a token — start polling
            asyncio.ensure_future(self._start_polling(str(token)))
            self._check_task = asyncio.ensure_future(self._update_check_loop())
        else:
            # First run — auto-create bot via BotFather
            asyncio.ensure_future(self._auto_setup())

    async def on_unload(self) -> None:
        if self._check_task and not self._check_task.done():
            self._check_task.cancel()
        await self._stop_polling()

    # ── Commands ──────────────────────────────────────────────────────────────

    @command("resetbot", required=OWNER)
    async def resetbot_cmd(self, event) -> None:
        """.resetbot — сбросить бота (будет пересоздан при следующем запуске)"""
        await self.db.delete(_DB_OWNER, "bot_token")
        await self.db.delete(_DB_OWNER, "bot_name")
        await self._stop_polling()
        await event.reply(self.strings("reset_done"), parse_mode="html")

    # ── Auto setup ────────────────────────────────────────────────────────────

    async def _auto_setup(self) -> None:
        """Talk to @BotFather, create a bot, extract token."""
        try:
            me           = await self.client.get_me()
            bot_name     = f"Kitsune {me.first_name}"
            base_username = f"kitsune_{me.id}_bot"

            logger.info("Notifier: starting BotFather auto-setup...")

            async with self.client.conversation("@BotFather", timeout=30) as conv:
                await conv.send_message("/start")
                await conv.get_response()

                await conv.send_message("/newbot")
                await conv.get_response()

                # Send display name
                await conv.send_message(bot_name)
                await conv.get_response()

                # Try usernames until one works
                token = None
                for suffix in ["", f"_{me.id % 10000}", "_ub", "_kitsune_ub"]:
                    username = f"kitsune_{me.id}{suffix}_bot"
                    await conv.send_message(username)
                    resp = await conv.get_response()
                    text = resp.text or ""

                    match = re.search(r"(\d{8,}:[A-Za-z0-9_-]{35,})", text)
                    if match:
                        token = match.group(1)
                        break

                    # Username taken or invalid — try next
                    if "Sorry" in text or "invalid" in text.lower() or "try" in text.lower():
                        continue
                    break

            if not token:
                raise RuntimeError("Не удалось получить токен от @BotFather")

            await self.db.set(_DB_OWNER, "bot_token", token)
            await self.db.set(_DB_OWNER, "bot_name",  bot_name)
            await self.db.set(_DB_OWNER, "owner_id",  me.id)
            self._save_token_to_config(token)

            logger.info("Notifier: bot created — %s", bot_name)

            # Tell user in Saved Messages
            await self.client.send_message(
                "me",
                self.strings("done").format(name=bot_name),
                parse_mode="html",
            )

            asyncio.ensure_future(self._start_polling(token))
            self._check_task = asyncio.ensure_future(self._update_check_loop())

        except asyncio.TimeoutError:
            logger.warning("Notifier: BotFather timed out, will retry on next restart")
        except Exception:
            logger.exception("Notifier: auto setup failed")

    # ── Config helpers ────────────────────────────────────────────────────────

    def _load_token_from_config(self) -> str | None:
        try:
            import toml
            from pathlib import Path
            cfg_path = Path(__file__).parent.parent.parent / "config.toml"
            if cfg_path.exists():
                cfg = toml.loads(cfg_path.read_text(encoding="utf-8"))
                val = cfg.get("bot_token")
                return str(val) if val else None
        except Exception:
            pass
        return None

    def _save_token_to_config(self, token: str) -> None:
        try:
            import toml
            from pathlib import Path
            cfg_path = Path(__file__).parent.parent.parent / "config.toml"
            if cfg_path.exists():
                cfg = toml.loads(cfg_path.read_text(encoding="utf-8"))
                cfg["bot_token"] = token
                cfg_path.write_text(toml.dumps(cfg), encoding="utf-8")
                logger.info("Notifier: token saved to config.toml")
        except Exception:
            logger.warning("Notifier: could not write token to config.toml")

    # ── Polling ───────────────────────────────────────────────────────────────

    async def _start_polling(self, token: str) -> None:
        try:
            from aiogram import Bot, Dispatcher, Router
            from aiogram.client.default import DefaultBotProperties
            from aiogram.enums import ParseMode
            from aiogram.filters import Command
            from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
        except ImportError:
            logger.warning("Notifier: aiogram not installed, polling disabled")
            return

        await self._stop_polling()

        try:
            self._bot = Bot(
                token=token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            self._dp = Dispatcher()
            router   = Router()
            self._dp.include_router(router)
            ref = self

            @router.message(Command("start"))
            async def on_start(msg: Message) -> None:
                owner_id = ref.db.get(_DB_OWNER, "owner_id", None)
                if msg.from_user.id != owner_id:
                    await msg.answer("🔒 Нет доступа.")
                    return
                await msg.answer(
                    "🦊 <b>Kitsune Notifier</b>\n\n"
                    "Я буду присылать тебе уведомления об обновлениях."
                )

            @router.callback_query(lambda c: c.data == "do_update")
            async def on_update(call: CallbackQuery) -> None:
                owner_id = ref.db.get(_DB_OWNER, "owner_id", None)
                if call.from_user.id != owner_id:
                    await call.answer("🔒 Нет доступа.", show_alert=True)
                    return
                await call.answer()
                await call.message.edit_text(ref.strings("updating"))
                try:
                    await ref._do_update()
                    await call.message.edit_text(ref.strings("update_done"))
                except Exception as exc:
                    await call.message.edit_text(
                        ref.strings("update_err").format(err=str(exc))
                    )

            @router.callback_query(lambda c: c.data == "update_yes")
            async def on_update_yes(call: CallbackQuery) -> None:
                """Handle update confirmation from .update command"""
                owner_id = ref.db.get(_DB_OWNER, "owner_id", None)
                if call.from_user.id != owner_id:
                    await call.answer("🔒 Нет доступа.", show_alert=True)
                    return
                await call.answer()
                pending = ref.db.get("kitsune.updater", "pending_update", None)
                if not pending:
                    await call.message.edit_text("❌ Данные обновления устарели. Запусти .update снова.")
                    return
                await ref.db.delete("kitsune.updater", "pending_update")
                await call.message.edit_text("⬇️ Скачиваю обновление...")
                try:
                    await ref._do_update()
                except Exception as exc:
                    await call.message.edit_text(f"❌ Ошибка:\n<code>{exc}</code>")

            @router.callback_query(lambda c: c.data == "update_no")
            async def on_update_no(call: CallbackQuery) -> None:
                """Handle update cancellation from .update command"""
                owner_id = ref.db.get(_DB_OWNER, "owner_id", None)
                if call.from_user.id != owner_id:
                    await call.answer("🔒 Нет доступа.", show_alert=True)
                    return
                await call.answer("Отменено")
                await ref.db.delete("kitsune.updater", "pending_update")
                await call.message.edit_text("❌ Обновление отменено.")

            self._polling_task = asyncio.ensure_future(
                self._dp.start_polling(self._bot, handle_signals=False)
            )
            logger.info("Notifier: polling started")

        except Exception:
            logger.exception("Notifier: polling failed — bot may be frozen")
            # Notify user in Saved Messages
            await self.client.send_message(
                "me",
                self.strings("frozen_hint"),
                parse_mode="html",
            )

    async def _stop_polling(self) -> None:
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
        if self._dp:
            try:
                await self._dp.stop_polling()
            except Exception:
                pass
        if self._bot:
            try:
                await self._bot.session.close()
            except Exception:
                pass
        self._bot          = None
        self._dp           = None
        self._polling_task = None

    # ── Auto update check ────────────────────────────────────────────────────

    async def _update_check_loop(self) -> None:
        """Check GitHub for new commits every 30 seconds."""
        await asyncio.sleep(30)  # wait 30s after startup before first check
        while True:
            try:
                await self._check_for_updates()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Notifier: update check failed")
            await asyncio.sleep(_CHECK_INTERVAL)

    async def _check_for_updates(self) -> None:
        """Check GitHub API for new commits (no git, no blocking I/O)."""
        import aiohttp

        REPO   = "KitsuneX-dev/Kitsune"
        BRANCH = "main"

        # Get local HEAD commit sha from git
        try:
            import git
            repo_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..")
            )
            repo = git.Repo(repo_path)
            try:
                local_sha = repo.head.commit.hexsha
                try:
                    BRANCH = repo.active_branch.name
                except TypeError:
                    pass
            except Exception:
                local_sha = None
        except Exception:
            local_sha = None

        # Fetch latest commits from GitHub API (async HTTP — non-blocking)
        try:
            url = f"https://api.github.com/repos/{REPO}/commits?sha={BRANCH}&per_page=10"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        logger.warning("Notifier: GitHub API returned %d", resp.status)
                        return
                    commits = await resp.json()
        except Exception as exc:
            logger.warning("Notifier: GitHub API request failed: %s", exc)
            return

        if not commits:
            return

        latest_sha = commits[0].get("sha", "")
        if not latest_sha:
            return

        # Already notified about this commit
        if latest_sha == self.db.get(_DB_OWNER, "last_notified_commit", None):
            return

        # If we know our local sha — check if we're actually behind
        if local_sha and latest_sha == local_sha:
            return

        # Mark as notified
        await self.db.set(_DB_OWNER, "last_notified_commit", latest_sha)

        from ..version import __version_str__

        # Build changes list from GitHub commit messages
        if local_sha:
            # Find how many commits ahead GitHub is
            shas = [c.get("sha", "") for c in commits]
            if local_sha in shas:
                idx = shas.index(local_sha)
                new_commits = commits[:idx]
            else:
                new_commits = commits[:5]
        else:
            new_commits = commits[:5]

        if not new_commits:
            return

        changes = "\n".join(
            f"• {c['commit']['message'].splitlines()[0]}"
            for c in new_commits
            if c.get("commit", {}).get("message")
        )
        new_ver = f"{__version_str__}+{len(new_commits)}"

        await self.notify_update(
            current=__version_str__,
            new=new_ver,
            changes=changes or "—",
        )
        logger.info("Notifier: update notification sent (%d new commits)", len(new_commits))

    # ── Public API for updater ────────────────────────────────────────────────

    async def send_restart_report(
        self,
        restart_time: str,
        total_time: str,
        mod_count: int,
    ) -> None:
        """Send restart completion report via bot."""
        token    = self.db.get(_DB_OWNER, "bot_token", None)
        owner_id = self.db.get(_DB_OWNER, "owner_id",  None)
        if not token or not owner_id:
            return
        try:
            from aiogram import Bot
            from aiogram.client.default import DefaultBotProperties
            from aiogram.enums import ParseMode

            bot = Bot(
                token=str(token),
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            text = (
                "✅ <b>Kitsune перезапущен</b>\n\n"
                f"⏱ Время перезапуска: <code>{restart_time}</code>\n"
                f"📦 Модули загружены: <code>{mod_count}</code>\n"
                f"⚡ Полная загрузка заняла: <code>{total_time}</code>"
            )
            await bot.send_message(chat_id=int(owner_id), text=text)
            await bot.session.close()
        except Exception:
            logger.exception("Notifier: failed to send restart report")



    async def notify_update(self, current: str, new: str, changes: str = "") -> None:
        token    = self.db.get(_DB_OWNER, "bot_token", None)
        owner_id = self.db.get(_DB_OWNER, "owner_id",  None)
        if not token or not owner_id:
            return
        try:
            from aiogram import Bot
            from aiogram.client.default import DefaultBotProperties
            from aiogram.enums import ParseMode
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            bot = Bot(
                token=str(token),
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⬆️ Обновить", callback_data="do_update"),
            ]])
            await bot.send_message(
                chat_id=int(owner_id),
                text=self.strings("update_notify").format(
                    current=current, new=new,
                    changes=changes or "—",
                ),
                reply_markup=kb,
            )
            await bot.session.close()
        except Exception:
            logger.exception("Notifier: failed to send update notification")

    # ── Update logic ──────────────────────────────────────────────────────────

    async def _do_update(self) -> None:
        import sys
        repo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        try:
            import git
            repo = git.Repo(repo_path)
            repo.remote("origin").pull()
        except Exception as exc:
            raise RuntimeError(f"Git pull failed: {exc}") from exc

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
            "--quiet", cwd=repo_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode()[:300])

        await asyncio.sleep(1)
        os.execl(sys.executable, sys.executable, "-m", "kitsune")
