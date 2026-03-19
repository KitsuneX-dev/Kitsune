"""
Kitsune Inline Manager

Migrated from aiogram 2.x (Hikka) → aiogram 3.x.
Key differences:
- Router-based handler registration (not dp.register_*)
- FSM context injection via Dispatcher, not middleware hacks
- CallbackQuery answers via call.answer() directly
- No global dp instance — clean per-bot setup
"""

# © Yushi (@Mikasu32), 2024-2026
# Kitsune Userbot — License: AGPLv3

from __future__ import annotations

import asyncio
import logging
import typing
import uuid

logger = logging.getLogger(__name__)

try:
    from aiogram import Bot, Dispatcher, Router
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.filters import Command
    from aiogram.types import (
        CallbackQuery,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        InlineQuery,
        InlineQueryResultArticle,
        InputTextMessageContent,
        Message,
    )
    AIOGRAM_AVAILABLE = True
except ImportError:
    AIOGRAM_AVAILABLE = False
    logger.warning("InlineManager: aiogram not installed, inline features disabled")

from .types import InlineCall


class InlineManager:
    """
    Manages the auxiliary inline bot used by Kitsune modules.

    Usage (inside a module):
        await self.inline.form(
            text="Choose:",
            message=event.message,
            reply_markup=[[{"text": "OK", "callback": my_handler}]],
        )
    """

    def __init__(self, client: typing.Any, db: typing.Any, token: str) -> None:
        self._client  = client
        self._db      = db
        self._token   = token
        self._bot:    typing.Any = None
        self._dp:     typing.Any = None
        self._router: typing.Any = None
        # callback_id → (handler, args, owner_id, disable_security)
        self._callbacks: dict[str, tuple] = {}
        self._started = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if not AIOGRAM_AVAILABLE:
            logger.warning("InlineManager: aiogram unavailable, skipping")
            return
        if self._started:
            return

        self._bot = Bot(
            token=self._token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self._dp  = Dispatcher()
        self._router = Router()
        self._dp.include_router(self._router)

        self._router.callback_query.register(self._on_callback)
        self._router.inline_query.register(self._on_inline_query)

        self._started = True
        asyncio.ensure_future(self._dp.start_polling(self._bot, handle_signals=False))
        logger.info("InlineManager: bot polling started")

    async def stop(self) -> None:
        if self._bot and self._started:
            await self._dp.stop_polling()
            await self._bot.session.close()
            self._started = False

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_markup(
        self,
        buttons: list[list[dict] | dict],
    ) -> InlineKeyboardMarkup | None:
        """
        Convert a nested list of button dicts into an aiogram InlineKeyboardMarkup.

        Button dict keys:
            text             (required)
            url              → URL button
            callback         → callable, registered with a unique data id
            args             → extra args for callback
            disable_security → bool
            data             → raw callback_data string
        """
        if not AIOGRAM_AVAILABLE:
            return None

        keyboard: list[list[InlineKeyboardButton]] = []

        def _normalize_row(row):
            return row if isinstance(row, list) else [row]

        for row in buttons:
            kb_row: list[InlineKeyboardButton] = []
            for btn in _normalize_row(row):
                text = btn.get("text", "?")
                if url := btn.get("url"):
                    kb_row.append(InlineKeyboardButton(text=text, url=url))
                elif callback := btn.get("callback"):
                    cb_id = str(uuid.uuid4())[:8]
                    self._callbacks[cb_id] = (
                        callback,
                        btn.get("args", ()),
                        self._client.tg_id,
                        btn.get("disable_security", False),
                    )
                    kb_row.append(InlineKeyboardButton(text=text, callback_data=cb_id))
                elif raw_data := btn.get("data"):
                    kb_row.append(InlineKeyboardButton(text=text, callback_data=raw_data))
            if kb_row:
                keyboard.append(kb_row)

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    async def form(
        self,
        text: str,
        message: typing.Any,
        reply_markup: list | None = None,
        parse_mode: str = "HTML",
        silent: bool = True,
    ) -> typing.Any:
        """Send a message with an inline keyboard via the bot."""
        if not self._bot:
            logger.warning("InlineManager.form: bot not started")
            return None

        markup = self.generate_markup(reply_markup) if reply_markup else None
        try:
            return await self._bot.send_message(
                chat_id=message.chat_id,
                text=text,
                reply_markup=markup,
                parse_mode=parse_mode,
                disable_notification=silent,
            )
        except Exception:
            logger.exception("InlineManager.form: send failed")
            return None

    # ── Handlers ──────────────────────────────────────────────────────────────

    async def _on_callback(self, call: "CallbackQuery") -> None:  # type: ignore[name-defined]
        entry = self._callbacks.get(call.data)
        if entry is None:
            await call.answer("⚠️ Устаревшая кнопка.", show_alert=True)
            return

        handler, args, owner_id, disable_security = entry

        if not disable_security and call.from_user.id != owner_id:
            await call.answer("🚫 Нет доступа.", show_alert=True)
            return

        wrapped = InlineCall(
            id=call.id,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            data=call.data,
            _answer=call.answer,
            _edit=call.message.edit_text,
        )

        try:
            await handler(wrapped, *args)
        except Exception:
            logger.exception("InlineManager: callback handler failed (data=%s)", call.data)
            await call.answer("❌ Ошибка обработки.", show_alert=True)

    async def _on_inline_query(self, query: "InlineQuery") -> None:  # type: ignore[name-defined]
        # Default empty handler — modules override via subclassing or registration
        await query.answer([], cache_time=0)
