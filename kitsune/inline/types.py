"""
Kitsune Inline Types

Defines typed wrappers for aiogram inline interactions.
Cleaner than Hikka's approach — uses dataclasses instead of bare dicts.
"""

# © Yushi (@Mikasu32), 2024-2026
# Kitsune Userbot — License: AGPLv3

from __future__ import annotations

import asyncio
import typing
from dataclasses import dataclass, field


@dataclass
class InlineButton:
    """A single inline keyboard button."""
    text: str
    # Exactly one of these must be set:
    callback: typing.Callable | None = None
    url: str | None = None
    data: str | None = None
    # Extra args passed to callback(call, *args)
    args: tuple = field(default_factory=tuple)
    # If True — any user can press, not just owner
    disable_security: bool = False


@dataclass
class InlineCall:
    """Wraps an aiogram CallbackQuery for Kitsune handlers."""
    id: str
    chat_id: int
    message_id: int
    data: str
    _answer: typing.Callable   # raw aiogram answer coroutine
    _edit:   typing.Callable   # raw aiogram edit coroutine

    async def answer(self, text: str = "", show_alert: bool = False) -> None:
        await self._answer(text=text, show_alert=show_alert)

    async def edit(
        self,
        text: str,
        reply_markup: typing.Any = None,
        parse_mode: str = "HTML",
    ) -> None:
        await self._edit(text=text, reply_markup=reply_markup, parse_mode=parse_mode)


# Markup helpers
def markup_from_buttons(
    buttons: list[InlineButton | list[InlineButton]],
) -> list[list[dict]]:
    """
    Convert a flat list or list-of-rows of InlineButton into the
    raw dict structure that InlineManager.generate_markup() expects.
    """
    rows: list[list[InlineButton]] = []
    for item in buttons:
        if isinstance(item, list):
            rows.append(item)
        else:
            rows.append([item])

    result = []
    for row in rows:
        result_row = []
        for btn in row:
            d: dict[str, typing.Any] = {"text": btn.text}
            if btn.url:
                d["url"] = btn.url
            elif btn.callback:
                d["callback"] = btn.callback
                d["args"] = btn.args
                d["disable_security"] = btn.disable_security
            elif btn.data:
                d["data"] = btn.data
            result_row.append(d)
        result.append(result_row)
    return result
