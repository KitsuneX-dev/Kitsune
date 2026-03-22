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
        self._client      = client
        self._db          = db
        self._token       = token
        self._bot:        typing.Any = None
        self._dp:         typing.Any = None
        self._callbacks:  dict[str, tuple] = {}
        self._units:      dict[str, dict]  = {}
        self._error_events: dict[str, asyncio.Event] = {}
        self._started     = False
        self._bot_username: str | None = None

    async def _ensure_bot_username(self) -> str | None:
        if self._bot_username:
            return self._bot_username
        if self._bot:
            try:
                me = await self._bot.get_me()
                self._bot_username = me.username
                return self._bot_username
            except Exception:
                pass
        return None

    async def start(self) -> None:
        if not AIOGRAM_AVAILABLE or self._started:
            return
        self._bot = Bot(
            token=self._token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self._dp     = Dispatcher()
        router       = Router()
        self._dp.include_router(router)
        router.callback_query.register(self._on_callback)
        router.inline_query.register(self._on_inline_query)
        self._started = True
        asyncio.ensure_future(self._dp.start_polling(self._bot, handle_signals=False))
        asyncio.ensure_future(self._cleaner())
        await self._ensure_bot_username()
        logger.info("InlineManager: started (bot=@%s)", self._bot_username)

    async def stop(self) -> None:
        if self._bot and self._started:
            await self._dp.stop_polling()
            await self._bot.session.close()
            self._started = False

    async def _cleaner(self) -> None:
        while True:
            await asyncio.sleep(300)
            now = time.time()
            stale_cb = [k for k, v in self._callbacks.items() if v[4] < now]
            for k in stale_cb:
                del self._callbacks[k]
            stale_u = [k for k, v in self._units.items() if v.get("ttl", now + 1) < now]
            for k in stale_u:
                del self._units[k]

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
                    expires = int(time.time()) + _UNIT_TTL
                    self._callbacks[cb_id] = (
                        btn["callback"],
                        btn.get("args", ()),
                        self._client.tg_id,
                        btn.get("disable_security", False),
                        expires,
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
        *,
        parse_mode: str = "HTML",
    ) -> typing.Any:
        if not self._bot:
            return None

        unit_id = str(uuid.uuid4())[:16]
        markup  = self.generate_markup(reply_markup or [])

        self._units[unit_id] = {
            "text":    text,
            "buttons": reply_markup or [],
            "markup":  markup,
            "ttl":     int(time.time()) + _UNIT_TTL,
            "future":  asyncio.Event(),
        }

        bot_username = await self._ensure_bot_username()
        if not bot_username:
            del self._units[unit_id]
            return None

        try:
            chat_id = message.chat_id if hasattr(message, "chat_id") else getattr(message, "peer_id", None)

            results = await self._client.inline_query(bot_username, unit_id)
            if not results:
                raise RuntimeError("No inline results")

            sent = await results[0].click(
                chat_id,
                reply_to=getattr(message, "id", None),
            )

            self._units[unit_id]["chat_id"]    = getattr(sent, "chat_id", None)
            self._units[unit_id]["message_id"] = getattr(sent, "id", None)

            try:
                await message.delete()
            except Exception:
                pass

            return sent

        except Exception as exc:
            logger.exception("InlineManager.form: failed (%s)", exc)
            del self._units[unit_id]
            try:
                await message.edit(text)
            except Exception:
                pass
            return None

    async def edit(
        self,
        call_or_msg: typing.Any,
        text: str,
        reply_markup: list | None = None,
        *,
        parse_mode: str = "HTML",
    ) -> None:
        if not AIOGRAM_AVAILABLE or not self._bot:
            return
        markup = self.generate_markup(reply_markup or [])
        try:
            if hasattr(call_or_msg, "_edit"):
                await call_or_msg._edit(text, reply_markup=markup, parse_mode=parse_mode)
            elif hasattr(call_or_msg, "chat_id") and hasattr(call_or_msg, "message_id"):
                await self._bot.edit_message_text(
                    chat_id=call_or_msg.chat_id,
                    message_id=call_or_msg.message_id,
                    text=text,
                    reply_markup=markup,
                    parse_mode=parse_mode,
                )
            elif hasattr(call_or_msg, "edit"):
                await call_or_msg.edit(text, reply_markup=markup, parse_mode=parse_mode)
        except Exception:
            logger.exception("InlineManager.edit: failed")

    async def _on_inline_query(self, query: "InlineQuery") -> None:
        unit_id = query.query.strip()
        unit    = self._units.get(unit_id)

        if not unit or query.from_user.id != self._client.tg_id:
            await query.answer([], cache_time=0)
            return

        markup = unit.get("markup") or self.generate_markup(unit.get("buttons", []))

        try:
            await query.answer(
                [
                    InlineQueryResultArticle(
                        id=unit_id,
                        title="Kitsune",
                        input_message_content=InputTextMessageContent(
                            message_text=unit["text"],
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                        ),
                        reply_markup=markup,
                    )
                ],
                cache_time=0,
            )
        except Exception:
            logger.exception("InlineManager: inline query answer failed")

        if "future" in unit:
            unit["future"].set()

    async def _on_callback(self, call: "CallbackQuery") -> None:
        entry = self._callbacks.get(call.data)
        if entry is None:
            await call.answer("⚠️ Устаревшая кнопка.", show_alert=True)
            return

        handler, args, owner_id, disable_security, _expires = entry

        if not disable_security and call.from_user.id != owner_id:
            await call.answer("🚫 Нет доступа.", show_alert=True)
            return

        wrapped = InlineCall(
            id=call.id,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            data=call.data,
            _answer=call.answer,
            _edit=call.message.edit_text,
        )

        try:
            await handler(wrapped, *args)
        except Exception:
            logger.exception("InlineManager callback error (data=%s)", call.data)
            await call.answer("❌ Ошибка.", show_alert=True)
