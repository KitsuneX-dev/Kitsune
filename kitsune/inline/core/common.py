
from __future__ import annotations

import logging

logger = logging.getLogger("kitsune.inline.core")

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

_AIOGRAM_WARNED: set[str] = set()

_AIOGRAM_HINT = "Install it with: pip install aiogram"


def warn_no_aiogram_once(feature: str, disabled: str) -> None:
    if feature in _AIOGRAM_WARNED:
        return
    _AIOGRAM_WARNED.add(feature)
    logger.warning(
        "optional dependency 'aiogram' is not installed: %s -> %s. %s",
        feature,
        disabled,
        _AIOGRAM_HINT,
    )


def reset_optional_dep_warnings() -> None:
    _AIOGRAM_WARNED.clear()


_UNIT_TTL = 60 * 60 * 24
_INPUT_MARKER = "\u2063\u2060\u2063"

_RAND_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
