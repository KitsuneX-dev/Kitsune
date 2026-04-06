"""
kitsune/inline/events.py — типы событий и FSM-состояния для inline-системы.

Содержит:
  - BotInlineCall    — расширенный InlineCall с удобными методами
  - BotInlineMessage — обёртка над inline-сообщением для редактирования
  - FSMState         — хранилище состояний диалогов (машина состояний)

FSM используется в bot_pm.py для выстраивания диалогов с пользователем
через личные сообщения боту.
"""

from __future__ import annotations

import asyncio
import logging
import time
import typing

logger = logging.getLogger(__name__)

_STATE_TTL = 60 * 30  # 30 минут — потом состояние протухает


# ─── BotInlineCall ────────────────────────────────────────────────────────────

class BotInlineCall:
    """
    Расширенный объект нажатия на inline-кнопку.

    Добавляет по сравнению с базовым InlineCall:
      - unit_id — ID unit'а из InlineManager
      - manager — ссылка на InlineManager (для edit, form и т.п.)
      - unload() — закрыть/удалить unit
    """

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
        """Ответить на нажатие кнопки (всплывающее уведомление)."""
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
        """Редактировать текст inline-сообщения."""
        if self._edit is None:
            logger.warning("BotInlineCall.edit: нет edit_fn")
            return
        try:
            await self._edit(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            logger.debug("BotInlineCall.edit: failed", exc_info=True)

    async def delete(self) -> None:
        """Удалить сообщение (если доступно)."""
        if self._delete:
            try:
                await self._delete()
            except Exception:
                logger.debug("BotInlineCall.delete: failed", exc_info=True)

    async def unload(self) -> None:
        """Удалить unit из InlineManager и сообщение."""
        if self.manager and self.unit_id:
            self.manager._units.pop(self.unit_id, None)
        await self.delete()


# ─── BotInlineMessage ─────────────────────────────────────────────────────────

class BotInlineMessage:
    """
    Обёртка над отправленным inline-сообщением.
    Позволяет впоследствии редактировать его из кода (не из callback).
    """

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
        """Редактировать inline-сообщение через InlineManager.edit."""
        if self._manager:
            await self._manager.edit(
                self,
                text,
                reply_markup=reply_markup,
                inline_message_id=self.inline_message_id,
            )

    async def unload(self) -> None:
        """Удалить unit из InlineManager."""
        if self._manager:
            self._manager._units.pop(self.unit_id, None)


# ─── FSMState ────────────────────────────────────────────────────────────────

class FSMState:
    """
    Простая машина состояний для диалогов через личные сообщения боту.

    Пример использования в модуле:
        from ..inline.events import FSMState
        _fsm = FSMState()

        # Установить состояние (когда пользователь начал диалог)
        _fsm.set(user_id, "waiting_name")

        # Проверить состояние (в on_message)
        if _fsm.get(user_id) == "waiting_name":
            name = message.text
            _fsm.clear(user_id)
            ...

    Состояния автоматически удаляются через _STATE_TTL секунд.
    """

    def __init__(self, ttl: int = _STATE_TTL) -> None:
        self._states: dict[int, tuple[str, float]] = {}
        self._meta:   dict[int, typing.Any]         = {}
        self._ttl     = ttl
        self._lock    = asyncio.Lock()

    def set(self, user_id: int, state: str, meta: typing.Any = None) -> None:
        """Установить состояние пользователя."""
        self._states[user_id] = (state, time.monotonic() + self._ttl)
        if meta is not None:
            self._meta[user_id] = meta

    def get(self, user_id: int) -> str | None:
        """Получить текущее состояние пользователя (или None если нет/протухло)."""
        entry = self._states.get(user_id)
        if entry is None:
            return None
        state, expires = entry
        if time.monotonic() > expires:
            self.clear(user_id)
            return None
        return state

    def get_meta(self, user_id: int) -> typing.Any:
        """Получить метаданные, сохранённые вместе с состоянием."""
        return self._meta.get(user_id)

    def set_meta(self, user_id: int, meta: typing.Any) -> None:
        """Обновить метаданные не меняя состояние."""
        self._meta[user_id] = meta

    def clear(self, user_id: int) -> None:
        """Сбросить состояние пользователя."""
        self._states.pop(user_id, None)
        self._meta.pop(user_id, None)

    def has(self, user_id: int) -> bool:
        """Проверить наличие активного состояния."""
        return self.get(user_id) is not None

    def purge_expired(self) -> int:
        """Удалить все протухшие состояния. Возвращает количество удалённых."""
        now   = time.monotonic()
        stale = [uid for uid, (_, exp) in self._states.items() if exp < now]
        for uid in stale:
            self.clear(uid)
        return len(stale)

    def __len__(self) -> int:
        return sum(1 for uid in list(self._states) if self.get(uid) is not None)
