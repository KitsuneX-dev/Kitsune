
from __future__ import annotations

import uuid

from .common import AIOGRAM_AVAILABLE, logger, warn_no_aiogram_once

if AIOGRAM_AVAILABLE:
    from .common import InlineKeyboardButton, InlineKeyboardMarkup


def _warn_no_aiogram_once() -> None:
    warn_no_aiogram_once(
        "generate_markup()",
        "inline keyboards are disabled, generate_markup() returns None",
    )

class _InlineTarget:

    __slots__ = ("inline_message_id",)

    def __init__(self, inline_message_id: str) -> None:
        self.inline_message_id = inline_message_id

class _MarkupMixin:
    def generate_markup(
        self,
        buttons: list,
        unit_id: str | None = None,
    ) -> "InlineKeyboardMarkup | None":
        if not AIOGRAM_AVAILABLE:
            _warn_no_aiogram_once()
            return None
        keyboard: list[list[InlineKeyboardButton]] = []
        def _row(r):
            return r if isinstance(r, list) else [r]
        for row in buttons:
            for btn in _row(row):
                if isinstance(btn, dict) and "input" in btn and "_switch_query" not in btn:
                    btn["_switch_query"] = str(uuid.uuid4())[:10]
        for row in buttons:
            kb_row: list[InlineKeyboardButton] = []
            for btn in _row(row):
                if not isinstance(btn, dict):
                    continue
                text = btn.get("text", "?")
                if url := btn.get("url"):
                    kb_row.append(InlineKeyboardButton(text=text, url=url))
                elif "input" in btn:
                    kb_row.append(InlineKeyboardButton(
                        text=text,
                        switch_inline_query_current_chat=btn["_switch_query"] + " ",
                    ))
                elif "callback" in btn:
                    cb_id = str(uuid.uuid4())[:12]
                    self._callbacks[cb_id] = (
                        btn["callback"],
                        btn.get("args", ()),
                        self._client.tg_id,
                        btn.get("disable_security", False),
                        btn.get("kwargs", {}),
                    )
                    btn["_callback_data"] = cb_id
                    if unit_id:
                        self._callback_units[cb_id] = unit_id
                    kb_row.append(InlineKeyboardButton(text=text, callback_data=cb_id))
                elif "action" in btn:
                    action = str(btn["action"]).lower()
                    cb_id = str(uuid.uuid4())[:12]
                    if action in ("close", "delete"):
                        handler = self._make_action_handler(unit_id, close=True)
                    else:
                        handler = self._make_action_handler(unit_id, close=False)
                    self._callbacks[cb_id] = (
                        handler,
                        (),
                        self._client.tg_id,
                        btn.get("disable_security", False),
                        {},
                    )
                    btn["_callback_data"] = cb_id
                    if unit_id:
                        self._callback_units[cb_id] = unit_id
                    kb_row.append(InlineKeyboardButton(text=text, callback_data=cb_id))
                elif raw := btn.get("data"):
                    kb_row.append(InlineKeyboardButton(text=text, callback_data=raw))
            if kb_row:
                keyboard.append(kb_row)
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
