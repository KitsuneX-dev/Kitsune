
from __future__ import annotations

import asyncio
import contextlib
import html as _html
import inspect
import io
import json
import logging
import os
import platform as _platform
import random
import shlex
import sys
import typing

from .args import get_args, get_args_raw, get_args_html, split_args
from .entity import (
    get_display_name, get_entity_id, get_entity_url, mention_html,
    resolve_entity, is_bot, is_channel, is_group,
)
from .git import (
    get_repo_path, get_current_commit, get_current_branch,
    get_remote_commit, has_updates, get_changelog,
)
from .platform import (
    is_docker, is_termux, is_userland, is_mobile, is_heroku,
    _detect_proot,
    get_platform_name, get_python_version, get_arch,
    get_named_platform_label, get_os_pretty_name, get_kernel_release,
    get_hostname, get_username, get_cpu_model_cores, get_run_environment,
)
from .tg_html import parse_html_with_tg_emoji

logger = logging.getLogger(__name__)
_logger = logger


def detect_environment() -> dict[str, bool]:
    is_wsl = False
    with contextlib.suppress(Exception):
        if "microsoft-standard" in _platform.uname().release.lower():
            is_wsl = True
    return {
        "termux": is_termux(),
        "docker": is_docker(),
        "heroku": is_heroku(),
        "railway": "RAILWAY" in os.environ or "RAILWAY_ENVIRONMENT" in os.environ,
        "codespaces": "CODESPACES" in os.environ,
        "wsl": is_wsl,
        "linux": _platform.system() == "Linux",
        "windows": _platform.system() == "Windows",
        "macos": _platform.system() == "Darwin",
    }


ENV = detect_environment()

IS_TERMUX = ENV["termux"]
IS_DOCKER = ENV["docker"]
IS_HEROKU = ENV["heroku"]
IS_RAILWAY = ENV["railway"]
IS_WSL = ENV["wsl"]
IS_LINUX = ENV["linux"]
IS_WINDOWS = ENV["windows"]
IS_MACOS = ENV["macos"]


def escape_html(text: typing.Any) -> str:
    return _html.escape(str(text))


def chunks(text: str, size: int) -> list[str]:
    return [text[i: i + size] for i in range(0, len(text), size)]


def array_sum(array: typing.Optional[list[list]]) -> list:
    result: list = []
    for item in array or []:
        result += item
    return result


def truncate(text: str, max_len: int = 512, suffix: str = "…") -> str:
    return text if len(text) <= max_len else text[: max_len - len(suffix)] + suffix


def rand(size: int) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(random.choice(alphabet) for _ in range(size))


async def run_sync(func: typing.Callable, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


def is_serializable(value: typing.Any) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def get_chat_id(message: typing.Any) -> typing.Optional[int]:
    if isinstance(message, int):
        return message
    peer = getattr(message, "peer_id", None)
    if peer is not None:
        chat_id = (
            getattr(peer, "channel_id", None)
            or getattr(peer, "chat_id", None)
            or getattr(peer, "user_id", None)
        )
        if chat_id:
            return chat_id
    chat = getattr(message, "chat", None)
    if chat is not None:
        return getattr(chat, "id", None)
    return getattr(message, "chat_id", None)


_FIND_CALLER_INTERNAL = frozenset(
    {"Loader", "CommandDispatcher", "SecurityManager", "DatabaseManager"}
)


def iter_raw_frames(depth: int = 1) -> typing.Iterator[typing.Any]:
    try:
        frame = sys._getframe(depth + 1)
    except (ValueError, AttributeError):
        return
    while frame is not None:
        yield frame
        frame = frame.f_back


def find_caller(
    stack: typing.Iterable[inspect.FrameInfo] | None = None,
) -> typing.Callable | None:
    if stack is None:
        for frame in iter_raw_frames(1):
            self_ = frame.f_locals.get("self")
            if self_ is None:
                continue
            if type(self_).__name__ in _FIND_CALLER_INTERNAL:
                continue
            method = getattr(self_, frame.f_code.co_name, None)
            if callable(method):
                return method
        return None
    for frame_info in stack:
        frame = getattr(frame_info, "frame", None)
        if frame is None:
            continue
        self_ = frame.f_locals.get("self")
        if self_ is None:
            continue
        if type(self_).__name__ in _FIND_CALLER_INTERNAL:
            continue
        method = getattr(self_, getattr(frame_info, "function", ""), None)
        if callable(method):
            return method
    return None


async def auto_delete(message: typing.Any, delay: float | None = None) -> None:
    if delay is None:
        try:
            client = getattr(message, "client", None)
            db = getattr(client, "_kitsune_db", None)
            delay = float(db.get("kitsune.core", "auto_delete_delay", 0)) if db else 0.0
        except Exception:
            delay = 0.0
    if not delay:
        return
    await asyncio.sleep(delay)
    with contextlib.suppress(Exception):
        await message.delete()


def progress_bar(
    current: typing.Union[int, float],
    total: typing.Union[int, float],
    width: int = 12,
) -> str:
    pct = 0.0 if total <= 0 else max(0.0, min(1.0, current / total))
    filled = round(pct * width)
    return "█" * filled + "░" * (width - filled) + f"  {int(pct * 100)}%"


def make_progress_bar(current: int, total: int, width: int = 10) -> str:
    filled = int(width * current / max(total, 1))
    return "█" * filled + "░" * (width - filled) + f" {current}/{total}"


class ProgressMessage:

    def __init__(
        self,
        event: typing.Any,
        text: str,
        total: typing.Union[int, float] = 100,
        width: int = 12,
        update_every: float = 1.5,
    ) -> None:
        self._event = event
        self._text = text
        self._total = total
        self._width = width
        self._update_every = update_every
        self._step: float = 0
        self._msg: typing.Any = None
        self._last_update: float = 0.0

    async def __aenter__(self) -> "ProgressMessage":
        self._msg = await self._event.reply(self._text, parse_mode="html")
        with contextlib.suppress(RuntimeError):
            self._last_update = asyncio.get_event_loop().time()
        return self

    async def __aexit__(self, *_: object) -> None:
        pass

    async def update(
        self,
        step: typing.Union[int, float],
        text: str | None = None,
        *,
        force: bool = False,
    ) -> None:
        self._step = step
        now = asyncio.get_event_loop().time()
        if not force and (now - self._last_update) < self._update_every:
            return
        self._last_update = now
        bar = make_progress_bar(int(step), int(self._total))
        with contextlib.suppress(Exception):
            await self._msg.edit(f"{text or self._text}\n{bar}", parse_mode="html")

    async def done(self, text: str) -> None:
        with contextlib.suppress(Exception):
            await self._msg.edit(text, parse_mode="html")


async def answer(
    message: typing.Any,
    response: typing.Union[str, bytes, io.IOBase],
    *,
    parse_mode: str = "HTML",
    link_preview: bool = False,
    reply_markup: typing.Any = None,
    **kwargs: typing.Any,
) -> typing.Any:
    if isinstance(message, list) and message:
        message = message[0]

    if isinstance(message, int):
        client = kwargs.pop("client", None)
        if client is None:
            raise ValueError("answer: передан int message без client=")
        return await client.send_message(
            message, response, parse_mode=parse_mode, link_preview=link_preview, **kwargs
        )

    def _is_own() -> bool:
        return bool(
            getattr(message, "out", False)
            and not getattr(message, "via_bot_id", None)
            and not getattr(message, "fwd_from", None)
        )

    if isinstance(response, str) and len(response.encode("utf-16le")) // 2 > 4096:
        parts: list[str] = []
        try:
            from telethon.extensions.html import parse as _tl_parse
            text, entities = _tl_parse(response)
            parts = list(smart_split(text, entities, length=4096))
        except Exception:
            logger.debug("answer: smart_split не сработал", exc_info=True)

        if len(parts) > 1:
            inline = getattr(getattr(message, "client", None), "inline", None)
            if inline is not None and hasattr(inline, "list"):
                try:
                    result = await inline.list(message, parts, silent=True)
                    if result is not False and result is not None:
                        return result
                except Exception:
                    logger.debug("answer: inline-список не удался", exc_info=True)

            try:
                first_fn = message.edit if _is_own() else message.respond
                result = await first_fn(parts[0], parse_mode="html", link_preview=link_preview)
                for part in parts[1:]:
                    await message.respond(part, parse_mode="html", link_preview=False)
                return result
            except Exception:
                logger.debug("answer: постраничная отправка не удалась", exc_info=True)

        try:
            buf = io.BytesIO(response.encode("utf-8"))
            buf.name = "command_result.txt"
            result = await answer_file(
                message,
                buf,
                "📄 Результат слишком длинный для сообщения",
                **{k: v for k, v in kwargs.items() if k == "reply_to"},
            )
            return result
        except Exception:
            logger.debug("answer: отправка файлом не удалась, обрезаем текст", exc_info=True)
            response = response[:4090] + "…"

    if _is_own():
        try:
            return await message.edit(
                response, parse_mode=parse_mode, link_preview=link_preview, **kwargs
            )
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return message
            logger.debug("answer: edit failed, falling back to respond", exc_info=True)

    if "reply_to" not in kwargs:
        reply_to = getattr(message, "reply_to_msg_id", None)
        if reply_to:
            kwargs["reply_to"] = reply_to
    return await message.respond(
        response, parse_mode=parse_mode, link_preview=link_preview, **kwargs
    )


async def answer_file(
    message: typing.Any,
    file: typing.Union[str, bytes, io.IOBase],
    caption: typing.Optional[str] = None,
    *,
    force_document: bool = False,
    **kwargs: typing.Any,
) -> typing.Any:
    client = getattr(message, "client", None)
    peer = getattr(message, "peer_id", None) or getattr(message, "chat_id", None)
    if peer is None or client is None:
        raise ValueError("answer_file: не удалось определить peer/client из message")
    if "reply_to" not in kwargs:
        reply_to = getattr(message, "reply_to_msg_id", None)
        if reply_to:
            kwargs["reply_to"] = reply_to
    if isinstance(file, bytes):
        file = io.BytesIO(file)

    try:
        try:
            from ..hydro_media import send_file as _hydro_send
            result = await _hydro_send(
                client, peer, file,
                caption=caption or "",
                reply_to=kwargs.get("reply_to"),
            )
        except ImportError:
            result = await client.send_file(
                peer, file, caption=caption, force_document=force_document, **kwargs
            )
    except Exception:
        if caption:
            logger.warning("answer_file: отправка файла не удалась, шлём текст", exc_info=True)
            return await answer(message, caption)
        raise

    if getattr(message, "out", False):
        with contextlib.suppress(Exception):
            await message.delete()
    return result


def _copy_tl_entity(entity, **kwargs):
    d = entity.to_dict()
    d.pop("_", None)
    d.update(kwargs)
    return entity.__class__(**d)


def smart_split(
    text: str,
    entities: list,
    length: int = 4096,
    split_on: tuple = ("\n", " "),
    min_length: int = 1,
):
    try:
        import grapheme as _grapheme
        _safe_split_index = _grapheme.safe_split_index
    except ImportError:
        def _safe_split_index(s, idx):
            return min(idx, len(s))
    try:
        from telethon.extensions.html import unparse as _unparse
    except ImportError:
        def _unparse(text, entities):
            return text

    encoded = text.encode("utf-16le")
    pending_entities = list(entities)
    text_offset = 0
    bytes_offset = 0
    text_length = len(text)
    bytes_length = len(encoded)
    while text_offset < text_length:
        if bytes_offset + length * 2 >= bytes_length:
            yield _unparse(
                text[text_offset:],
                sorted(pending_entities, key=lambda x: (x.offset, -x.length)),
            )
            break
        codepoint_count = len(
            encoded[bytes_offset: bytes_offset + length * 2].decode(
                "utf-16le", errors="ignore",
            )
        )
        search_index = -1
        for sep in split_on:
            si = text.rfind(sep, text_offset + min_length, text_offset + codepoint_count)
            if si != -1:
                search_index = si
                break
        if search_index == -1:
            search_index = text_offset + codepoint_count
        split_index = _safe_split_index(text, search_index)
        split_offset_utf16 = len(text[text_offset:split_index].encode("utf-16le")) // 2
        exclude = 0
        while (
            split_index + exclude < text_length
            and text[split_index + exclude] in split_on
        ):
            exclude += 1
        current_entities = []
        entities_copy = pending_entities.copy()
        pending_entities = []
        for entity in entities_copy:
            eo, el = entity.offset, entity.length
            if eo < split_offset_utf16 and eo + el > split_offset_utf16 + exclude:
                current_entities.append(_copy_tl_entity(entity, length=split_offset_utf16 - eo))
                pending_entities.append(_copy_tl_entity(entity, offset=0, length=eo + el - split_offset_utf16 - exclude))
            elif eo < split_offset_utf16 < eo + el:
                current_entities.append(_copy_tl_entity(entity, length=split_offset_utf16 - eo))
            elif eo < split_offset_utf16:
                current_entities.append(entity)
            elif eo + el > split_offset_utf16 + exclude > eo:
                pending_entities.append(_copy_tl_entity(entity, offset=0, length=eo + el - split_offset_utf16 - exclude))
            elif eo + el > split_offset_utf16 + exclude:
                pending_entities.append(_copy_tl_entity(entity, offset=eo - split_offset_utf16 - exclude))
        current_text = text[text_offset:split_index]
        yield _unparse(
            current_text,
            sorted(current_entities, key=lambda x: (x.offset, -x.length)),
        )
        text_offset = split_index + exclude
        bytes_offset += len(current_text.encode("utf-16le"))


_ASSET_CHANNEL_CACHE_OWNER = "kitsune.asset_channels"


def _asset_cache_get(db, title: str):
    if db is None:
        return None
    try:
        val = db.get(_ASSET_CHANNEL_CACHE_OWNER, title, None)
        if isinstance(val, int) and val:
            return val
    except Exception:
        pass
    return None


def _asset_cache_set(db, title: str, channel_id: int) -> None:
    if db is None or not channel_id:
        return
    try:
        db.set_sync(_ASSET_CHANNEL_CACHE_OWNER, title, int(channel_id))
    except Exception:
        try:
            db._data.setdefault(_ASSET_CHANNEL_CACHE_OWNER, {})[title] = int(channel_id)
        except Exception:
            pass


def _asset_cache_drop(db, title: str) -> None:
    if db is None:
        return
    try:
        db.set_sync(_ASSET_CHANNEL_CACHE_OWNER, title, None)
    except Exception:
        try:
            sub = db._data.get(_ASSET_CHANNEL_CACHE_OWNER)
            if sub and title in sub:
                sub.pop(title, None)
        except Exception:
            pass


async def asset_channel(
    client,
    title: str = "Kitsune Assets",
    *,
    silent: bool = True,
    description: str = "",
    archive: bool = False,
    megagroup: bool = False,
    db=None,
):
    try:
        from telethon.tl.functions.channels import CreateChannelRequest

        cached_id = _asset_cache_get(db, title)
        if cached_id:
            try:
                ent = await client.get_entity(cached_id)
                if ent is not None:
                    ent_title = getattr(ent, "title", None)
                    if ent_title and ent_title != title:
                        logger.debug(
                            "asset_channel: cached id=%s имеет другой title %r (ожидался %r) — принимаем",
                            cached_id, ent_title, title,
                        )
                    return getattr(ent, "id", cached_id), False
            except Exception as _e:
                logger.debug("asset_channel: cached id=%s невалиден (%s) — ищем заново", cached_id, _e)
                _asset_cache_drop(db, title)

        try:
            async for dialog in client.iter_dialogs():
                if (dialog.is_channel or dialog.is_group) and dialog.title == title:
                    cid = dialog.entity.id
                    _asset_cache_set(db, title, cid)
                    return cid, False
        except Exception as _e:
            logger.debug("asset_channel: iter_dialogs ошибка: %s", _e)

        result = await client(CreateChannelRequest(
            title=title,
            about=description or "Kitsune internal asset storage",
            megagroup=megagroup,
        ))
        channel = result.chats[0]
        if archive:
            with contextlib.suppress(Exception):
                from telethon.tl.functions.folders import EditPeerFoldersRequest
                from telethon.tl.types import InputFolderPeer, InputChannel
                await client(EditPeerFoldersRequest(folder_peers=[
                    InputFolderPeer(
                        peer=InputChannel(channel.id, channel.access_hash),
                        folder_id=1,
                    )
                ]))
        _asset_cache_set(db, title, channel.id)
        return channel.id, True
    except Exception as e:
        logger.warning("asset_channel: не удалось создать канал: %s", e)
        return None, False


_KITSUNE_FOLDER_TITLE = "🦊 Kitsune"
_KITSUNE_FOLDER_TITLE_LEGACY = ("Kitsune",)
_KITSUNE_ASSET_TITLES = ("KitsuneBackup", "Kitsune-logs", "kitsune-assets", "Kitsune Assets")


def _dialog_filter_title(title: str) -> typing.Any:
    try:
        from telethon.tl.types import TextWithEntities
        return TextWithEntities(text=title, entities=[])
    except ImportError:
        return title


def _normalize_username(value: typing.Any) -> typing.Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip().lstrip("@").lower()
    return value or None


def _peer_key(peer: typing.Any) -> typing.Any:
    for attr in ("channel_id", "user_id", "chat_id"):
        value = getattr(peer, attr, None)
        if value:
            return (attr, value)
    return None


def _notifier_bot_username(db: typing.Any) -> typing.Optional[str]:
    if db is None:
        return None
    try:
        from ..modules.notifier import _DB_KEY as _NOTIFIER_DB_KEY
        return _normalize_username(db.get(_NOTIFIER_DB_KEY, "bot_username", None))
    except Exception:
        return None


async def ensure_kitsune_folder(client: typing.Any, db: typing.Any = None) -> None:
    try:
        from telethon.tl.functions.messages import (
            GetDialogFiltersRequest,
            UpdateDialogFilterRequest,
        )
        from telethon.tl.types import DialogFilter

        bot_username = _notifier_bot_username(db)

        peer_inputs = []
        async for dialog in client.iter_dialogs():
            matched = dialog.title in _KITSUNE_ASSET_TITLES
            if not matched and bot_username:
                entity_username = _normalize_username(
                    getattr(getattr(dialog, "entity", None), "username", None)
                )
                matched = entity_username is not None and entity_username == bot_username
            if matched:
                with contextlib.suppress(Exception):
                    peer_inputs.append(await client.get_input_entity(dialog.id))
        if not peer_inputs:
            logger.debug("ensure_kitsune_folder: служебные каналы ещё не созданы")
            return

        existing_filters = await client(GetDialogFiltersRequest())
        existing: typing.Any = None
        legacy_filters: typing.List[typing.Any] = []
        next_free_id: int = 2
        for f in getattr(existing_filters, "filters", []):
            f_title = getattr(f, "title", None)
            f_title_text = getattr(f_title, "text", f_title)
            f_id = getattr(f, "id", None)
            if f_id is not None:
                next_free_id = max(next_free_id, f_id + 1)
            if f_title_text == _KITSUNE_FOLDER_TITLE:
                if existing is None:
                    existing = f
            elif f_title_text in _KITSUNE_FOLDER_TITLE_LEGACY and f_id is not None:
                legacy_filters.append(f)

        if existing is None and legacy_filters:
            existing = legacy_filters.pop(0)
            logger.info(
                "ensure_kitsune_folder: найдена папка со старым названием '%s' (id=%s) — переименовываю в '%s'",
                getattr(getattr(existing, "title", None), "text", getattr(existing, "title", None)),
                getattr(existing, "id", None),
                _KITSUNE_FOLDER_TITLE,
            )

        existing_id = getattr(existing, "id", None) if existing is not None else None
        if existing_id is None:
            existing_id = next_free_id

        our_keys = {_peer_key(p) for p in peer_inputs}
        our_keys.discard(None)
        for legacy in legacy_filters:
            legacy_id = getattr(legacy, "id", None)
            if legacy_id is None or legacy_id == existing_id:
                continue
            legacy_peers = list(getattr(legacy, "include_peers", []))
            foreign = [p for p in legacy_peers if _peer_key(p) not in our_keys]
            if foreign:
                logger.warning(
                    "ensure_kitsune_folder: найдена дублирующая папка '%s' (id=%s) с %d посторонними чатами — "
                    "удалите её вручную, автоматически не трогаю",
                    _KITSUNE_FOLDER_TITLE_LEGACY[0], legacy_id, len(foreign),
                )
                continue
            try:
                await client(UpdateDialogFilterRequest(id=legacy_id, filter=None))
                logger.info(
                    "ensure_kitsune_folder: удалена устаревшая дублирующая папка (id=%s)", legacy_id
                )
            except Exception as del_exc:
                logger.warning(
                    "ensure_kitsune_folder: не удалось удалить дублирующую папку (id=%s): %s",
                    legacy_id, del_exc,
                )

        include_peers = list(getattr(existing, "include_peers", [])) if existing is not None else []
        if existing is not None:
            known = {_peer_key(p) for p in include_peers}
            known.discard(None)
            for p in peer_inputs:
                key = _peer_key(p)
                if key is not None and key not in known:
                    include_peers.append(p)
                    known.add(key)
        else:
            include_peers = peer_inputs

        new_filter = DialogFilter(
            id=existing_id,
            title=_dialog_filter_title(_KITSUNE_FOLDER_TITLE),
            pinned_peers=[],
            include_peers=include_peers,
            exclude_peers=[],
            contacts=False,
            non_contacts=False,
            groups=False,
            broadcasts=False,
            bots=False,
            exclude_muted=False,
            exclude_read=False,
            exclude_archived=False,
        )
        await client(UpdateDialogFilterRequest(id=existing_id, filter=new_filter))
        logger.info(
            "ensure_kitsune_folder: папка '%s' обновлена (%d чатов)",
            _KITSUNE_FOLDER_TITLE, len(include_peers),
        )
    except Exception as exc:
        logger.debug("ensure_kitsune_folder: не удалось обновить папку — %s", exc, exc_info=True)


def censor(
    obj: typing.Any,
    to_censor: typing.Optional[typing.Iterable[str]] = None,
    replace_with: str = "redacted_{count}_chars",
) -> typing.Any:
    if to_censor is None:
        to_censor = ("phone", "session", "auth_key", "token", "bot_token", "api_hash")
    try:
        attrs = vars(obj)
    except TypeError:
        return obj
    for k, v in list(attrs.items()):
        if k in to_censor and v is not None:
            with contextlib.suppress(Exception):
                setattr(obj, k, replace_with.format(count=len(str(v))))
        elif k and k[0] != "_" and hasattr(v, "__dict__"):
            with contextlib.suppress(Exception):
                setattr(obj, k, censor(v, to_censor, replace_with))
    return obj


def relocate_entities(
    entities: typing.Optional[list],
    offset: int,
    text: typing.Optional[str] = None,
) -> typing.Optional[list]:
    if not entities:
        return entities
    length = len(text) if text is not None else 0
    for ent in entities.copy():
        ent.offset += offset
        if ent.offset < 0:
            ent.length += ent.offset
            ent.offset = 0
        if text is not None and ent.offset + ent.length > length:
            ent.length = length - ent.offset
        if ent.length <= 0:
            entities.remove(ent)
    return entities


def remove_html(text: typing.Any, escape: bool = False, keep_emojis: bool = False) -> str:
    pattern = (
        r"(<\/?a.*?>|<\/?b>|<\/?i>|<\/?u>|<\/?strong>|<\/?em>|<\/?code>|<\/?strike>|<\/?del>|<\/?pre.*?>)"
        if keep_emojis
        else r"(<\/?a.*?>|<\/?b>|<\/?i>|<\/?u>|<\/?strong>|<\/?em>|<\/?code>|<\/?strike>|<\/?del>|<\/?pre.*?>|<\/?emoji.*?>)"
    )
    import re as _re
    cleaned = _re.sub(pattern, "", str(text))
    return escape_html(cleaned) if escape else cleaned


def validate_html(html: str) -> str:
    try:
        from telethon.extensions.html import parse as _parse, unparse as _unparse
        text, entities = _parse(str(html))
        return _unparse(escape_html(text), entities)
    except Exception:
        logger.debug("validate_html: не удалось распарсить, удаляю теги", exc_info=True)
        return remove_html(html)


def mime_type(message: typing.Any) -> str:
    media = getattr(message, "media", None)
    if not media:
        return ""
    document = getattr(media, "document", None)
    if not document:
        return ""
    return getattr(document, "mime_type", "") or ""


def get_link(user: typing.Any, /) -> str:
    from telethon.tl.types import User
    if isinstance(user, User):
        return f"tg://user?id={user.id}"
    username = getattr(user, "username", None)
    return f"tg://resolve?domain={username}" if username else ""


async def get_message_link(
    message: typing.Any,
    chat: typing.Any = None,
) -> str:
    if getattr(message, "is_private", False):
        return f"tg://openmessage?user_id={get_chat_id(message)}&message_id={message.id}"

    if not chat and not (chat := getattr(message, "chat", None)):
        chat = await message.get_chat()

    reply_to = getattr(message, "reply_to", None)
    topic_affix = (
        f"?topic={reply_to.reply_to_msg_id}"
        if getattr(reply_to, "forum_topic", False)
        else ""
    )
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{message.id}{topic_affix}"
    return f"https://t.me/c/{getattr(chat, 'id', 0)}/{message.id}{topic_affix}"


def get_topic(message: typing.Any) -> typing.Optional[int]:
    reply_to = getattr(message, "reply_to", None)
    if reply_to is not None and getattr(reply_to, "forum_topic", False):
        return getattr(reply_to, "reply_to_top_id", None) or getattr(
            reply_to, "reply_to_msg_id", None
        )
    form = getattr(message, "form", None)
    if isinstance(form, dict):
        return form.get("top_msg_id")
    return None


async def get_user(message: typing.Any) -> typing.Any:
    from telethon.tl.types import PeerUser, PeerChannel, PeerChat
    try:
        return await message.get_sender()
    except ValueError:
        logger.debug("get_user: отправителя нет в кэше, ищу...")

    peer_id = getattr(message, "peer_id", None)
    if isinstance(peer_id, PeerUser):
        await message.client.get_dialogs()
        return await message.get_sender()

    if isinstance(peer_id, (PeerChannel, PeerChat)):
        async for user in message.client.iter_participants(peer_id, aggressive=True):
            if user.id == message.sender_id:
                return user
        logger.error("get_user: отправитель не найден в группе")
        return None

    logger.error("get_user: peer_id не является user/chat/channel")
    return None


async def get_target(message: typing.Any, arg_no: int = 0) -> typing.Optional[int]:
    from telethon.tl.types import MessageEntityMentionName, User

    entities = getattr(message, "entities", None) or []
    mentions = [e for e in entities if isinstance(e, MessageEntityMentionName)]
    if mentions:
        return sorted(mentions, key=lambda x: x.offset)[0].user_id

    args = get_args(message)
    if len(args) > arg_no:
        user: typing.Any = args[arg_no]
        if isinstance(user, str) and user.isdigit():
            user = int(user)
    elif getattr(message, "is_reply", False):
        reply = await message.get_reply_message()
        return getattr(reply, "sender_id", None)
    elif hasattr(getattr(message, "peer_id", None), "user_id"):
        user = message.peer_id.user_id
    else:
        return None

    try:
        entity = await message.client.get_entity(user)
    except (ValueError, TypeError):
        return None
    return entity.id if isinstance(entity, User) else None


async def send_reaction(
    client: typing.Any,
    message: typing.Any,
    emoji: typing.Union[int, str],
) -> None:
    from telethon.tl.functions.messages import SendReactionRequest
    from telethon.tl.types import ReactionCustomEmoji, ReactionEmoji
    try:
        if isinstance(emoji, int):
            me = await client.get_me()
            if not getattr(me, "premium", False):
                return
            reaction: typing.Any = [ReactionCustomEmoji(document_id=emoji)]
        elif isinstance(emoji, str):
            reaction = [ReactionEmoji(emoticon=emoji)]
        else:
            return
        await client(
            SendReactionRequest(
                peer=message.chat_id,
                msg_id=message.id,
                reaction=reaction,
            )
        )
    except Exception as exc:
        logger.error("send_reaction: не удалось поставить реакцию: %s", exc)


async def dnd(client: typing.Any, peer: typing.Any, archive: bool = True) -> bool:
    from telethon.tl.functions.account import UpdateNotifySettingsRequest
    from telethon.tl.types import InputPeerNotifySettings
    try:
        await client(
            UpdateNotifySettingsRequest(
                peer=peer,
                settings=InputPeerNotifySettings(
                    show_previews=False,
                    silent=True,
                    mute_until=2**31 - 1,
                ),
            )
        )
        if archive:
            await client.edit_folder(peer, 1)
    except Exception:
        logger.exception("dnd: ошибка")
        return False
    return True


async def set_avatar(client: typing.Any, peer: typing.Any, avatar: typing.Any) -> bool:
    import os as _os
    from telethon.tl.functions.channels import EditPhotoRequest
    from telethon.tl.types import UpdateNewChannelMessage

    if isinstance(avatar, str) and avatar.startswith(("http://", "https://")):
        try:
            import requests
            f: typing.Any = (await run_sync(requests.get, avatar)).content
        except Exception:
            return False
    elif isinstance(avatar, str) and _os.path.exists(avatar):
        f = avatar
    elif isinstance(avatar, bytes):
        f = avatar
    else:
        return False

    try:
        res = await client(
            EditPhotoRequest(
                channel=peer,
                photo=await client.upload_file(f, file_name="photo.png"),
            )
        )
    except Exception:
        logger.exception("set_avatar: ошибка")
        return False

    with contextlib.suppress(Exception):
        msg_id = next(
            u.message.id
            for u in res.updates
            if isinstance(u, UpdateNewChannelMessage)
        )
        await client.delete_messages(peer, message_ids=[msg_id])
    return True


async def invite_inline_bot(client: typing.Any, peer: typing.Any) -> None:
    from telethon.tl.functions.channels import InviteToChannelRequest, EditAdminRequest
    from telethon.tl.types import ChatAdminRights

    inline = getattr(client, "inline", None)
    bot_username = getattr(inline, "bot_username", None)
    if not bot_username:
        raise RuntimeError("invite_inline_bot: inline-бот недоступен")

    try:
        await client(InviteToChannelRequest(peer, [bot_username]))
    except Exception as exc:
        raise RuntimeError(
            "Не удалось пригласить inline-бота в чат, требуемый модулем"
        ) from exc

    with contextlib.suppress(Exception):
        await client(
            EditAdminRequest(
                channel=peer,
                user_id=bot_username,
                admin_rights=ChatAdminRights(ban_users=True),
                rank="Kitsune",
            )
        )


__all__ = [
    "get_args", "get_args_raw", "get_args_html", "split_args",
    "get_display_name", "get_entity_id", "get_entity_url", "mention_html",
    "resolve_entity", "is_bot", "is_channel", "is_group",
    "get_repo_path", "get_current_commit", "get_current_branch",
    "get_remote_commit", "has_updates", "get_changelog",
    "is_docker", "is_termux", "is_userland", "is_mobile", "is_heroku",
    "_detect_proot",
    "get_platform_name", "get_python_version", "get_arch",
    "escape_html", "chunks", "array_sum", "truncate", "run_sync", "rand",
    "detect_environment", "ENV",
    "IS_TERMUX", "IS_DOCKER", "IS_HEROKU", "IS_RAILWAY",
    "IS_WSL", "IS_LINUX", "IS_WINDOWS", "IS_MACOS",
    "is_serializable", "get_chat_id", "find_caller", "iter_raw_frames",
    "auto_delete", "ProgressMessage", "progress_bar", "make_progress_bar",
    "answer", "answer_file", "smart_split",
    "asset_channel", "ensure_kitsune_folder",
    "censor", "relocate_entities", "remove_html", "validate_html",
    "mime_type", "get_link", "get_message_link", "get_topic",
    "get_user", "get_target", "send_reaction", "dnd", "set_avatar",
    "invite_inline_bot",
]
