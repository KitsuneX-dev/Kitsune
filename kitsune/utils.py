from __future__ import annotations

import asyncio
import html
import inspect
import io
import logging
import os
import shlex
import typing
from pathlib import Path

logger = logging.getLogger(__name__)

def escape_html(text: typing.Any) -> str:
    return html.escape(str(text))

def chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]

def smart_split(text: str, entities: list, max_len: int = 4096) -> typing.Generator[str, None, None]:
    for chunk in chunks(text, max_len):
        yield chunk

def truncate(text: str, max_len: int = 512, suffix: str = "…") -> str:
    return text if len(text) <= max_len else text[: max_len - len(suffix)] + suffix

async def run_sync(func: typing.Callable, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

def get_args(message: typing.Any) -> list[str]:
    text = getattr(message, "text", None) or getattr(message, "message", "")
    if not text:
        return []
    parts = text.split(maxsplit=1)
    if len(parts) <= 1:
        return []
    raw = parts[1]
    try:
        return list(filter(None, shlex.split(raw)))
    except ValueError:
        return list(filter(None, raw.split()))

def get_args_raw(message: typing.Any) -> str:
    text = getattr(message, "text", None) or getattr(message, "message", "")
    if not text:
        return ""
    parts = text.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""

def get_args_html(message: typing.Any) -> str:
    try:
        from telethon.extensions import html as tl_html
        import copy

        raw_text = getattr(message, "text", "") or getattr(message, "message", "")
        entities = getattr(message, "entities", None) or []

        if not raw_text:
            return ""

        space_idx = raw_text.find(" ")
        if space_idx == -1:
            return ""

        command_len = space_idx + 1
        args_text = raw_text[command_len:]

        shifted_entities = []
        for entity in entities:
            new_offset = entity.offset - command_len
            if new_offset < 0:
                if new_offset + entity.length > 0:
                    e = copy.copy(entity)
                    e.length = new_offset + entity.length
                    e.offset = 0
                    shifted_entities.append(e)
                continue
            e = copy.copy(entity)
            e.offset = new_offset
            shifted_entities.append(e)

        if not shifted_entities:
            return args_text

        return tl_html.unparse(args_text, shifted_entities)
    except ImportError:
        return get_args_raw(message)
    except Exception:
        logger.debug("get_args_html failed", exc_info=True)
        return get_args_raw(message)

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

async def answer(
    message: typing.Any,
    response: typing.Union[str, bytes, io.IOBase],
    *,
    parse_mode: str = "HTML",
    link_preview: bool = False,
    **kwargs: typing.Any,
) -> typing.Any:
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
    import contextlib

    client = message.client
    peer = getattr(message, "peer_id", None) or getattr(message, "chat_id", None)
    if peer is None:
        raise ValueError("answer_file: cannot determine peer from message")

    if "reply_to" not in kwargs:
        reply_to = getattr(message, "reply_to_msg_id", None)
        if reply_to:
            kwargs["reply_to"] = reply_to

    if isinstance(file, bytes):
        file = io.BytesIO(file)

    try:
        result = await client.send_file(
            peer, file, caption=caption, force_document=force_document, **kwargs
        )
    except Exception:
        if caption:
            logger.warning("answer_file: send failed, falling back to text", exc_info=True)
            return await answer(message, caption)
        raise

    if getattr(message, "out", False):
        with contextlib.suppress(Exception):
            await message.delete()

    return result

async def asset_channel(
    client: typing.Any,
    title: str,
    description: str,
    archive: bool = True,
    avatar: str | None = None,
    megagroup: bool = False,
) -> tuple[int, bool]:
    import contextlib
    from telethon.tl.functions.channels import CreateChannelRequest
    from telethon.tl.functions.account import UpdateNotifySettingsRequest
    from telethon.tl.types import InputNotifyPeer, InputPeerNotifySettings
    from telethon.errors import ChannelsTooMuchError

    # Сначала ищем существующую группу/канал с таким названием
    async for dialog in client.iter_dialogs():
        if (dialog.is_channel or dialog.is_group) and dialog.title == title:
            return dialog.id, False

    try:
        result = await client(
            CreateChannelRequest(title=title, about=description, megagroup=megagroup)
        )
        channel = result.chats[0]
        channel_id = channel.id

        with contextlib.suppress(Exception):
            await client(
                UpdateNotifySettingsRequest(
                    peer=InputNotifyPeer(await client.get_input_entity(channel_id)),
                    settings=InputPeerNotifySettings(mute_until=2**31 - 1),
                )
            )

        if archive:
            with contextlib.suppress(Exception):
                from telethon.tl.functions.folders import EditPeerFoldersRequest
                from telethon.tl.types import InputFolderPeer
                await client(
                    EditPeerFoldersRequest(
                        folder_peers=[
                            InputFolderPeer(
                                peer=await client.get_input_entity(channel_id),
                                folder_id=1,
                            )
                        ]
                    )
                )

        logger.info("asset_channel: created %r (id=%d)", title, channel_id)
        return channel_id, True

    except ChannelsTooMuchError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not create asset channel {title!r}: {exc}") from exc

async def ensure_kitsune_folder(client: typing.Any, db: typing.Any) -> None:
    """
    Создаёт папку '🦊 Kitsune' в Telegram и добавляет туда
    все служебные группы: KitsuneBackup, Kitsune-logs, kitsune-assets.
    Если папка уже есть — только обновляет её состав.
    """
    import contextlib
    try:
        from telethon.tl.functions.messages import (
            UpdateDialogFilterRequest,
            GetDialogFiltersRequest,
        )
        from telethon.tl.types import DialogFilter, InputPeerChannel, InputPeerEmpty

        _FOLDER_TITLE = "🦊 Kitsune"
        _ASSET_TITLES = {"KitsuneBackup", "Kitsune-logs", "kitsune-assets"}

        # Ищем ID нужных групп
        peer_inputs = []
        async for dialog in client.iter_dialogs():
            if dialog.title in _ASSET_TITLES:
                with contextlib.suppress(Exception):
                    peer_inputs.append(
                        await client.get_input_entity(dialog.id)
                    )

        if not peer_inputs:
            logger.debug("ensure_kitsune_folder: no asset channels found yet")
            return

        # Получаем существующие папки
        existing_filters = await client(GetDialogFiltersRequest())
        existing: typing.Any = None
        existing_id: int = 2  # 0 = All, 1 = Archived, 2+ — пользовательские

        # Ищем нашу папку
        for f in existing_filters.filters:
            if getattr(f, "title", None) == _FOLDER_TITLE:
                existing = f
                existing_id = f.id
                break
            if hasattr(f, "id"):
                existing_id = max(existing_id, f.id + 1)

        if existing is not None:
            # Добавляем недостающих
            current_peers = list(getattr(existing, "include_peers", []))
            existing_ids = {getattr(p, "channel_id", None) for p in current_peers}
            for p in peer_inputs:
                cid = getattr(p, "channel_id", None)
                if cid and cid not in existing_ids:
                    current_peers.append(p)
            new_filter = DialogFilter(
                id=existing_id,
                title=_FOLDER_TITLE,
                pinned_peers=[],
                include_peers=current_peers,
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
        else:
            new_filter = DialogFilter(
                id=existing_id,
                title=_FOLDER_TITLE,
                pinned_peers=[],
                include_peers=peer_inputs,
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
        logger.info("ensure_kitsune_folder: folder '%s' updated (%d peers)", _FOLDER_TITLE, len(peer_inputs))

    except Exception as exc:
        logger.debug("ensure_kitsune_folder: failed — %s", exc)


def find_caller(stack: list[inspect.FrameInfo]) -> typing.Callable | None:
    for frame_info in stack:
        frame = frame_info.frame
        locals_ = frame.f_locals
        self_ = locals_.get("self")
        if self_ is None:
            continue
        cls_name = type(self_).__name__
        if cls_name in ("Loader", "CommandDispatcher", "SecurityManager", "DatabaseManager"):
            continue
        func_name = frame_info.function
        method = getattr(self_, func_name, None)
        if callable(method):
            return method
    return None

def is_serializable(value: typing.Any) -> bool:
    import json
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False

async def auto_delete(message: typing.Any, delay: float | None = None) -> None:
    import contextlib

    if delay is None:
        try:
            client = message.client
            db = getattr(client, "_kitsune_db", None)
            if db is not None:
                delay = float(db.get("kitsune.core", "auto_delete_delay", 0))
            else:
                delay = 0.0
        except Exception:
            delay = 0.0

    if not delay:
        return

    await asyncio.sleep(delay)
    with contextlib.suppress(Exception):
        await message.delete()

def progress_bar(current: int | float, total: int | float, width: int = 12) -> str:
    if total <= 0:
        pct = 0.0
    else:
        pct = max(0.0, min(1.0, current / total))

    filled = round(pct * width)
    empty = width - filled

    bar = "█" * filled + "░" * empty
    percent = int(pct * 100)
    return f"{bar}  {percent}%"

class ProgressMessage:

    def __init__(
        self,
        event: typing.Any,
        title: str,
        total: int | float = 100,
        width: int = 12,
        update_every: float = 1.5,
    ) -> None:
        self._event = event
        self._title = title
        self._total = total
        self._width = width
        self._update_every = update_every
        self._msg: typing.Any = None
        self._last_update: float = 0.0
        self._current: float = 0.0

    async def __aenter__(self) -> "ProgressMessage":
        bar = progress_bar(0, self._total, self._width)
        self._msg = await self._event.reply(
            f"{self._title}\n{bar}",
            parse_mode="html",
        )
        self._last_update = asyncio.get_event_loop().time()
        return self

    async def __aexit__(self, *_: object) -> None:
        pass

    async def update(self, current: int | float, *, force: bool = False) -> None:
        import contextlib

        self._current = current
        now = asyncio.get_event_loop().time()
        if not force and (now - self._last_update) < self._update_every:
            return
        self._last_update = now
        bar = progress_bar(self._current, self._total, self._width)
        with contextlib.suppress(Exception):
            await self._msg.edit(
                f"{self._title}\n{bar}",
                parse_mode="html",
            )

    async def done(self, text: str) -> None:
        import contextlib
        with contextlib.suppress(Exception):
            await self._msg.edit(text, parse_mode="html")

def detect_environment() -> dict[str, bool]:
    import contextlib
    import platform

    is_wsl = False
    with contextlib.suppress(Exception):
        if "microsoft-standard" in platform.uname().release.lower():
            is_wsl = True

    return {
        "termux": "com.termux" in os.environ.get("PREFIX", ""),
        "docker": "DOCKER" in os.environ,
        "railway": "RAILWAY" in os.environ,
        "codespaces": "CODESPACES" in os.environ,
        "wsl": is_wsl,
        "linux": platform.system() == "Linux",
        "windows": platform.system() == "Windows",
        "macos": platform.system() == "Darwin",
    }

ENV = detect_environment()
IS_TERMUX = ENV["termux"]
IS_DOCKER = ENV["docker"]
IS_RAILWAY = ENV["railway"]
IS_LINUX = ENV["linux"]
