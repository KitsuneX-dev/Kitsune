from __future__ import annotations

import asyncio
import logging
import re

from ...core.loader import KitsuneModule, command
from ...core.security import OWNER
from .bot_setup import BotSetup
from .bot_runner import BotRunner
from .update_checker import UpdateChecker

logger = logging.getLogger(__name__)

_DB_KEY = "kitsune.notifier"

class NotifierModule(KitsuneModule):
    name        = "notifier"
    description = "Авто-создание бота и уведомления"
    author      = "Yushi"
    version     = "1.3"

    strings_ru = {
        "creating":   "🤖 Создаю бота через @BotFather...",
        "done":       "✅ Бот <b>{name}</b> создан и подключён!\nТокен сохранён автоматически.",
        "reused":     "♻️ Бот <b>{name}</b> уже существует — переподключаю.\nПересоздавать не нужно.",
        "reset_done": "♻️ Бот сброшен. Перезапусти Kitsune — бот создастся заново.",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._setup:   BotSetup | None = None
        self._runner:  BotRunner | None = None
        self._updater: UpdateChecker | None = None

    async def on_load(self) -> None:
        self._setup   = BotSetup(self.client, self.db)
        self._runner  = BotRunner(self.client, self.db)
        self._updater = UpdateChecker(self.client, self.db)

        config_token = self._setup.load_token_from_config()
        if config_token:
            await self.db.set(_DB_KEY, "bot_token", config_token)
            logger.info("Notifier: token loaded from config.toml")

        token = self.db.get(_DB_KEY, "bot_token", None)
        if token:
            backup_asked = self.db.get(_DB_KEY, "backup_interval_asked", False)
            asyncio.ensure_future(self._runner.start(str(token), first_run=not backup_asked))
            self._updater.start()
            asyncio.ensure_future(self._updater.notify_update_done())
            asyncio.ensure_future(self._start_inline_manager(str(token)))
            asyncio.ensure_future(self._polling_watchdog(str(token)))
        else:
            asyncio.ensure_future(self._auto_setup())

    async def on_unload(self) -> None:
        if self._updater:
            self._updater.stop()
        if self._runner:
            await self._runner.stop()

    @command("resetbot", required=OWNER)
    async def resetbot_cmd(self, event) -> None:
        for key in ("bot_token", "bot_name", "bot_username", "backup_interval_asked"):
            await self.db.delete(_DB_KEY, key)
        if self._runner:
            await self._runner.stop()
        await event.reply(self.strings("reset_done"), parse_mode="html")

    @command("fixbot", required=OWNER)
    async def fixbot_cmd(self, event) -> None:
        username = self.db.get(_DB_KEY, "bot_username", None)
        if not username:
            await event.reply("❌ Бот не найден. Запусти <code>.resetbot</code>", parse_mode="html")
            return
        m = await event.reply(f"⚙️ Включаю Inline Mode для @{username}...", parse_mode="html")
        await self._setup.enable_inline_mode(username)
        await m.edit(f"✅ Inline Mode включён для @{username}", parse_mode="html")

    @command("setinline", required=OWNER)
    async def setinline_cmd(self, event) -> None:
        username = self.db.get(_DB_KEY, "bot_username", None)
        if not username:
            await event.reply("❌ Бот не найден. Сначала запусти <code>.setbot</code>", parse_mode="html")
            return
        m = await event.reply("⏳ Включаю inline mode...", parse_mode="html")
        await self._setup.enable_inline_mode(username)
        await m.edit("✅ Inline mode включён. Теперь кнопки работают в чатах!", parse_mode="html")

    @command("mybots", required=OWNER)
    async def mybots_cmd(self, event) -> None:
        m = await event.reply("🔍 Ищу ботов...", parse_mode="html")
        try:
            bots = await self._setup.list_kitsune_bots()
            if not bots:
                await m.edit("❌ Ботов Kitsune не найдено.", parse_mode="html")
                return
            current_token = self.db.get(_DB_KEY, "bot_token", None)
            lines = ["🤖 <b>Боты Kitsune на этом аккаунте:</b>\n"]
            for i, (uname, token) in enumerate(bots, 1):
                active = " ✅ <i>(активный)</i>" if token and token == current_token else ""
                lines.append(f"  {i}. @{uname}{active}")
            lines.append("\nЧтобы выбрать бота: <code>.setbot @username</code>")
            await m.edit("\n".join(lines), parse_mode="html")
        except Exception as exc:
            await m.edit(f"❌ Ошибка: <code>{exc}</code>", parse_mode="html")

    @command("setbot", required=OWNER)
    async def setbot_cmd(self, event) -> None:
        arg = self.get_args(event).strip()

        if re.match(r"^\d{8,}:[A-Za-z0-9_-]{35,}$", arg):
            token = arg
            m = await event.reply("🔍 Проверяю токен...", parse_mode="html")
            try:
                import aiohttp
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(
                        f"https://api.telegram.org/bot{token}/getMe",
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        data = await resp.json()
                if not data.get("ok"):
                    await m.edit(f"❌ Токен недействителен: {data.get('description', '?')}", parse_mode="html")
                    return
                bot_username = data["result"]["username"]
                if self._runner:
                    await self._runner.stop()
                await self.db.set(_DB_KEY, "bot_token", token)
                await self.db.set(_DB_KEY, "bot_username", bot_username)
                self._setup.save_token_to_config(token)
                asyncio.ensure_future(self._runner.start(token, first_run=False))
                await m.edit(f"✅ Теперь использую бота <b>@{bot_username}</b>.", parse_mode="html")
            except Exception as exc:
                await m.edit(f"❌ Ошибка: <code>{exc}</code>", parse_mode="html")
            return

        arg = arg.lstrip("@")
        if not arg:
            await event.reply(
                "❌ Укажи username или токен:\n"
                "<code>.setbot @kitsune_123456_bot</code>\n"
                "<code>.setbot 123456:TOKEN</code>",
                parse_mode="html",
            )
            return

        m = await event.reply("🔍 Получаю токен через @BotFather...", parse_mode="html")
        try:
            token = await self._setup.get_token_for_bot(arg)
            if not token:
                await m.edit(
                    f"❌ Не удалось получить токен для @{arg}.\n\n"
                    "💡 Передай токен напрямую:\n<code>.setbot ТОКЕН</code>",
                    parse_mode="html",
                )
                return
            if self._runner:
                await self._runner.stop()
            await self.db.set(_DB_KEY, "bot_token", token)
            await self.db.set(_DB_KEY, "bot_username", arg)
            self._setup.save_token_to_config(token)
            asyncio.ensure_future(self._runner.start(token, first_run=False))
            await m.edit(f"✅ Теперь использую бота <b>@{arg}</b>.", parse_mode="html")
        except Exception as exc:
            await m.edit(f"❌ Ошибка: <code>{exc}</code>", parse_mode="html")

    async def notify_update(self, current: str, new: str, changes: str = "") -> None:
        if self._updater:
            await self._updater.notify_update(current=current, new=new, changes=changes)

    async def send_restart_report(self, restart_time: str, total_time: str, mod_count: int) -> None:
        if self._updater:
            await self._updater.send_restart_report(restart_time, total_time, mod_count)

    async def _auto_setup(self) -> None:
        try:
            me = await self.client.get_me()
            logger.info("Notifier: first run for tg_id=%d", me.id)
            await self.db.set(_DB_KEY, "owner_tg_id", me.id)

            bot_name = f"Kitsune {me.first_name}"
            token, bot_username = await self._setup.find_existing_bot(me.id)
            reused = bool(token)
            if not token:
                token, bot_username = await self._setup.create_bot(me, bot_name)

            if not token:
                logger.error("Notifier: failed to get token")
                return

            await self.db.set(_DB_KEY, "bot_token", token)
            await self.db.set(_DB_KEY, "bot_name", bot_name)
            await self.db.set(_DB_KEY, "bot_username", bot_username or "")
            await self.db.set(_DB_KEY, "owner_id", me.id)
            self._setup.save_token_to_config(token)

            if bot_username:
                asyncio.ensure_future(self._setup.enable_inline_mode(bot_username))

            key = "reused" if reused else "done"
            await self.client.send_message("me", self.strings(key).format(name=bot_name), parse_mode="html")

            asyncio.ensure_future(self._runner.start(token, first_run=not reused))
            self._updater.start()

        except asyncio.TimeoutError:
            logger.warning("Notifier: BotFather timed out, retry on next restart")
        except Exception:
            logger.exception("Notifier: auto setup failed")

    async def _start_inline_manager(self, token: str) -> None:
        for _ in range(40):
            if self._runner and self._runner.bot and self._runner.dp:
                break
            await asyncio.sleep(0.5)
        try:
            if not (self._runner and self._runner.bot and self._runner.dp):
                logger.warning("Notifier: bot/dispatcher not ready, skipping InlineManager")
                return
            from ...inline.core import InlineManager
            from aiogram import Router as _Router
            inline = InlineManager(self.client, self.db, token)
            inline._bot     = self._runner.bot
            inline._dp      = self._runner.dp
            inline._started = True

            inline_router = _Router()
            inline_router.callback_query.register(inline._on_callback)
            inline_router.inline_query.register(inline._on_inline_query)
            inline_router.chosen_inline_result.register(inline._on_chosen_inline)
            self._runner.dp.include_router(inline_router)

            self.client._kitsune_inline = inline
            logger.info("Notifier: InlineManager attached")
        except Exception:
            logger.exception("Notifier: failed to attach InlineManager")

    async def _polling_watchdog(self, token: str) -> None:
        while True:
            await asyncio.sleep(120)
            if self._runner and self._runner._polling_task and self._runner._polling_task.done():
                exc = self._runner._polling_task.exception() if not self._runner._polling_task.cancelled() else None
                logger.warning("Notifier: polling died (%s) — restarting", exc)
                await self._runner.start(token, first_run=False)
