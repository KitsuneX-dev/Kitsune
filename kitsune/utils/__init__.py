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
