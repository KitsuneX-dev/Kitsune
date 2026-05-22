from __future__ import annotations
import asyncio
import logging
import re
import typing
import uuid
import time

logger = logging.getLogger(__name__)

_TG_EMOJI_VALID = re.compile(
    r'<tg-emoji\s+emoji-id\s*=\s*["\']?(\d+)["\']?\s*>(.*?)</tg-emoji>',
    re.DOTALL | re.IGNORECASE,
)
_TG_EMOJI_ANY_OPEN = re.compile(r'<tg-emoji\b[^>]*>', re.IGNORECASE)
_TG_EMOJI_ANY_CLOSE = re.compile(r'</tg-emoji\s*>', re.IGNORECASE)

def _normalize_tg_emoji(text: str) -> str:
    if not text or "tg-emoji" not in text.lower():
        return text
    def _fix(m: re.Match) -> str:
        emoji_id = m.group(1)
        inner = m.group(2)
        return f'<tg-emoji emoji-id="{emoji_id}">{inner}</tg-emoji>'
    return _TG_EMOJI_VALID.sub(_fix, text)

def _strip_tg_emoji(text: str) -> str:
    if not text or "tg-emoji" not in text.lower():
        return text
    text = _TG_EMOJI_ANY_OPEN.sub("", text)
    text = _TG_EMOJI_ANY_CLOSE.sub("", text)
    return text

try:
    from aiogram import Bot, Dispatcher, Router
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.types import (
        CallbackQuery,
        ChosenInlineResult,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        InlineQuery,
        InlineQueryResultArticle,
        InlineQueryResultGif,
        InlineQueryResultVideo,
        InputTextMessageContent,
        Message as AiogramMessage,
    )
    AIOGRAM_AVAILABLE = True
except ImportError:
    AIOGRAM_AVAILABLE = False
from .types import InlineCall

_UNIT_TTL = 60 * 60 * 24
_INPUT_MARKER = "\u2063\u2060\u2063"

class InlineManager:
    def __init__(self, client: typing.Any, db: typing.Any, token: str) -> None:
        self._client        = client
        self._db            = db
        self._token         = token
        self._bot:          typing.Any = None
        self._dp:           typing.Any = None
        self._router:       typing.Any = None
        self._callbacks:    dict[str, tuple] = {}
        self._units:        dict[str, dict]  = {}
        self._bot_username: str | None       = None
        self._bot_id:       int | None       = None
        self._started       = False
    async def start(self) -> None:
        if not AIOGRAM_AVAILABLE:
            return
        if self._started:
            return
        try:
            from ..rkn_bypass import make_aiogram_bot
            self._bot = make_aiogram_bot(self._token, parse_mode="HTML")
        except Exception as _exc:
            logger.debug("InlineManager: make_aiogram_bot fallback (%s)", _exc)
            self._bot = Bot(
                token=self._token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
        self._dp     = Dispatcher()
        self._router = Router()
        self._dp.include_router(self._router)
        self._router.callback_query.register(self._on_callback)
        self._router.inline_query.register(self._on_inline_query)
        self._router.chosen_inline_result.register(self._on_chosen_inline)
        self._router.message.register(self._on_message)
        self._started = True
        asyncio.ensure_future(self._dp.start_polling(self._bot, handle_signals=False))
        asyncio.ensure_future(self._cleaner())
        await asyncio.sleep(3)
        try:
            me = await self._bot.get_me()
            self._bot_username = me.username
            self._bot_id = me.id
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
    def generate_markup(self, buttons: list) -> "InlineKeyboardMarkup | None":
        if not AIOGRAM_AVAILABLE:
            return None
        keyboard: list[list[InlineKeyboardButton]] = []
        def _row(r):
            return r if isinstance(r, list) else [r]
        for row in buttons:
            for btn in _row(row):
                if isinstance(btn, dict) and "input" in btn and "_switch_query" not in btn:
                    btn["_switch_query"] = str(uuid.uuid4())[:10]
        for row in buttons:
            kb_row: list[InlineKeyboardButton] = []
            for btn in _row(row):
                if not isinstance(btn, dict):
                    continue
                text = btn.get("text", "?")
                if url := btn.get("url"):
                    kb_row.append(InlineKeyboardButton(text=text, url=url))
                elif "input" in btn:
                    kb_row.append(InlineKeyboardButton(
                        text=text,
                        switch_inline_query_current_chat=btn["_switch_query"] + " ",
                    ))
                elif "callback" in btn:
                    cb_id = str(uuid.uuid4())[:12]
                    self._callbacks[cb_id] = (
                        btn["callback"],
                        btn.get("args", ()),
                        self._client.tg_id,
                        btn.get("disable_security", False),
                        btn.get("kwargs", {}),
                    )
                    kb_row.append(InlineKeyboardButton(text=text, callback_data=cb_id))
                elif raw := btn.get("data"):
                    kb_row.append(InlineKeyboardButton(text=text, callback_data=raw))
            if kb_row:
                keyboard.append(kb_row)
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    def _register_callback(
        self,
        func,
        *,
        args: tuple = (),
        kwargs: dict | None = None,
    ) -> str:
        cb_id = str(uuid.uuid4())[:12]
        self._callbacks[cb_id] = (func, args, kwargs or {})
        return cb_id
    async def form(
        self,
        text: str,
        message: typing.Any,
        reply_markup: list | None = None,
        video: str | None = None,
        gif: str | None = None,
    ) -> typing.Any:
        media_url = gif or video
        media_type = None
        if media_url:
            try:
                import os
                from urllib.parse import urlparse
                ext = os.path.splitext(urlparse(media_url).path)[1].lower()
                media_type = "gif" if ext in (".gif", ".mp4") else "video"
            except Exception:
                media_type = "video"
        text = _normalize_tg_emoji(text)
        unit_id = str(uuid.uuid4())[:16]
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        origin_chat_id = getattr(message, "chat_id", None) or getattr(message, "peer_id", None)
        self._units[unit_id] = {
            "text":    text,
            "buttons": reply_markup or [],
            "ttl":     time.time() + _UNIT_TTL,
            "future":  future,
            "inline_message_id": "",
            "chat_id": origin_chat_id,
            **({media_type: media_url} if media_url and media_type else {}),
        }
        sent = await self._invoke_unit(unit_id, message)
        if sent is not None and unit_id in self._units:
            self._units[unit_id]["telethon_msg"] = sent
            sent_chat = getattr(sent, "chat_id", None) or getattr(sent, "peer_id", None)
            if sent_chat is not None:
                self._units[unit_id]["chat_id"] = sent_chat
        try:
            await asyncio.wait_for(asyncio.shield(future), timeout=30)
        except asyncio.TimeoutError:
            logger.warning("form: timeout waiting for inline_message_id for unit %s", unit_id)
        if "future" in self._units.get(unit_id, {}):
            del self._units[unit_id]["future"]
        return sent
    async def edit(
        self,
        call_or_msg: typing.Any,
        text: str,
        reply_markup: list | None = None,
        inline_message_id: str | None = None,
    ) -> None:
        if not AIOGRAM_AVAILABLE or not self._bot:
            return
        text = _normalize_tg_emoji(text)
        markup = self.generate_markup(reply_markup or [])
        effective_iid = inline_message_id or getattr(call_or_msg, "inline_message_id", None)
        if effective_iid:
            unit_key = f"iid:{effective_iid}"
            existing = self._units.get(unit_key, {})
            chat_id = existing.get("chat_id")
            if chat_id is None:
                _cb_msg = getattr(call_or_msg, "message", None)
                chat_id = (
                    getattr(_cb_msg, "chat", None) and getattr(_cb_msg.chat, "id", None)
                ) or getattr(call_or_msg, "chat_id", None) or None
            self._units[unit_key] = {
                "buttons": reply_markup or [],
                "ttl": time.time() + _UNIT_TTL,
                "chat_id": chat_id,
            }
        async def _send_edit_text(_text, _parse_mode, *, _iid=None, _chat=None, _msg=None):
            if _iid is not None:
                await self._bot.edit_message_text(
                    inline_message_id=_iid,
                    text=_text,
                    reply_markup=markup,
                    parse_mode=_parse_mode,
                )
            else:
                await self._bot.edit_message_text(
                    chat_id=_chat,
                    message_id=_msg,
                    text=_text,
                    reply_markup=markup,
                    parse_mode=_parse_mode,
                )
        async def _send_edit_caption(_text, _parse_mode, *, _iid=None, _chat=None, _msg=None):
            if _iid is not None:
                await self._bot.edit_message_caption(
                    inline_message_id=_iid,
                    caption=_text,
                    reply_markup=markup,
                    parse_mode=_parse_mode,
                )
            else:
                await self._bot.edit_message_caption(
                    chat_id=_chat,
                    message_id=_msg,
                    caption=_text,
                    reply_markup=markup,
                    parse_mode=_parse_mode,
                )
        async def _try_text_then_caption(*, _iid=None, _chat=None, _msg=None):
            current_text = text
            try:
                await _send_edit_text(current_text, "HTML", _iid=_iid, _chat=_chat, _msg=_msg)
                return
            except Exception as _exc_text:
                _msg_err = str(_exc_text).lower()
                if (
                    "can't parse entities" in _msg_err
                    or "empty attribute name" in _msg_err
                    or "unsupported start tag" in _msg_err
                    or "unmatched end tag" in _msg_err
                    or "unclosed start tag" in _msg_err
                ):
                    sanitized = _strip_tg_emoji(current_text)
                    try:
                        await _send_edit_text(sanitized, "HTML", _iid=_iid, _chat=_chat, _msg=_msg)
                        return
                    except Exception:
                        try:
                            await _send_edit_text(sanitized, None, _iid=_iid, _chat=_chat, _msg=_msg)
                            return
                        except Exception as _exc_plain:
                            logger.debug(
                                "InlineManager.edit: plain-text fallback failed: %s", _exc_plain,
                            )
                            return
                if (
                    "no text in the message" in _msg_err
                    or "there is no text" in _msg_err
                    or "message can't be edited" in _msg_err
                ):
                    try:
                        await _send_edit_caption(current_text, "HTML", _iid=_iid, _chat=_chat, _msg=_msg)
                        return
                    except Exception as _exc_cap:
                        _cap_err = str(_exc_cap).lower()
                        if (
                            "can't parse entities" in _cap_err
                            or "empty attribute name" in _cap_err
                            or "unsupported start tag" in _cap_err
                            or "unmatched end tag" in _cap_err
                            or "unclosed start tag" in _cap_err
                        ):
                            sanitized = _strip_tg_emoji(current_text)
                            try:
                                await _send_edit_caption(sanitized, "HTML", _iid=_iid, _chat=_chat, _msg=_msg)
                                return
                            except Exception:
                                try:
                                    await _send_edit_caption(sanitized, None, _iid=_iid, _chat=_chat, _msg=_msg)
                                    return
                                except Exception:
                                    pass
                        try:
                            if _iid is not None:
                                await self._bot.edit_message_reply_markup(
                                    inline_message_id=_iid, reply_markup=markup,
                                )
                            else:
                                await self._bot.edit_message_reply_markup(
                                    chat_id=_chat, message_id=_msg, reply_markup=markup,
                                )
                        except Exception:
                            pass
                        logger.debug(
                            "InlineManager.edit: caption fallback also failed: %s", _exc_cap,
                        )
                        return
                raise
        try:
            iid = inline_message_id or getattr(call_or_msg, "inline_message_id", None)
            _cb_msg = getattr(call_or_msg, "message", None)
            _cb_chat_id = (
                getattr(_cb_msg, "chat", None) and getattr(_cb_msg.chat, "id", None)
            )
            _cb_msg_id = getattr(_cb_msg, "message_id", None)
            if iid:
                await _try_text_then_caption(_iid=iid)
            elif hasattr(call_or_msg, "_edit") and callable(call_or_msg._edit):
                try:
                    await call_or_msg._edit(text, reply_markup=markup, parse_mode="HTML")
                except Exception as _exc_edit:
                    _edit_err = str(_exc_edit).lower()
                    if (
                        ("no text in the message" in _edit_err
                         or "there is no text" in _edit_err
                         or "message can't be edited" in _edit_err)
                        and _cb_chat_id and _cb_msg_id
                    ):
                        await _try_text_then_caption(_chat=_cb_chat_id, _msg=_cb_msg_id)
                    else:
                        raise
            elif hasattr(call_or_msg, "chat_id") and hasattr(call_or_msg, "message_id"):
                await _try_text_then_caption(
                    _chat=call_or_msg.chat_id, _msg=call_or_msg.message_id,
                )
            else:
                telethon_msg = getattr(call_or_msg, "_telethon_msg", None)
                if telethon_msg is None:
                    for unit in self._units.values():
                        if unit.get("telethon_msg") is not None:
                            chk = unit["telethon_msg"]
                            if getattr(chk, "id", None) and getattr(chk, "chat_id", None):
                                telethon_msg = chk
                                break
                if telethon_msg is not None:
                    try:
                        await self._client.edit_message(
                            getattr(telethon_msg, "chat_id", None) or getattr(telethon_msg, "peer_id", None),
                            telethon_msg.id,
                            text,
                            parse_mode="html",
                            buttons=None,
                        )
                    except Exception:
                        logger.debug("InlineManager.edit: Telethon fallback also failed", exc_info=True)
        except Exception as _edit_exc:
            _err = str(_edit_exc)
            if "MESSAGE_ID_INVALID" in _err or "message to edit not found" in _err.lower():
                logger.debug("InlineManager.edit: stale message after restart, skipping")
            else:
                logger.exception("InlineManager.edit: failed")
    async def _invoke_unit(self, unit_id: str, message: typing.Any) -> typing.Any:
        if not self._bot_username:
            try:
                me = await self._bot.get_me()
                self._bot_username = me.username
                self._bot_id = me.id
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
        for attempt in range(5):
            try:
                results = await self._client.inline_query(self._bot_username, unit_id)
                if not results:
                    await asyncio.sleep(0.4)
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
                    delay = 0.5 * (attempt + 1)
                    logger.warning(
                        "InlineManager._invoke_unit: timeout attempt %d/5, retrying in %.1fs",
                        attempt + 1, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.exception("InlineManager._invoke_unit failed")
                return None
        logger.error("InlineManager._invoke_unit: all attempts failed for unit %s", unit_id)
        return None
    async def _on_inline_query(self, query: "InlineQuery") -> None:
        try:
            await self._handle_inline_query(query)
        except Exception as exc:
            if "query is too old" in str(exc) or "query ID is invalid" in str(exc):
                logger.debug("InlineManager._on_inline_query: stale query ignored (%s)", exc)
            else:
                logger.exception("InlineManager._on_inline_query failed")
    async def _handle_inline_query(self, query: "InlineQuery") -> None:
        q = query.query.strip()
        for unit in self._units.values():
            for row in unit.get("buttons", []):
                row_ = row if isinstance(row, list) else [row]
                for btn in row_:
                    if not isinstance(btn, dict):
                        continue
                    sq = btn.get("_switch_query", "")
                    if not sq or not q.startswith(sq):
                        continue
                    input_hint = btn.get("input", "✍️ Введи значение")
                    parts = q.split(maxsplit=1)
                    has_value = len(parts) > 1 and parts[1].strip()
                    if has_value:
                        value_preview = parts[1].strip()
                        await query.answer(
                            results=[
                                InlineQueryResultArticle(
                                    id=str(uuid.uuid4()),
                                    title=f"Применить: {value_preview[:50]}",
                                    description="Нажми чтобы сохранить значение",
                                    input_message_content=InputTextMessageContent(
                                        message_text=_INPUT_MARKER,
                                        parse_mode="HTML",
                                        disable_web_page_preview=True,
                                    ),
                                    reply_markup=InlineKeyboardMarkup(
                                        inline_keyboard=[[
                                            InlineKeyboardButton(
                                                text="­",
                                                callback_data="__noop__",
                                            )
                                        ]]
                                    ),
                                )
                            ],
                            cache_time=0,
                        )
                    else:
                        await query.answer(
                            results=[
                                InlineQueryResultArticle(
                                    id=str(uuid.uuid4()),
                                    title=input_hint,
                                    description="Введи значение после пробела и нажми на результат",
                                    input_message_content=InputTextMessageContent(
                                        message_text=_INPUT_MARKER,
                                        parse_mode="HTML",
                                        disable_web_page_preview=True,
                                    ),
                                )
                            ],
                            cache_time=0,
                        )
                    return
        unit = self._units.get(q)
        if not unit:
            await query.answer([], cache_time=0)
            return
        markup = self.generate_markup(unit.get("buttons", []))
        try:
            if "gif" in unit:
                await query.answer(
                    results=[
                        InlineQueryResultGif(
                            id=str(uuid.uuid4()),
                            gif_url=unit["gif"],
                            thumbnail_url="https://img.icons8.com/cotton/452/moon-satellite.png",
                            title="Kitsune",
                            caption=unit["text"],
                            parse_mode="HTML",
                            reply_markup=markup,
                        )
                    ],
                    cache_time=0,
                )
            elif "video" in unit:
                await query.answer(
                    results=[
                        InlineQueryResultVideo(
                            id=str(uuid.uuid4()),
                            title="Kitsune",
                            description="Kitsune UserBot",
                            caption=unit["text"],
                            parse_mode="HTML",
                            video_url=unit["video"],
                            thumbnail_url="https://img.icons8.com/cotton/452/moon-satellite.png",
                            mime_type="video/mp4",
                            reply_markup=markup,
                        )
                    ],
                    cache_time=0,
                )
            else:
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
    async def _wipe_input_message(self, chat_id, sender_id=None) -> None:
        if chat_id is None:
            return
        client = self._client
        if client is None:
            return
        bot_id = self._bot_id
        deadline = time.time() + 6.0
        delay = 0.4
        while time.time() < deadline:
            try:
                async for m in client.iter_messages(chat_id, limit=8):
                    try:
                        text = (getattr(m, "raw_text", None) or getattr(m, "message", "") or "")
                        via_bot = getattr(m, "via_bot_id", None)
                        out = bool(getattr(m, "out", False))
                        if _INPUT_MARKER in text and (
                            (bot_id is not None and via_bot == bot_id) or out
                        ):
                            try:
                                await client.delete_messages(chat_id, [m.id])
                            except Exception:
                                logger.debug("wipe_input_message: delete failed", exc_info=True)
                            return
                    except Exception:
                        continue
            except Exception:
                logger.debug("wipe_input_message: iter_messages failed", exc_info=True)
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 1.2)
        logger.debug("wipe_input_message: marker message not found in %s", chat_id)
    async def _on_chosen_inline(self, result: "ChosenInlineResult") -> None:
        q = result.query.strip()
        if not q:
            return
        for unit_id, unit in self._units.items():
            if (
                unit_id == q
                and "future" in unit
                and isinstance(unit["future"], asyncio.Future)
                and not unit["future"].done()
            ):
                unit["inline_message_id"] = result.inline_message_id
                unit["future"].set_result(result.inline_message_id)
                logger.debug("form: saved inline_message_id=%s for unit %s", result.inline_message_id, unit_id)
                return
        first_word = q.split()[0]
        value = q.split(maxsplit=1)[1] if len(q.split()) > 1 else ""
        for unit_id, unit in self._units.copy().items():
            for row in unit.get("buttons", []):
                row_ = row if isinstance(row, list) else [row]
                for btn in row_:
                    if not isinstance(btn, dict):
                        continue
                    sq = btn.get("_switch_query", "")
                    if not sq or sq != first_word:
                        continue
                    if "input" not in btn:
                        continue
                    handler = btn.get("handler")
                    args    = btn.get("args", ())
                    kwargs  = btn.get("kwargs", {})
                    if not handler:
                        return
                    if unit_id.startswith("iid:"):
                        original_iid = unit_id[4:]
                    else:
                        original_iid = unit.get("inline_message_id", "")
                    chat_id_for_wipe = unit.get("chat_id")
                    if chat_id_for_wipe is None and original_iid:
                        alt = self._units.get(f"iid:{original_iid}")
                        if alt:
                            chat_id_for_wipe = alt.get("chat_id")
                    logger.debug("_on_chosen_inline: input sq=%r val=%r iid=%r chat=%r",
                                 sq, value, original_iid, chat_id_for_wipe)
                    wrapped = InlineCall(
                        id="chosen",
                        chat_id=0,
                        message_id=0,
                        data="",
                        _answer=self._noop_answer,
                        _edit=None,
                    )
                    wrapped.inline_message_id = original_iid
                    sender_id = None
                    try:
                        sender_id = result.from_user.id
                    except Exception:
                        pass
                    if chat_id_for_wipe is not None:
                        asyncio.ensure_future(self._wipe_input_message(chat_id_for_wipe, sender_id))
                    try:
                        await handler(wrapped, value, *args, **kwargs)
                    except Exception:
                        logger.exception("InlineManager._on_chosen_inline: handler error")
                    return
    async def _noop_answer(self, *a, **kw):
        pass
    async def _on_message(self, message: "AiogramMessage") -> None:
        pass
    async def _on_callback(self, call: "CallbackQuery") -> None:
        if call.data == "__noop__":
            await call.answer()
            return
        entry = self._callbacks.get(call.data)
        if entry is None:
            await call.answer("⚠️ Устаревшая кнопка.", show_alert=True)
            return
        handler, args, owner_id, disable_security, kwargs = entry
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
            await handler(wrapped, *args, **kwargs)
        except Exception:
            logger.exception("InlineManager callback error (data=%s)", call.data)
            await call.answer("❌ Ошибка.", show_alert=True)
