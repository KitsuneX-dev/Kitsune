
from __future__ import annotations

import time
import typing
import uuid

from ..types import InlineCall
from .common import logger

if typing.TYPE_CHECKING:  
    from .common import CallbackQuery

class _CallbacksMixin:
    def _register_callback(
        self,
        func,
        *,
        args: tuple = (),
        kwargs: dict | None = None,
    ) -> str:
        cb_id = str(uuid.uuid4())[:12]
        self._callbacks[cb_id] = (func, args, kwargs or {})
        return cb_id
    def register_inline_handler(self, func: typing.Callable) -> None:
        only_own = bool(getattr(func, "_inline_only_own", False))
        entry    = (func, only_own)
        if entry not in self._inline_handlers:
            self._inline_handlers.append(entry)
            logger.debug("InlineManager: registered inline_handler %r", func)
    def unregister_inline_handler(self, func: typing.Callable) -> None:
        def _same(h: typing.Callable) -> bool:
            if h is func:
                return True
            h_self = getattr(h, "__self__", None)
            f_self = getattr(func, "__self__", None)
            if h_self is not None and h_self is f_self:
                return getattr(h, "__func__", None) is getattr(func, "__func__", None)
            return False

        self._inline_handlers = [
            (h, o) for h, o in self._inline_handlers if not _same(h)
        ]
        logger.debug("InlineManager: unregistered inline_handler %r", func)
    def _make_action_handler(self, unit_id: str | None, *, close: bool) -> typing.Callable:
        async def _handler(call: typing.Any) -> None:
            if close:
                await self._delete_unit_message(call, unit_id=unit_id)
            if unit_id:
                await self._unload_unit(unit_id)
        return _handler
    async def _on_callback(self, call: "CallbackQuery") -> None:
        if call.data == "__noop__":
            await call.answer()
            return
        entry = self._callbacks.get(call.data)
        if entry is None:
            custom = self._custom_map.get(call.data)
            if custom is not None:
                entry = (
                    custom["handler"],
                    custom.get("args", ()),
                    self._me,
                    not custom.get("force_me", False),
                    custom.get("kwargs", {}),
                )
        if entry is None:
            await call.answer("⚠️ Устаревшая кнопка.", show_alert=True)
            return
        handler, args, owner_id, disable_security, kwargs = entry
        user_id = call.from_user.id if call.from_user else 0
        unit_id = self._callback_units.get(call.data)
        unit = self._units.get(unit_id) if unit_id else None
        if unit is not None:
            ttl = unit.get("ttl")
            if ttl and ttl < time.time():
                await self._unload_unit(unit_id)
                await call.answer("⌛️ Форма больше не активна.", show_alert=True)
                return
            button = next(
                (
                    btn
                    for row in unit.get("buttons", [])
                    for btn in (row if isinstance(row, list) else [row])
                    if isinstance(btn, dict) and btn.get("_callback_data") == call.data
                ),
                None,
            )
            if disable_security:
                button = dict(button or {}, disable_security=True)
            if not await self._check_unit_security(unit, user_id, button):
                await call.answer("🚫 Нет доступа.", show_alert=True)
                return
        elif not disable_security and user_id != owner_id:
            if user_id not in self._owner_ids():
                await call.answer("🚫 Нет доступа.", show_alert=True)
                return
        wrapped = InlineCall(
            id=call.id,
            chat_id=call.message.chat.id if call.message else 0,
            message_id=call.message.message_id if call.message else 0,
            data=call.data,
            _answer=call.answer,
            _edit=call.message.edit_text if call.message else None,
            from_user_id=call.from_user.id if call.from_user else None,
        )
        wrapped.inline_message_id = call.inline_message_id or ""
        try:
            await handler(wrapped, *args, **kwargs)
        except Exception:
            logger.exception("InlineManager callback error (data=%s)", call.data)
            await call.answer("❌ Ошибка.", show_alert=True)
