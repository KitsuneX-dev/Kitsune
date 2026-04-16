
from __future__ import annotations

import asyncio
import logging
import time
import typing

logger = logging.getLogger(__name__)

_STATE_TTL = 60 * 30

class BotInlineCall:

    __slots__ = (
        "id", "chat_id", "message_id", "data",
        "inline_message_id", "from_user_id",
        "_answer", "_edit", "_delete",
        "unit_id", "manager",
    )

    def __init__(
        self,
        *,
        call_id: str,
        chat_id: int,
        message_id: int,
        data: str,
        inline_message_id: str = "",
        from_user_id: int = 0,
        answer_fn: typing.Callable,
        edit_fn: typing.Optional[typing.Callable] = None,
        delete_fn: typing.Optional[typing.Callable] = None,
        unit_id: str = "",
        manager: typing.Any = None,
    ) -> None:
        self.id                 = call_id
        self.chat_id            = chat_id
        self.message_id         = message_id
        self.data               = data
        self.inline_message_id  = inline_message_id
        self.from_user_id       = from_user_id
        self._answer            = answer_fn
        self._edit              = edit_fn
        self._delete            = delete_fn
        self.unit_id            = unit_id
        self.manager            = manager

    async def answer(self, text: str = "", *, show_alert: bool = False) -> None:
        try:
            await self._answer(text=text, show_alert=show_alert)
        except Exception:
            logger.debug("BotInlineCall.answer: failed", exc_info=True)

    async def edit(
        self,
        text: str,
        reply_markup: typing.Any = None,
        *,
        parse_mode: str = "HTML",
    ) -> None:
        if self._edit is None:
            logger.warning("BotInlineCall.edit: нет edit_fn")
            return
        try:
            await self._edit(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            logger.debug("BotInlineCall.edit: failed", exc_info=True)

    async def delete(self) -> None:
        if self._delete:
            try:
                await self._delete()
            except Exception:
                logger.debug("BotInlineCall.delete: failed", exc_info=True)

    async def unload(self) -> None:
        if self.manager and self.unit_id:
            self.manager._units.pop(self.unit_id, None)
        await self.delete()

class BotInlineMessage:

    def __init__(
        self,
        *,
        inline_message_id: str,
        unit_id: str,
        manager: typing.Any,
    ) -> None:
        self.inline_message_id = inline_message_id
        self.unit_id           = unit_id
        self._manager          = manager

    async def edit(
        self,
        text: str,
        reply_markup: list | None = None,
    ) -> None:
        if self._manager:
            await self._manager.edit(
                self,
                text,
                reply_markup=reply_markup,
                inline_message_id=self.inline_message_id,
            )

    async def unload(self) -> None:
        if self._manager:
            self._manager._units.pop(self.unit_id, None)

class FSMState:

    def __init__(self, ttl: int = _STATE_TTL) -> None:
        self._states: dict[int, tuple[str, float]] = {}
        self._meta:   dict[int, typing.Any]         = {}
        self._ttl     = ttl
        self._lock    = asyncio.Lock()

    def set(self, user_id: int, state: str, meta: typing.Any = None) -> None:
        self._states[user_id] = (state, time.monotonic() + self._ttl)
        if meta is not None:
            self._meta[user_id] = meta

    def get(self, user_id: int) -> str | None:
        entry = self._states.get(user_id)
        if entry is None:
            return None
        state, expires = entry
        if time.monotonic() > expires:
            self.clear(user_id)
            return None
        return state

    def get_meta(self, user_id: int) -> typing.Any:
        return self._meta.get(user_id)

    def set_meta(self, user_id: int, meta: typing.Any) -> None:
        self._meta[user_id] = meta

    def clear(self, user_id: int) -> None:
        self._states.pop(user_id, None)
        self._meta.pop(user_id, None)

    def has(self, user_id: int) -> bool:
        return self.get(user_id) is not None

    def purge_expired(self) -> int:
        now   = time.monotonic()
        stale = [uid for uid, (_, exp) in self._states.items() if exp < now]
        for uid in stale:
            self.clear(uid)
        return len(stale)

    def __len__(self) -> int:
        return sum(1 for uid in list(self._states) if self.get(uid) is not None)
