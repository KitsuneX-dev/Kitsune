"""
kitsune/utils/__init__.py — реэкспорт для обратной совместимости.

Все модули импортируют из kitsune.utils — этот файл собирает
их из подмодулей в одном месте.
"""

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

# Из оригинального utils.py — оставляем здесь чтобы не ломать импорты
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
    # args
    "get_args", "get_args_raw", "get_args_html", "split_args",
    # entity
    "get_display_name", "get_entity_id", "mention_html",
    "resolve_entity", "is_bot", "is_channel", "is_group",
    # git
    "get_repo_path", "get_current_commit", "get_current_branch",
    "get_remote_commit", "has_updates", "get_changelog",
    # platform
    "is_docker", "is_termux", "is_heroku",
    "get_platform_name", "get_python_version", "get_arch",
    # base
    "escape_html", "chunks", "truncate", "run_sync",
]


# ─── Совместимость: функции из оригинального utils.py ────────────────────────

import asyncio as _asyncio
import inspect as _inspect
import logging as _logging
import os as _os

_logger = _logging.getLogger(__name__)

# Алиасы платформ для обратной совместимости (from ..utils import IS_TERMUX, IS_DOCKER)
IS_TERMUX = is_termux()
IS_DOCKER = is_docker()


async def auto_delete(message, delay: float = 5.0) -> None:
    """Удалить сообщение через delay секунд."""
    await _asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


class ProgressMessage:
    """
    Контекстный менеджер для сообщений с прогресс-баром.

    Использование:
        async with ProgressMessage(event, "Загружаю...", total=3) as prog:
            await prog.update(1)
            ...
            await prog.done("Готово!")
    """

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
    """Найти имя вызывающего модуля из стека."""
    for frame_info in stack:
        filename = frame_info.filename if hasattr(frame_info, "filename") else frame_info[1]
        if "kitsune" in filename and "log.py" not in filename and "utils" not in filename:
            module = _os.path.basename(filename).replace(".py", "")
            return module
    return "unknown"


async def asset_channel(client, title: str = "Kitsune Assets", *, silent: bool = True, description: str = "", archive: bool = False):
    """
    Получить или создать приватный канал для хранения ассетов.
    Возвращает (channel_id, created: bool).
    """
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
