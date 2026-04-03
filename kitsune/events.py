from __future__ import annotations

import asyncio
import logging
import typing
import weakref

from ._types import KitsuneEvent

logger = logging.getLogger(__name__)

_Handler = typing.Callable[[KitsuneEvent], typing.Awaitable[None]]


class EventBus:

    def __init__(self) -> None:
        self._handlers: dict[type, list[_Handler]] = {}
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: type, handler: _Handler) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)
            logger.debug("EventBus: subscribed %s to %s", handler.__qualname__, event_type.__name__)

    def unsubscribe(self, event_type: type, handler: _Handler) -> None:
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h is not handler
            ]

    def unsubscribe_all(self, module: typing.Any) -> None:
        for event_type in list(self._handlers):
            self._handlers[event_type] = [
                h for h in self._handlers[event_type]
                if getattr(h, "__self__", None) is not module
            ]

    async def emit(self, event: KitsuneEvent) -> None:
        event_type = type(event)
        handlers = self._handlers.get(event_type, [])

        if not handlers:
            return

        tasks = []
        for handler in handlers:
            tasks.append(asyncio.ensure_future(self._safe_call(handler, event)))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_call(self, handler: _Handler, event: KitsuneEvent) -> None:
        try:
            await handler(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "EventBus: unhandled exception in %s for event %s",
                handler.__qualname__,
                type(event).__name__,
            )

    def emit_sync(self, event: KitsuneEvent) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.emit(event))
        except RuntimeError:
            pass


bus: EventBus = EventBus()
