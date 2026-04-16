from .args     import get_args, get_args_raw, get_args_html, split_args
from .entity   import (
    get_display_name, get_entity_id, mention_html,
    resolve_entity, is_bot, is_channel, is_group,
)
from .git      import (
    get_repo_path, get_current_commit, get_current_branch,
    get_remote_commit, has_updates, get_changelog,
)
from .platform import (
    is_docker, is_termux, is_heroku,
    get_platform_name, get_python_version, get_arch,
)

import html as _html
import asyncio as _asyncio
import io as _io
import logging as _logging

_logger = _logging.getLogger(__name__)

def escape_html(text: object) -> str:
    return _html.escape(str(text))

def chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]

def truncate(text: str, max_len: int = 512, suffix: str = "…") -> str:
    return text if len(text) <= max_len else text[: max_len - len(suffix)] + suffix

async def run_sync(func, *args, **kwargs):
    loop = _asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

__all__ = [
    "get_args", "get_args_raw", "get_args_html", "split_args",
    "get_display_name", "get_entity_id", "mention_html",
    "resolve_entity", "is_bot", "is_channel", "is_group",
    "get_repo_path", "get_current_commit", "get_current_branch",
    "get_remote_commit", "has_updates", "get_changelog",
    "is_docker", "is_termux", "is_heroku",
    "get_platform_name", "get_python_version", "get_arch",
    "escape_html", "chunks", "truncate", "run_sync",
]

import asyncio as _asyncio
import inspect as _inspect
import logging as _logging
import os as _os

_logger = _logging.getLogger(__name__)

IS_TERMUX = is_termux()
IS_DOCKER = is_docker()

async def auto_delete(message, delay: float | None = None) -> None:
    import contextlib as _ctx
    if delay is None:
        try:
            client = getattr(message, 'client', None)
            db = getattr(client, '_kitsune_db', None)
            delay = float(db.get('kitsune.core', 'auto_delete_delay', 0)) if db else 0.0
        except Exception:
            delay = 0.0
    if not delay:
        return
    await _asyncio.sleep(delay)
    with _ctx.suppress(Exception):
        await message.delete()

class ProgressMessage:

    def __init__(self, event, text: str, total: int = 100):
        self._event = event
        self._text = text
        self._total = total
        self._step = 0
        self._msg = None

    async def __aenter__(self):
        self._msg = await self._event.reply(self._text, parse_mode="html")
        return self

    async def __aexit__(self, *_):
        pass

    async def update(self, step: int, text: str | None = None) -> None:
        self._step = step
        bar = make_progress_bar(step, self._total)
        label = text or self._text
        try:
            await self._msg.edit(f"{label}\n{bar}", parse_mode="html")
        except Exception:
            pass

    async def done(self, text: str) -> None:
        try:
            await self._msg.edit(text, parse_mode="html")
        except Exception:
            pass

def make_progress_bar(current: int, total: int, width: int = 10) -> str:
    filled = int(width * current / max(total, 1))
    return "█" * filled + "░" * (width - filled) + f" {current}/{total}"

def find_caller(stack: list) -> str:
    for frame_info in stack:
        filename = frame_info.filename if hasattr(frame_info, "filename") else frame_info[1]
        if "kitsune" in filename and "log.py" not in filename and "utils" not in filename:
            module = _os.path.basename(filename).replace(".py", "")
            return module
    return "unknown"

async def asset_channel(client, title: str = "Kitsune Assets", *, silent: bool = True, description: str = "", archive: bool = False):
    try:
        from telethon.tl.functions.channels import CreateChannelRequest
        from telethon.tl.types import InputMessagesFilterEmpty

        async for dialog in client.iter_dialogs():
            if dialog.is_channel and dialog.title == title and dialog.entity.creator:
                return dialog.entity.id, False

        result = await client(CreateChannelRequest(
            title=title,
            about=description or "Kitsune internal asset storage",
            megagroup=False,
        ))
        channel = result.chats[0]
        if archive:
            try:
                from telethon.tl.functions.folders import EditPeerFoldersRequest
                from telethon.tl.types import InputFolderPeer, InputChannel
                await client(EditPeerFoldersRequest(folder_peers=[
                    InputFolderPeer(peer=InputChannel(channel.id, channel.access_hash), folder_id=1)
                ]))
            except Exception:
                pass
        return channel.id, True
    except Exception as e:
        _logger.warning("asset_channel: не удалось создать канал: %s", e)
        return None, False

__all__ += [
    "IS_TERMUX", "IS_DOCKER",
    "auto_delete", "ProgressMessage", "make_progress_bar",
    "find_caller", "asset_channel",
]

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
    import re as _re

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

__all__ += ["smart_split"]

# ---------------------------------------------------------------------------
# Functions ported from kitsune/utils.py (flat module) that are required by
# hikka/heroku compat shims and user modules.
# ---------------------------------------------------------------------------

import io as _io
import typing as _typing

def is_serializable(value: _typing.Any) -> bool:
    """Return True if *value* can be serialised to JSON."""
    import json as _json
    try:
        _json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def get_chat_id(message: _typing.Any) -> _typing.Optional[int]:
    """Return the chat/peer id from a Telethon message object."""
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


async def answer(
    message: _typing.Any,
    response: _typing.Union[str, bytes, _io.IOBase],
    *,
    parse_mode: str = "HTML",
    link_preview: bool = False,
    **kwargs: _typing.Any,
) -> _typing.Any:
    """Edit the caller's own message or respond to someone else's."""
    if isinstance(message, int):
        client = kwargs.pop("client", None)
        if client is None:
            raise ValueError("answer: int message requires client= kwarg")
        return await client.send_message(
            message, response, parse_mode=parse_mode, link_preview=link_preview, **kwargs
        )

    is_own = (
        getattr(message, "out", False)
        and not getattr(message, "via_bot_id", None)
        and not getattr(message, "fwd_from", None)
    )

    if is_own:
        try:
            return await message.edit(
                response, parse_mode=parse_mode, link_preview=link_preview, **kwargs
            )
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return message
            _logger.debug("answer: edit failed, falling back to respond", exc_info=True)

    if "reply_to" not in kwargs:
        reply_to = getattr(message, "reply_to_msg_id", None)
        if reply_to:
            kwargs["reply_to"] = reply_to

    return await message.respond(
        response, parse_mode=parse_mode, link_preview=link_preview, **kwargs
    )


async def answer_file(
    message: _typing.Any,
    file: _typing.Union[str, bytes, _io.IOBase],
    caption: _typing.Optional[str] = None,
    *,
    force_document: bool = False,
    **kwargs: _typing.Any,
) -> _typing.Any:
    """Send a file as a reply, deleting the original outgoing message."""
    import contextlib as _ctx

    client = message.client
    peer = getattr(message, "peer_id", None) or getattr(message, "chat_id", None)
    if peer is None:
        raise ValueError("answer_file: cannot determine peer from message")

    if "reply_to" not in kwargs:
        reply_to = getattr(message, "reply_to_msg_id", None)
        if reply_to:
            kwargs["reply_to"] = reply_to

    if isinstance(file, bytes):
        file = _io.BytesIO(file)

    try:
        result = await client.send_file(
            peer, file, caption=caption, force_document=force_document, **kwargs
        )
    except Exception:
        if caption:
            _logger.warning("answer_file: send failed, falling back to text", exc_info=True)
            return await answer(message, caption)
        raise

    if getattr(message, "out", False):
        with _ctx.suppress(Exception):
            await message.delete()

    return result


def progress_bar(current: _typing.Union[int, float], total: _typing.Union[int, float], width: int = 12) -> str:
    """Return a Unicode progress bar string with percentage."""
    if total <= 0:
        pct = 0.0
    else:
        pct = max(0.0, min(1.0, current / total))

    filled = round(pct * width)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    percent = int(pct * 100)
    return f"{bar}  {percent}%"


__all__ += [
    "is_serializable", "get_chat_id",
    "answer", "answer_file",
    "progress_bar",
]
