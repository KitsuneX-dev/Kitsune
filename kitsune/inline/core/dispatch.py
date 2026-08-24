
from __future__ import annotations

import asyncio
import contextlib
import time
import typing
import uuid

from ..types import InlineCall
from .common import (
    AIOGRAM_AVAILABLE,
    _INPUT_MARKER,
    _UNIT_TTL,
    logger,
    warn_no_aiogram_once,
)
from .markup import _InlineTarget
from .sanitize import _sanitize_tg_html, _strip_all_html, _strip_tg_emoji

if AIOGRAM_AVAILABLE:
    from .common import (
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        InlineQueryResultArticle,
        InlineQueryResultGif,
        InlineQueryResultVideo,
        InputTextMessageContent,
    )

if typing.TYPE_CHECKING:  
    from .common import AiogramMessage, ChosenInlineResult, InlineQuery

class _DispatchMixin:
    async def _delete_unit_message(
        self,
        call: typing.Any = None,
        unit_id: str | None = None,
    ) -> None:
        unit = self._units.get(unit_id or "", {})
        chat_id = unit.get("chat") or unit.get("chat_id")
        message_id = unit.get("message_id")
        deleted = False
        if chat_id and message_id:
            try:
                await self._client.delete_messages(chat_id, [message_id])
                deleted = True
            except Exception:
                logger.debug("_delete_unit_message: Telethon delete failed", exc_info=True)
        if not deleted and self._bot:
            iid = getattr(call, "inline_message_id", None)
            try:
                if iid:
                    await self._bot.edit_message_text(
                        inline_message_id=iid,
                        text="🗑 <i>Закрыто</i>",
                        parse_mode="HTML",
                    )
                    deleted = True
                elif getattr(call, "chat_id", None) and getattr(call, "message_id", None):
                    await self._bot.delete_message(
                        chat_id=call.chat_id, message_id=call.message_id,
                    )
                    deleted = True
            except Exception:
                logger.debug("_delete_unit_message: bot fallback failed", exc_info=True)
        if call is not None:
            with contextlib.suppress(Exception):
                await call.answer("")
    async def _edit_unit(
        self,
        text: str | None = None,
        reply_markup: typing.Any = None,
        *,
        unit_id: str | None = None,
        inline_message_id: str | None = None,
        chat_id: int | None = None,
        message_id: int | None = None,
        **kwargs: typing.Any,
    ) -> typing.Any:
        unit = self._units.get(unit_id or "", {})
        iid = inline_message_id or unit.get("inline_message_id") or ""
        if not unit and iid:
            unit = self._units.get(f"iid:{iid}", {})
        if text is not None:
            safe = _sanitize_tg_html(text)
            if unit:
                unit["text"] = safe
        else:
            safe = unit.get("text", "") or ""
        if reply_markup is not None and unit:
            unit["buttons"] = self._normalize_form_markup(reply_markup)
        if reply_markup is not None and not unit:
            buttons = self._normalize_form_markup(reply_markup)
        else:
            buttons = unit.get("buttons", []) if unit else (reply_markup or [])
        target = _InlineTarget(iid, chat_id, message_id)
        await self.edit(target, safe, buttons, inline_message_id=iid or None)
        return True
    async def edit(
        self,
        call_or_msg: typing.Any,
        text: str,
        reply_markup: list | None = None,
        inline_message_id: str | None = None,
    ) -> None:
        if not AIOGRAM_AVAILABLE:
            warn_no_aiogram_once(
                "InlineManager.edit()",
                "inline messages cannot be edited, edit() is a no-op",
            )
            return
        if not self._bot:
            return
        text = _sanitize_tg_html(text)
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
            elif (
                callable(getattr(call_or_msg, "_edit", None))
                and not getattr(call_or_msg._edit, "_kitsune_unit_edit", False)
            ):
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
            elif (
                getattr(call_or_msg, "chat_id", None)
                and getattr(call_or_msg, "message_id", None)
            ):
                await _try_text_then_caption(
                    _chat=call_or_msg.chat_id, _msg=call_or_msg.message_id,
                )
            elif _cb_chat_id and _cb_msg_id:
                await _try_text_then_caption(_chat=_cb_chat_id, _msg=_cb_msg_id)
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


        if self._inline_handlers:
            from_uid = getattr(query.from_user, "id", None)
            for handler, only_own in list(self._inline_handlers):
                if only_own and from_uid != self._client.tg_id:
                    continue
                try:
                    result = await handler(q, query)
                    if result is True:
                        return
                except Exception:
                    logger.exception(
                        "InlineManager: inline_handler %r failed (query=%r)",
                        handler, q,
                    )

        try:
            if await self._handle_query_gallery(query):
                return
        except Exception:
            logger.exception("InlineManager: _handle_query_gallery failed")

        unit_by_id = self._units.get(q)
        if unit_by_id is not None:
            u_type = unit_by_id.get("type")
            if u_type == "gallery":
                await self._gallery_inline_handler(query)
                return
            if u_type == "list":
                await self._list_inline_handler(query, q)
                return
            if u_type == "form":
                await self._form_inline_handler(query)
                return

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
        raw_text = unit.get("text", "") or ""
        safe_text = _sanitize_tg_html(raw_text)
        unit["text"] = safe_text
        async def _send(_payload_text: str, _parse_mode: str | None):
            if "gif" in unit:
                await query.answer(
                    results=[
                        InlineQueryResultGif(
                            id=str(uuid.uuid4()),
                            gif_url=unit["gif"],
                            thumbnail_url="https://img.icons8.com/cotton/452/moon-satellite.png",
                            title="Kitsune",
                            caption=_payload_text,
                            parse_mode=_parse_mode,
                            reply_markup=markup,
                        )
                    ],
                    cache_time=0,
                )
                return
            if "video" in unit:
                await query.answer(
                    results=[
                        InlineQueryResultVideo(
                            id=str(uuid.uuid4()),
                            title="Kitsune",
                            description="Kitsune UserBot",
                            caption=_payload_text,
                            parse_mode=_parse_mode,
                            video_url=unit["video"],
                            thumbnail_url="https://img.icons8.com/cotton/452/moon-satellite.png",
                            mime_type="video/mp4",
                            reply_markup=markup,
                        )
                    ],
                    cache_time=0,
                )
                return
            await query.answer(
                results=[
                    InlineQueryResultArticle(
                        id=str(uuid.uuid4()),
                        title="Kitsune",
                        input_message_content=InputTextMessageContent(
                            message_text=_payload_text,
                            parse_mode=_parse_mode,
                            disable_web_page_preview=True,
                        ),
                        reply_markup=markup,
                    )
                ],
                cache_time=0,
            )
        try:
            await _send(safe_text, "HTML")
        except Exception as exc_html:
            err = str(exc_html).lower()
            if (
                "can't parse entities" in err
                or "unmatched end tag" in err
                or "unclosed start tag" in err
                or "unsupported start tag" in err
                or "empty attribute name" in err
                or "can't parse inline query result" in err
            ):
                stripped = _strip_all_html(raw_text)
                try:
                    await _send(stripped, None)
                    return
                except Exception:
                    logger.exception("InlineManager._on_inline_query: plain-text fallback failed")
                    try:
                        await query.answer([], cache_time=0)
                    except Exception:
                        pass
                    return
            logger.exception("InlineManager._on_inline_query failed")
            try:
                await query.answer([], cache_time=0)
            except Exception:
                pass
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
            if unit_id != q or "future" not in unit:
                continue
            fut = unit["future"]
            unit["inline_message_id"] = result.inline_message_id
            if isinstance(fut, asyncio.Event):
                fut.set()
            elif isinstance(fut, asyncio.Future) and not fut.done():
                fut.set_result(result.inline_message_id)
            else:
                continue
            logger.debug(
                "unit %s: saved inline_message_id=%s", unit_id, result.inline_message_id,
            )
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
                        chat_id=chat_id_for_wipe or 0,
                        message_id=0,
                        data="",
                        _answer=self._noop_answer,
                        _edit=None,
                        inline_message_id=original_iid or "",
                        unit_id=unit_id,
                        _manager=self,
                    )
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
        try:
            await self._handle_pm_message(message)
        except Exception:
            logger.exception("InlineManager._on_message failed")
