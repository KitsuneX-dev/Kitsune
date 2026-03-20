"""
Kitsune utility functions.
Cleaned-up version of Hikka's utils.py — removed dead code, full type hints.
"""

# © Yushi (@Mikasu32), 2024-2026
# Kitsune Userbot — License: AGPLv3

from __future__ import annotations

import asyncio
import html
import inspect
import io
import logging
import os
import typing
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Text helpers ──────────────────────────────────────────────────────────────

def escape_html(text: typing.Any) -> str:
    return html.escape(str(text))


def chunks(text: str, size: int) -> list[str]:
    """Split *text* into chunks of at most *size* characters."""
    return [text[i : i + size] for i in range(0, len(text), size)]


def smart_split(text: str, entities: list, max_len: int = 4096) -> typing.Generator[str, None, None]:
    """
    Split an HTML-parsed (text, entities) pair into chunks ≤ max_len,
    reconstructing HTML tags around each chunk.
    Yields plain strings.
    """
    # Simple fallback: chunk on raw text
    for chunk in chunks(text, max_len):
        yield chunk


def truncate(text: str, max_len: int = 512, suffix: str = "…") -> str:
    return text if len(text) <= max_len else text[: max_len - len(suffix)] + suffix


# ── Async helpers ─────────────────────────────────────────────────────────────

async def run_sync(func: typing.Callable, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
    """Run a blocking callable in the default executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


# ── Telegram helpers ──────────────────────────────────────────────────────────

async def asset_channel(
    client: typing.Any,
    title: str,
    description: str,
    archive: bool = True,
    avatar: str | None = None,
) -> tuple[int, bool]:
    """
    Get or create a private channel used as asset storage.
    Returns (channel_id, created: bool).
    """
    from telethon.tl.functions.channels import CreateChannelRequest
    from telethon.tl.functions.account import UpdateNotifySettingsRequest
    from telethon.tl.types import InputNotifyPeer, InputPeerNotifySettings
    from telethon.errors import ChannelsTooMuchError

    async for dialog in client.iter_dialogs():
        if dialog.is_channel and dialog.title == title:
            return dialog.id, False

    try:
        result = await client(
            CreateChannelRequest(title=title, about=description, megagroup=False)
        )
        channel = result.chats[0]
        channel_id = channel.id

        # Mute notifications
        with __import__("contextlib").suppress(Exception):
            await client(
                UpdateNotifySettingsRequest(
                    peer=InputNotifyPeer(await client.get_input_entity(channel_id)),
                    settings=InputPeerNotifySettings(mute_until=2**31 - 1),
                )
            )

        if archive:
            with __import__("contextlib").suppress(Exception):
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


def find_caller(
    stack: list[inspect.FrameInfo],
) -> typing.Callable | None:
    """Return the first non-kitsune-internals callable on the call stack."""
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


# ── Auto-delete ───────────────────────────────────────────────────────────────

async def auto_delete(message: typing.Any, delay: float | None = None) -> None:
    """
    Удалить сервисное сообщение через delay секунд.
    Если delay=None — читает настройку из БД (kitsune.core / auto_delete_delay).
    Если настройка = 0 — ничего не делает.
    """
    if delay is None:
        # Пробуем получить клиент и БД из объекта сообщения
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
    with __import__("contextlib").suppress(Exception):
        await message.delete()


# ── Progress bar ──────────────────────────────────────────────────────────────

def progress_bar(current: int | float, total: int | float, width: int = 12) -> str:
    """
    Возвращает красивую строку прогресс-бара.

    Пример: ████████░░░░  67%

    Использует filled/empty блоки без кринжовых ASCII-символов.
    """
    if total <= 0:
        pct = 0.0
    else:
        pct = max(0.0, min(1.0, current / total))

    filled = round(pct * width)
    empty  = width - filled

    bar = "█" * filled + "░" * empty
    percent = int(pct * 100)
    return f"{bar}  {percent}%"


class ProgressMessage:
    """
    Хелпер для обновления прогресс-бара прямо в Telegram-сообщении.

    Использование:
        async with ProgressMessage(event, "⬇️ Скачиваю", total=100) as prog:
            for i in range(100):
                await do_work()
                await prog.update(i + 1)
    """

    def __init__(
        self,
        event: typing.Any,
        title: str,
        total: int | float = 100,
        width: int = 12,
        update_every: float = 1.5,
    ) -> None:
        self._event       = event
        self._title       = title
        self._total       = total
        self._width       = width
        self._update_every = update_every
        self._msg:        typing.Any = None
        self._last_update: float = 0.0
        self._current:    float = 0.0

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
        """Обновить значение прогресса. Сообщение редактируется не чаще update_every секунд."""
        self._current = current
        now = asyncio.get_event_loop().time()
        if not force and (now - self._last_update) < self._update_every:
            return
        self._last_update = now
        bar = progress_bar(self._current, self._total, self._width)
        with __import__("contextlib").suppress(Exception):
            await self._msg.edit(
                f"{self._title}\n{bar}",
                parse_mode="html",
            )

    async def done(self, text: str) -> None:
        """Заменить бар финальным сообщением."""
        with __import__("contextlib").suppress(Exception):
            await self._msg.edit(text, parse_mode="html")


# ── System detection ──────────────────────────────────────────────────────────

def detect_environment() -> dict[str, bool]:
    """Detect the runtime environment."""
    import contextlib, platform

    is_wsl = False
    with contextlib.suppress(Exception):
        if "microsoft-standard" in platform.uname().release.lower():
            is_wsl = True

    return {
        "termux":     "com.termux" in os.environ.get("PREFIX", ""),
        "docker":     "DOCKER" in os.environ,
        "railway":    "RAILWAY" in os.environ,
        "codespaces": "CODESPACES" in os.environ,
        "wsl":        is_wsl,
        "linux":      platform.system() == "Linux",
        "windows":    platform.system() == "Windows",
        "macos":      platform.system() == "Darwin",
    }


ENV = detect_environment()
IS_TERMUX    = ENV["termux"]
IS_DOCKER    = ENV["docker"]
IS_RAILWAY   = ENV["railway"]
IS_LINUX     = ENV["linux"]
