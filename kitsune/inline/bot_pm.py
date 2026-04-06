"""
kitsune/inline/bot_pm.py — диалоги через личные сообщения боту (FSM).

Позволяет модулям запускать пошаговые диалоги с пользователем через
личку бота: бот задаёт вопрос → пользователь отвечает → следующий шаг.

Подключается как mixin к InlineManager.

Пример использования в модуле:
    async def my_cmd(self, event):
        inline = self.client._kitsune_inline
        if not inline:
            return

        await inline.ask(
            user_id=event.sender_id,
            question="Как тебя зовут?",
            handler=self._got_name,
        )

    async def _got_name(self, message, value):
        await message.reply(f"Привет, {value}!")
"""

from __future__ import annotations

import asyncio
import logging
import typing

from .events import FSMState

logger = logging.getLogger(__name__)


class BotPM:
    """
    Mixin — диалоги через личные сообщения боту.

    Требует в классе:
        self._bot           — aiogram Bot instance
        self._bot_username  — username бота (str)
        self._client        — Telethon client
        self._me            — Telegram ID владельца (int)
        _fsm                — экземпляр FSMState (создаётся автоматически)
    """

    # FSM — общий для всего InlineManager
    _fsm: FSMState = FSMState()

    # Словарь user_id → (handler, args, kwargs)
    _pm_handlers: dict[int, tuple[typing.Callable, tuple, dict]] = {}

    async def ask(
        self,
        user_id: int,
        question: str,
        handler: typing.Callable,
        *,
        args: tuple = (),
        kwargs: dict | None = None,
        timeout: int = 300,
        parse_mode: str = "HTML",
    ) -> bool:
        """
        Задать пользователю вопрос в личке бота и дождаться ответа.

        :param user_id:   ID пользователя Telegram.
        :param question:  Текст вопроса (отправляется в личку бота).
        :param handler:   async callable(message, value, *args, **kwargs)
                          вызывается с ответом пользователя.
        :param args:      Дополнительные аргументы для handler.
        :param kwargs:    Дополнительные kwargs для handler.
        :param timeout:   Через сколько секунд вопрос устаревает.
        :param parse_mode: Режим разметки вопроса.
        :return:          True если вопрос успешно отправлен.
        """
        if kwargs is None:
            kwargs = {}

        if not self._bot or not self._bot_username:
            logger.warning("BotPM.ask: бот не инициализирован")
            return False

        try:
            await self._bot.send_message(
                chat_id=user_id,
                text=question,
                parse_mode=parse_mode,
            )
        except Exception as exc:
            logger.warning("BotPM.ask: не удалось отправить вопрос: %s", exc)
            return False

        self._fsm.set(user_id, "waiting_answer", meta={
            "question": question,
            "timeout":  timeout,
        })
        self._pm_handlers[user_id] = (handler, args, kwargs)

        # Автоматически снять состояние по таймауту
        asyncio.ensure_future(self._auto_clear(user_id, timeout))
        return True

    async def _auto_clear(self, user_id: int, timeout: int) -> None:
        await asyncio.sleep(timeout)
        if self._fsm.get(user_id) == "waiting_answer":
            self._fsm.clear(user_id)
            self._pm_handlers.pop(user_id, None)
            logger.debug("BotPM: timeout for user %d, state cleared", user_id)

    async def _handle_pm_message(self, message: typing.Any) -> bool:
        """
        Обрабатывает входящее сообщение в личке бота.

        Вызывается из обработчика сообщений InlineManager.
        Возвращает True если сообщение было обработано как ответ на ask().
        """
        user_id = getattr(message, "from_user", None)
        if user_id is None:
            return False
        user_id = user_id.id

        if self._fsm.get(user_id) != "waiting_answer":
            return False

        entry = self._pm_handlers.pop(user_id, None)
        self._fsm.clear(user_id)

        if entry is None:
            return False

        handler, args, kwargs = entry
        value = message.text or ""

        try:
            await handler(message, value, *args, **kwargs)
        except Exception:
            logger.exception("BotPM: handler error for user %d", user_id)

        return True

    def set_fsm_state(
        self,
        user_id: int,
        state: str | None,
        meta: typing.Any = None,
    ) -> None:
        """
        Вручную установить или сбросить FSM-состояние пользователя.

        set_fsm_state(user_id, None) — сбросить.
        set_fsm_state(user_id, "my_state", meta={"step": 1}) — установить.
        """
        if state is None:
            self._fsm.clear(user_id)
            self._pm_handlers.pop(user_id, None)
        else:
            self._fsm.set(user_id, state, meta=meta)

    def get_fsm_state(self, user_id: int) -> str | None:
        """Получить текущее FSM-состояние пользователя."""
        return self._fsm.get(user_id)

    def get_fsm_meta(self, user_id: int) -> typing.Any:
        """Получить метаданные FSM-состояния."""
        return self._fsm.get_meta(user_id)

    def is_waiting(self, user_id: int) -> bool:
        """Проверяет, ожидает ли пользователь ответа на ask()."""
        return self._fsm.get(user_id) == "waiting_answer"
