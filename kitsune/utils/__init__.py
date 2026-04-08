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


# ─── smart_split: умное разбиение длинных сообщений (перенесено из Heroku) ───
#
# Разбивает длинный HTML-текст на части не ломая теги форматирования и не
# разрывая слова посередине. Учитывает UTF-16 (как Telegram считает длину).
#
# Использование:
#   from kitsune.utils import smart_split
#   chunks = list(smart_split(text, entities, length=4096))
#
# Автор оригинала: @bsolute (Heroku/Hikka project)

def _copy_tl_entity(entity, **kwargs):
    """Создаёт копию TL-объекта с изменёнными полями."""
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
    """
    Умное разбиение текста на части с сохранением HTML-форматирования.

    Гарантии:
    - Ни один графемный кластер (символ) не будет разорван посередине.
    - HTML-теги (entities) корректно обрезаются и смещаются для каждой части.
    - Учитывается UTF-16-кодировка (именно так Telegram считает длину строк).
    - Разбивка происходит по ``split_on`` символам (\\n или пробел), а не в середине слова.

    :param text:        Чистый текст (без HTML).
    :param entities:    Список форматирующих entity-объектов Telethon.
    :param length:      Максимальная длина одной части в UTF-16 кодовых единицах (4096 для Telegram).
    :param split_on:    Символы, по которым предпочтительно делать разбивку.
    :param min_length:  Минимальная позиция для поиска split_on (не разрывать в самом начале).
    :return:            Итератор строк с HTML-форматированием.

    Пример::

        from telethon.extensions.html import unparse
        text, entities = parse("<b>Hello world! ...</b>")
        for part in smart_split(text, entities):
            await message.respond(part, parse_mode="html")
    """
    import re as _re

    # Ленивый импорт grapheme — не нужен при старте, только при больших текстах
    try:
        import grapheme as _grapheme
        _safe_split_index = _grapheme.safe_split_index
    except ImportError:
        # Fallback: просто берём по символам
        def _safe_split_index(s, idx):
            return min(idx, len(s))

    try:
        from telethon.extensions.html import unparse as _unparse
    except ImportError:
        # Минимальный fallback если telethon недоступен
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
