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
        Message as AiogramMessage,
        ForceReply,
    )
    AIOGRAM_AVAILABLE = True
except ImportError:
    AIOGRAM_AVAILABLE = False

from .types import InlineCall

_UNIT_TTL = 60 * 60 * 24

# Ожидающие ввода: {chat_id: {handler, args, kwargs, call, prompt_msg_id}}
_pending_inputs: dict[int, dict] = {}


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
        self._router.message.register(self._on_message)
        self._started = True
        asyncio.ensure_future(self._dp.start_polling(self._bot, handle_signals=False))
        asyncio.ensure_future(self._cleaner())
        await asyncio.sleep(1)  # Даём polling время инициализироваться
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
            # Чистим зависшие pending_inputs старше 5 минут
            for cid in list(_pending_inputs.keys()):
                if time.time() - _pending_inputs[cid].get("ts", time.time()) > 300:
                    del _pending_inputs[cid]

    def generate_markup(self, buttons: list) -> "InlineKeyboardMarkup | None":
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
                elif "input" in btn:
                    # Кнопка ввода через ForceReply бота
                    cb_id = str(uuid.uuid4())[:12]
                    self._callbacks[cb_id] = (
                        self._handle_input_btn,
                        (btn,),
                        self._client.tg_id,
                        btn.get("disable_security", False),
                    )
                    kb_row.append(InlineKeyboardButton(text=text, callback_data=cb_id))
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

    async def _handle_input_btn(self, call: "InlineCall", btn: dict) -> None:
        """Обработка нажатия кнопки с input — бот шлёт ForceReply в чат."""
        if not AIOGRAM_AVAILABLE or not self._bot:
            return
        input_prompt = btn.get("input", "✍️ Введи новое значение этого параметра")
        handler      = btn.get("handler")
        args         = btn.get("args", ())
        kwargs       = btn.get("kwargs", {})

        chat_id = call.chat_id
        if not chat_id:
            return

        try:
            sent = await self._bot.send_message(
                chat_id=chat_id,
                text=(
                    f"✍️ <b>Введи новое значение этого параметра</b>\n"
                    f"⚠️ <i>Не удаляйте ID!</i> 🦊\n\n"
                    f"<i>{input_prompt}</i>"
                ),
                reply_markup=ForceReply(selective=True),
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("_handle_input_btn: failed to send force reply")
            return

        _pending_inputs[chat_id] = {
            "handler":       handler,
            "args":          args,
            "kwargs":        kwargs,
            "call":          call,
            "prompt_msg_id": sent.message_id,
            "ts":            time.time(),
        }
        await call.answer()

    async def _on_message(self, message: "AiogramMessage") -> None:
        """Перехватываем ответ пользователя на ForceReply."""
        if not message.chat:
            return
        chat_id = message.chat.id
        pending = _pending_inputs.get(chat_id)
        if not pending:
            return

        reply = message.reply_to_message
        if not reply or reply.message_id != pending["prompt_msg_id"]:
            return

        del _pending_inputs[chat_id]

        handler = pending["handler"]
        args    = pending["args"]
        kwargs  = pending["kwargs"]
        call    = pending["call"]
        query   = (message.text or "").strip()

        try:
            await self._bot.delete_message(chat_id, pending["prompt_msg_id"])
        except Exception:
            pass
        try:
            await message.delete()
        except Exception:
            pass

        if handler:
            try:
                await handler(call, query, *args, **kwargs)
            except Exception:
                logger.exception("_on_message: handler error")

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
            iid = getattr(call_or_msg, "inline_message_id", None)
            if iid:
                await self._bot.edit_message_text(
                    inline_message_id=iid,
                    text=text,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
            elif hasattr(call_or_msg, "_edit") and callable(call_or_msg._edit):
                await call_or_msg._edit(text, reply_markup=markup, parse_mode="HTML")
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

        reply_to = getattr(message, "reply_to_msg_id", None)

        try:
            peer = getattr(message, "input_chat", None) or getattr(message, "peer_id", None)
            if peer is None:
                peer = await self._client.get_input_entity(getattr(message, "chat_id", None))
            entity = peer
        except Exception:
            logger.error("InlineManager: cannot resolve entity", exc_info=True)
            return None

        await asyncio.sleep(0.3)

        for attempt in range(3):
            try:
                results = await self._client.inline_query(self._bot_username, unit_id)
                if not results:
                    await asyncio.sleep(0.3)
                    continue
                sent = await results[0].click(entity, reply_to=reply_to)
                try:
                    await message.delete()
                except Exception:
                    pass
                return sent
            except Exception as exc:
                err = str(exc)
                if "BotResponseTimeout" in err or "timeout" in err.lower():
                    logger.warning("InlineManager._invoke_unit: timeout attempt %d/3", attempt + 1)
                    await asyncio.sleep(0.5)
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
        wrapped.inline_message_id = call.inline_message_id or ""

        try:
            await handler(wrapped, *args)
        except Exception:
            logger.exception("InlineManager callback error (data=%s)", call.data)
            await call.answer("❌ Ошибка.", show_alert=True)
