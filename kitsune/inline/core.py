from __future__ import annotations

import asyncio
import logging
import typing
import uuid
import time

logger = logging.getLogger(__name__)

try:
    from aiogram import Bot, Dispatcher, Router
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.types import (
        CallbackQuery,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        InlineQuery,
        InlineQueryResultArticle,
        InputTextMessageContent,
    )
    AIOGRAM_AVAILABLE = True
except ImportError:
    AIOGRAM_AVAILABLE = False

from .types import InlineCall

_UNIT_TTL = 60 * 60 * 24


class InlineManager:

    def __init__(self, client: typing.Any, db: typing.Any, token: str) -> None:
        self._client   = client
        self._db       = db
        self._token    = token
        self._bot:     typing.Any = None
        self._dp:      typing.Any = None
        self._router:  typing.Any = None
        self._callbacks: dict[str, tuple] = {}
        self._units:     dict[str, dict]  = {}
        self._bot_username: str | None    = None
        self._started  = False

    async def start(self) -> None:
        if not AIOGRAM_AVAILABLE:
            return
        if self._started:
            return
        self._bot = Bot(
            token=self._token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self._dp     = Dispatcher()
        self._router = Router()
        self._dp.include_router(self._router)
        self._router.callback_query.register(self._on_callback)
        self._router.inline_query.register(self._on_inline_query)
        self._started = True
        asyncio.ensure_future(self._dp.start_polling(self._bot, handle_signals=False))
        asyncio.ensure_future(self._cleaner())
        try:
            me = await self._bot.get_me()
            self._bot_username = me.username
        except Exception:
            pass
        logger.info("InlineManager: started")

    async def stop(self) -> None:
        if self._bot and self._started:
            await self._dp.stop_polling()
            await self._bot.session.close()
            self._started = False

    async def _cleaner(self) -> None:
        while True:
            await asyncio.sleep(300)
            now = time.time()
            for uid in list(self._units.keys()):
                if self._units[uid].get("ttl", now + 1) < now:
                    del self._units[uid]

    def generate_markup(self, buttons: list) -> InlineKeyboardMarkup | None:
        if not AIOGRAM_AVAILABLE:
            return None
        keyboard: list[list[InlineKeyboardButton]] = []

        def _row(r):
            return r if isinstance(r, list) else [r]

        for row in buttons:
            kb_row: list[InlineKeyboardButton] = []
            for btn in _row(row):
                if not isinstance(btn, dict):
                    continue
                text = btn.get("text", "?")
                if url := btn.get("url"):
                    kb_row.append(InlineKeyboardButton(text=text, url=url))
                elif "callback" in btn:
                    cb_id = str(uuid.uuid4())[:12]
                    self._callbacks[cb_id] = (
                        btn["callback"],
                        btn.get("args", ()),
                        self._client.tg_id,
                        btn.get("disable_security", False),
                    )
                    kb_row.append(InlineKeyboardButton(text=text, callback_data=cb_id))
                elif raw := btn.get("data"):
                    kb_row.append(InlineKeyboardButton(text=text, callback_data=raw))
            if kb_row:
                keyboard.append(kb_row)
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    async def form(
        self,
        text: str,
        message: typing.Any,
        reply_markup: list | None = None,
    ) -> typing.Any:
        unit_id = str(uuid.uuid4())[:16]
        self._units[unit_id] = {
            "text":    text,
            "buttons": reply_markup or [],
            "ttl":     time.time() + _UNIT_TTL,
            "future":  asyncio.Event(),
        }
        result = await self._invoke_unit(unit_id, message)
        return result

    async def edit(
        self,
        call_or_msg: typing.Any,
        text: str,
        reply_markup: list | None = None,
    ) -> None:
        if not AIOGRAM_AVAILABLE or not self._bot:
            return
        markup = self.generate_markup(reply_markup or [])
        try:
            if hasattr(call_or_msg, "_edit"):
                await call_or_msg._edit(text, reply_markup=markup, parse_mode="HTML")
            elif hasattr(call_or_msg, "inline_message_id") and call_or_msg.inline_message_id:
                await self._bot.edit_message_text(
                    inline_message_id=call_or_msg.inline_message_id,
                    text=text,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
            elif hasattr(call_or_msg, "chat_id") and hasattr(call_or_msg, "message_id"):
                await self._bot.edit_message_text(
                    chat_id=call_or_msg.chat_id,
                    message_id=call_or_msg.message_id,
                    text=text,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
        except Exception:
            logger.exception("InlineManager.edit: failed")

    async def _invoke_unit(self, unit_id: str, message: typing.Any) -> typing.Any:
        if not self._bot_username:
            try:
                me = await self._bot.get_me()
                self._bot_username = me.username
            except Exception:
                return None

        chat_id  = getattr(message, "chat_id", None)
        reply_to = getattr(message, "reply_to_msg_id", None)

        await asyncio.sleep(0.5)

        for attempt in range(5):
            try:
                results = await self._client.inline_query(self._bot_username, unit_id)
                if not results:
                    await asyncio.sleep(1)
                    continue
                sent = await results[0].click(chat_id, reply_to=reply_to)
                try:
                    await message.delete()
                except Exception:
                    pass
                return sent
            except Exception as exc:
                err = str(exc)
                if "BotResponseTimeout" in err or "timeout" in err.lower():
                    logger.warning("InlineManager._invoke_unit: timeout attempt %d/3", attempt + 1)
                    await asyncio.sleep(2)
                    continue
                logger.exception("InlineManager._invoke_unit failed")
                return None
        logger.error("InlineManager._invoke_unit: all attempts failed for unit %s", unit_id)
        return None

    async def _on_inline_query(self, query: "InlineQuery") -> None:
        unit_id = query.query.strip()
        unit = self._units.get(unit_id)
        if not unit:
            await query.answer([], cache_time=0)
            return

        markup = self.generate_markup(unit.get("buttons", []))
        try:
            await query.answer(
                results=[
                    InlineQueryResultArticle(
                        id=str(uuid.uuid4()),
                        title="Kitsune",
                        input_message_content=InputTextMessageContent(
                            message_text=unit["text"],
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        ),
                        reply_markup=markup,
                    )
                ],
                cache_time=0,
            )
        except Exception:
            logger.exception("InlineManager._on_inline_query failed")

    async def _on_callback(self, call: "CallbackQuery") -> None:
        entry = self._callbacks.get(call.data)
        if entry is None:
            await call.answer("⚠️ Устаревшая кнопка.", show_alert=True)
            return

        handler, args, owner_id, disable_security = entry

        if not disable_security and call.from_user.id != owner_id:
            await call.answer("🚫 Нет доступа.", show_alert=True)
            return

        wrapped = InlineCall(
            id=call.id,
            chat_id=call.message.chat.id if call.message else 0,
            message_id=call.message.message_id if call.message else 0,
            data=call.data,
            _answer=call.answer,
            _edit=call.message.edit_text if call.message else None,
        )
        wrapped.inline_message_id = call.inline_message_id

        try:
            await handler(wrapped, *args)
        except Exception:
            logger.exception("InlineManager callback error (data=%s)", call.data)
            await call.answer("❌ Ошибка.", show_alert=True)
