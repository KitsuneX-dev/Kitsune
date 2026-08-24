
from __future__ import annotations

import asyncio
import contextlib
import copy
import logging
import os
import time
import typing
from urllib.parse import urlparse

from .types import InlineMessage
from .utils import is_url

logger = logging.getLogger(__name__)

try:
    from aiogram.types import (
        InlineQueryResultArticle,
        InlineQueryResultAudio,
        InlineQueryResultDocument,
        InlineQueryResultGif,
        InlineQueryResultLocation,
        InlineQueryResultPhoto,
        InlineQueryResultVideo,
        InputTextMessageContent,
    )
    AIOGRAM_TYPES_AVAILABLE = True
except ImportError:
    AIOGRAM_TYPES_AVAILABLE = False

_THUMB = "https://img.icons8.com/cotton/452/moon-satellite.png"

_MAX_TTL = 60 * 60 * 24

_NO_BUTTONS_TTL = 10 * 60

_MEDIA_KEYS = ("photo", "gif", "video", "file", "audio", "location")

_ALLOWED_MIME = frozenset({
    "application/pdf",
    "application/zip",
    "application/x-zip-compressed",
    "application/gzip",
    "application/x-tar",
    "text/plain",
})

class Placeholder:
    pass
class Form:

    async def form(
        self,
        text: str,
        message: typing.Any,
        reply_markup: typing.Any = None,
        *,
        force_me: bool = False,
        always_allow: typing.Optional[typing.List[int]] = None,
        manual_security: bool = False,
        disable_security: bool = False,
        ttl: typing.Optional[int] = None,
        on_unload: typing.Optional[typing.Callable] = None,
        photo: typing.Optional[str] = None,
        gif: typing.Optional[str] = None,
        file: typing.Optional[str] = None,
        mime_type: typing.Optional[str] = None,
        video: typing.Optional[str] = None,
        location: typing.Optional[typing.Union[list, tuple]] = None,
        audio: typing.Optional[typing.Union[dict, str]] = None,
        silent: bool = False,
    ) -> typing.Union[InlineMessage, bool]:
        if reply_markup is None:
            reply_markup = []
        if always_allow is None:
            always_allow = []
        if not isinstance(text, str):
            logger.error("form: `text` должен быть str, получен %s", type(text).__name__)
            return False
        for name, value in (
            ("silent", silent),
            ("manual_security", manual_security),
            ("disable_security", disable_security),
            ("force_me", force_me),
        ):
            if not isinstance(value, bool):
                logger.error("form: `%s` должен быть bool, получен %s", name, type(value).__name__)
                return False
        if not isinstance(always_allow, (list, tuple)):
            logger.error(
                "form: `always_allow` должен быть list, получен %s",
                type(always_allow).__name__,
            )
            return False
        always_allow = [int(uid) for uid in always_allow if isinstance(uid, int)]
        if message is None:
            logger.error("form: `message` не передан")
            return False
        if not isinstance(reply_markup, (list, tuple, dict)):
            logger.error(
                "form: `reply_markup` должен быть list или dict, получен %s",
                type(reply_markup).__name__,
            )
            return False
        if ttl is not None and ttl is not False and not isinstance(ttl, int):
            logger.error("form: `ttl` должен быть int, получен %s", type(ttl).__name__)
            return False
        if isinstance(ttl, int) and ttl > _MAX_TTL:
            logger.debug("form: ttl обрезан до суток")
            ttl = _MAX_TTL
        if photo and (not isinstance(photo, str) or not is_url(photo)):
            logger.error("form: `photo` должен быть str с URL")
            return False
        if photo:
            try:
                ext = os.path.splitext(urlparse(photo).path)[1].lower()
            except Exception:
                ext = ""
            if ext in {".gif", ".mp4"}:
                gif = copy.copy(photo)
                photo = None
        if gif and (not isinstance(gif, str) or not is_url(gif)):
            logger.error("form: `gif` должен быть str с URL")
            return False
        if video and (not isinstance(video, str) or not is_url(video)):
            logger.error("form: `video` должен быть str с URL")
            return False
        if file and (not isinstance(file, str) or not is_url(file)):
            logger.error("form: `file` должен быть str с URL")
            return False
        if file and not mime_type:
            logger.error(
                "form: вместе с `file` нужен `mime_type` (например application/pdf)"
            )
            return False
        if file and mime_type not in _ALLOWED_MIME:
            logger.warning("form: нестандартный mime_type %r, Telegram может отказать", mime_type)
        if isinstance(audio, str):
            audio = {"url": audio}
        if audio and (
            not isinstance(audio, dict)
            or "url" not in audio
            or not is_url(audio["url"])
        ):
            logger.error("form: `audio` должен быть dict с ключом `url`")
            return False
        if location is not None and (
            not isinstance(location, (list, tuple))
            or len(location) != 2
            or not all(isinstance(item, (int, float)) for item in location)
        ):
            logger.error("form: `location` должен быть (широта, долгота)")
            return False
        if location is not None:
            location = (float(location[0]), float(location[1]))
        if [
            photo is not None,
            gif is not None,
            file is not None,
            video is not None,
            audio is not None,
            location is not None,
        ].count(True) > 1:
            logger.error("form: передано несколько взаимоисключающих медиа одновременно")
            return False
        text = self._sanitise_form_text(text)
        reply_markup = self._normalize_form_markup(reply_markup)
        perms_map = None if manual_security else self._find_caller_sec_map()
        base_reply_markup: typing.Any = Placeholder()
        if not reply_markup and not ttl:
            base_reply_markup = []
            reply_markup = [[{"text": "\u00ad", "data": "\u00ad"}]]
        has_interactive = any(
            ("callback" in button or "input" in button or "action" in button)
            for row in reply_markup
            for button in row
        )
        if not has_interactive and not ttl:
            ttl = _NO_BUTTONS_TTL
        unit_id = self._rand(16)
        status_message = None
        if not silent and hasattr(message, "out"):
            with contextlib.suppress(Exception):
                send = message.edit if getattr(message, "out", False) else message.respond
                status_message = await send("🦊 <b>Лиса разворачивает форму...</b>", parse_mode="html")
        origin_chat_id = self._form_chat_id(message)
        self._units[unit_id] = {
            "type": "form",
            "uid": unit_id,
            "text": text,
            "buttons": reply_markup,
            "caller": message,
            "chat": origin_chat_id,
            "chat_id": origin_chat_id,
            "message_id": None,
            "inline_message_id": "",
            "future": asyncio.Event(),
            "on_unload": on_unload if callable(on_unload) else None,
            "always_allow": always_allow,
            **({"photo": photo} if photo else {}),
            **({"gif": gif} if gif else {}),
            **({"video": video} if video else {}),
            **({"file": file, "mime_type": mime_type} if file else {}),
            **({"audio": audio} if audio else {}),
            **({"location": location} if location is not None else {}),
            **({"perms_map": perms_map} if perms_map else {}),
            **({"message": message} if hasattr(message, "out") else {}),
            **({"force_me": True} if force_me else {}),
            **({"disable_security": True} if disable_security else {}),
            **({"ttl": time.time() + ttl} if ttl else {}),
        }
        try:
            sent = await self._invoke_unit(unit_id, message)
        except Exception as exc:
            logger.exception("form: не удалось отправить unit %s", unit_id)
            await self._form_fallback_answer(message, exc)
            self._drop_unit(unit_id)
            await self._delete_status(status_message)
            return False
        unit = self._units.get(unit_id)
        if unit is None:
            await self._delete_status(status_message)
            return False
        event: asyncio.Event = unit.get("future")
        if isinstance(event, asyncio.Event):
            try:
                await asyncio.wait_for(event.wait(), timeout=30)
            except asyncio.TimeoutError:
                logger.warning("form: таймаут ожидания inline_message_id для unit %s", unit_id)
        unit = self._units.get(unit_id)
        if unit is None:
            await self._delete_status(status_message)
            return False
        unit.pop("future", None)
        error = unit.pop("_error", None)
        if error is not None:
            logger.error("form: inline-бот не смог ответить на unit %s: %s", unit_id, error)
            await self._form_fallback_answer(message, error)
            self._drop_unit(unit_id)
            await self._delete_status(status_message)
            return False
        if sent is not None:
            unit["telethon_msg"] = sent
            if getattr(sent, "id", None):
                unit["message_id"] = sent.id
            sent_chat = getattr(sent, "chat_id", None) or getattr(sent, "peer_id", None)
            if sent_chat is not None:
                unit["chat"] = sent_chat
                unit["chat_id"] = sent_chat
        await self._delete_status(status_message)
        if unit.get("ttl"):
            self._schedule_unit_unload(unit_id, unit["ttl"] - time.time())
        result = InlineMessage(
            self,
            unit_id,
            unit.get("inline_message_id", "") or "",
            telethon_msg=sent,
        )
        if not isinstance(base_reply_markup, Placeholder):
            with contextlib.suppress(Exception):
                await result.edit(text, reply_markup=base_reply_markup)
        return result
    def _sanitise_form_text(self, text: str) -> str:
        from .core import _sanitize_tg_html
        return _sanitize_tg_html(text)
    def _normalize_form_markup(self, reply_markup: typing.Any) -> list[list[dict]]:
        from .utils import normalize_rows
        if isinstance(reply_markup, dict):
            reply_markup = [[reply_markup]]
        elif isinstance(reply_markup, (list, tuple)) and any(
            isinstance(item, dict) for item in reply_markup
        ):
            reply_markup = [list(reply_markup)]
        return normalize_rows(list(reply_markup or []))
    @staticmethod
    def _form_chat_id(message: typing.Any) -> typing.Any:
        if isinstance(message, int):
            return message
        return getattr(message, "chat_id", None) or getattr(message, "peer_id", None)
    @staticmethod
    async def _delete_status(status_message: typing.Any) -> None:
        if status_message is None:
            return
        with contextlib.suppress(Exception):
            await status_message.delete()
    async def _form_fallback_answer(self, message: typing.Any, exc: typing.Any) -> None:
        err = str(exc)
        if "ChatSendInlineForbidden" in err or "CHAT_SEND_INLINE_FORBIDDEN" in err:
            text = "🚫 <b>В этом чате запрещены inline-сообщения</b>"
        else:
            text = "🚫 <b>Не удалось открыть форму.</b> Подробности в логах."
        with contextlib.suppress(Exception):
            if hasattr(message, "out"):
                send = message.edit if getattr(message, "out", False) else message.respond
                await send(text, parse_mode="html")
            elif message is not None:
                await self._client.send_message(message, text, parse_mode="html")
    async def _form_inline_handler(self, inline_query: typing.Any) -> None:
        if not AIOGRAM_TYPES_AVAILABLE:
            return
        query = inline_query.query.strip()
        unit = self._units.get(query)
        if not unit or unit.get("type") != "form":
            return
        markup = self.generate_markup(unit.get("buttons", []), unit_id=query)
        caption = unit.get("text", "") or ""
        try:
            if "photo" in unit:
                result = InlineQueryResultPhoto(
                    id=self._rand(20),
                    title="Kitsune",
                    description="Kitsune UserBot",
                    caption=caption,
                    parse_mode="HTML",
                    photo_url=unit["photo"],
                    thumbnail_url=_THUMB,
                    reply_markup=markup,
                )
            elif "gif" in unit:
                result = InlineQueryResultGif(
                    id=self._rand(20),
                    title="Kitsune",
                    caption=caption,
                    parse_mode="HTML",
                    gif_url=unit["gif"],
                    thumbnail_url=_THUMB,
                    reply_markup=markup,
                )
            elif "video" in unit:
                result = InlineQueryResultVideo(
                    id=self._rand(20),
                    title="Kitsune",
                    description="Kitsune UserBot",
                    caption=caption,
                    parse_mode="HTML",
                    video_url=unit["video"],
                    thumbnail_url=_THUMB,
                    mime_type="video/mp4",
                    reply_markup=markup,
                )
            elif "file" in unit:
                result = InlineQueryResultDocument(
                    id=self._rand(20),
                    title="Kitsune",
                    description="Kitsune UserBot",
                    caption=caption,
                    parse_mode="HTML",
                    document_url=unit["file"],
                    mime_type=unit["mime_type"],
                    reply_markup=markup,
                )
            elif "location" in unit:
                result = InlineQueryResultLocation(
                    id=self._rand(20),
                    latitude=unit["location"][0],
                    longitude=unit["location"][1],
                    title="Kitsune",
                    reply_markup=markup,
                )
            elif "audio" in unit:
                audio = unit["audio"]
                result = InlineQueryResultAudio(
                    id=self._rand(20),
                    audio_url=audio["url"],
                    caption=caption,
                    parse_mode="HTML",
                    title=audio.get("title", "Kitsune"),
                    performer=audio.get("performer"),
                    audio_duration=audio.get("duration"),
                    reply_markup=markup,
                )
            else:
                result = InlineQueryResultArticle(
                    id=self._rand(20),
                    title="Kitsune",
                    input_message_content=InputTextMessageContent(
                        message_text=caption,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    ),
                    reply_markup=markup,
                )
            await inline_query.answer([result], cache_time=0)
        except Exception as exc:
            err = str(exc).lower()
            if (
                "can't parse entities" in err
                or "unmatched end tag" in err
                or "unclosed start tag" in err
                or "unsupported start tag" in err
                or "empty attribute name" in err
                or "can't parse inline query result" in err
            ):
                from .core import _strip_all_html
                plain = _strip_all_html(caption)
                with contextlib.suppress(Exception):
                    await inline_query.answer(
                        [
                            InlineQueryResultArticle(
                                id=self._rand(20),
                                title="Kitsune",
                                input_message_content=InputTextMessageContent(
                                    message_text=plain,
                                    disable_web_page_preview=True,
                                ),
                                reply_markup=markup,
                            )
                        ],
                        cache_time=0,
                    )
                    return
            logger.exception("form: не удалось ответить на inline-запрос")
            self._fail_unit(query, exc)
            with contextlib.suppress(Exception):
                await inline_query.answer([], cache_time=0)
    def _fail_unit(self, unit_id: str, exc: typing.Any) -> None:
        unit = self._units.get(unit_id)
        if not unit:
            return
        unit["_error"] = exc
        event = unit.get("future")
        if isinstance(event, asyncio.Event):
            event.set()
        elif isinstance(event, asyncio.Future) and not event.done():
            event.set_result(None)
    def _find_caller_sec_map(self) -> typing.Optional[typing.Callable[[], int]]:
        try:
            from .. import utils
            caller = utils.find_caller()
            if not caller:
                return None
            required = getattr(caller, "_required", None)
            if required is None:
                owner = getattr(caller, "__self__", None)
                method = getattr(owner, getattr(caller, "__name__", ""), None)
                required = getattr(method, "_required", None)
            if required is None:
                return None
            return lambda: required
        except Exception:
            logger.debug("form: не удалось определить права вызвавшей команды", exc_info=True)
        return None
    def _owner_ids(self) -> list[int]:
        ids = [self._me] if self._me else []
        with contextlib.suppress(Exception):
            co_owners = self._db.get("kitsune.security", "co_owners", []) or []
            ids += [int(uid) for uid in co_owners]
        return ids
    async def _check_unit_security(
        self,
        unit: dict,
        user_id: int,
        button: typing.Optional[dict] = None,
    ) -> bool:
        button = button or {}
        if button.get("disable_security") or unit.get("disable_security"):
            return True
        allow_list = list(unit.get("always_allow") or []) + list(
            button.get("always_allow") or []
        )
        if user_id in allow_list:
            return True
        if self._me and user_id == self._me:
            return True
        if unit.get("force_me"):
            return False
        if user_id in self._owner_ids():
            return True
        perms_map = unit.get("perms_map")
        if perms_map is None:
            return False
        return await self._check_perms_map(perms_map, user_id, unit)
    async def _check_perms_map(
        self,
        perms_map: typing.Callable[[], int],
        user_id: int,
        unit: dict,
    ) -> bool:
        try:
            required = perms_map()
        except Exception:
            logger.debug("form: perms_map упал", exc_info=True)
            return False
        if not required:
            return False
        dispatcher = getattr(self._client, "_kitsune_dispatcher", None)
        security = getattr(dispatcher, "security", None) or getattr(
            dispatcher, "_security", None
        )
        if security is None:
            return False
        if isinstance(required, str):
            return user_id in self._owner_ids()
        shim = _SecurityShim(user_id, unit.get("chat") or unit.get("chat_id"))
        try:
            return bool(await security.check(shim, int(required)))
        except Exception:
            logger.debug("form: проверка прав по perms_map упала", exc_info=True)
            return False
    def _schedule_unit_unload(self, unit_id: str, delay: float) -> None:
        if delay <= 0:
            asyncio.ensure_future(self._unload_unit(unit_id))
            return
        async def _later() -> None:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            await self._unload_unit(unit_id)
        task = asyncio.ensure_future(_later())
        unit = self._units.get(unit_id)
        if unit is not None:
            unit["_ttl_task"] = task
    def _drop_unit(self, unit_id: str) -> None:
        unit = self._units.pop(unit_id, None)
        if unit is None:
            return
        task = unit.get("_ttl_task")
        if task is not None and not task.done():
            task.cancel()
        for cb_id in [
            cb for cb, uid in getattr(self, "_callback_units", {}).items() if uid == unit_id
        ]:
            self._callback_units.pop(cb_id, None)
            self._callbacks.pop(cb_id, None)
        btn_call_data = unit.get("btn_call_data")
        if btn_call_data:
            self._custom_map.pop(btn_call_data, None)
    async def _unload_unit(self, unit_id: str) -> bool:
        unit = self._units.get(unit_id)
        if unit is None:
            return False
        on_unload = unit.get("on_unload")
        self._drop_unit(unit_id)
        if callable(on_unload):
            try:
                result = on_unload()
                if asyncio.iscoroutine(result) or isinstance(result, asyncio.Future):
                    await result
            except Exception:
                logger.exception("form: on_unload упал для unit %s", unit_id)
        return True
class _SecurityShim:

    __slots__ = ("sender_id", "chat_id")

    def __init__(self, sender_id: int, chat_id: typing.Any) -> None:
        self.sender_id = sender_id
        self.chat_id = chat_id
