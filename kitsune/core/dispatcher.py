from __future__ import annotations

import asyncio
import logging
import typing

from herokutl import events

from .rate_limiter import RateLimiter
from .security import SecurityManager, OWNER, SUDO

logger = logging.getLogger(__name__)

_FLOOD_REPLY = "⏳ <b>Too fast. Please wait a moment.</b>"


class CommandDispatcher:

    def __init__(
        self,
        client: typing.Any,
        db: typing.Any,
        security: SecurityManager,
        prefix: str = ".",
    ) -> None:
        self._client   = client
        self._db       = db
        self._security = security
        self._prefix   = prefix
        self._limiter  = RateLimiter()
        self._loader: typing.Any = None

        self._commands: dict[str, tuple[typing.Callable, int]] = {}
        self._watchers: list[tuple[typing.Callable | None, typing.Callable]] = []

        self._client.add_event_handler(self._on_out_message,  events.NewMessage(outgoing=True))
        self._client.add_event_handler(self._on_in_message,   events.NewMessage(incoming=True))

    def register_command(self, name: str, handler: typing.Callable, required: int = OWNER) -> None:
        self._commands[name.lower()] = (handler, required)
        logger.debug("Dispatcher: registered command .%s (required=%d)", name, required)

    def unregister_command(self, name: str) -> None:
        self._commands.pop(name.lower(), None)

    def register_watcher(self, handler: typing.Callable, filter_func: typing.Callable | None = None) -> None:
        self._watchers.append((filter_func, handler))

    def unregister_watchers_for(self, module: typing.Any) -> None:
        self._watchers = [
            (f, h) for f, h in self._watchers
            if getattr(h, "__self__", None) is not module
        ]

    def set_prefix(self, prefix: str) -> None:
        self._prefix = prefix
        logger.info("Dispatcher: prefix changed to %r", prefix)

    def set_owner(self, owner_id: int) -> None:
        self._limiter.set_owner(owner_id)
        self._limiter.start_cleanup()

    async def _on_out_message(self, event: events.NewMessage.Event) -> None:
        await self._handle_message(event, is_own=True)

    async def _on_in_message(self, event: events.NewMessage.Event) -> None:
        message = event.message
        if not message or not message.text:
            return
        sender_id = message.sender_id
        if not sender_id or sender_id == self._client.tg_id:
            return
        sec = self._security
        sudo_users = sec.get_sudo_users() if sec else []
        co_owners  = self._db.get("kitsune.security", "co_owners", [])
        if sender_id not in sudo_users and sender_id not in co_owners:
            return
        await self._handle_message(event, is_own=False)

    async def _handle_message(self, event: events.NewMessage.Event, *, is_own: bool) -> None:
        message = event.message
        if not message or not message.text:
            return

        text: str = (message.raw_text or message.text or "").strip()

        if text.startswith(self._prefix):
            raw = text[len(self._prefix):]
            parts = raw.split(maxsplit=1)
            if not parts:
                return

            cmd_name = parts[0].lower().split("@")[0]
            entry = self._commands.get(cmd_name)
            if entry is None:
                return

            handler, required = entry

            if not is_own and required >= OWNER:
                return

            sender_id = message.sender_id or 0

            if not await self._limiter.check(sender_id, cmd_name):
                if is_own:
                    try:
                        await message.respond(_FLOOD_REPLY, parse_mode="html")
                    except Exception:
                        pass
                return

            try:
                allowed = await self._security.check(message, required)
            except Exception:
                logger.exception("Dispatcher: security check failed for .%s", cmd_name)
                return

            if not allowed:
                return

            await self._safe_call(handler, event, cmd_name)
            return

        if is_own:
            for filter_func, handler in list(self._watchers):
                try:
                    if filter_func is not None and not filter_func(message):
                        continue
                except Exception:
                    continue
                await self._safe_call(handler, event, f"watcher:{handler.__name__}")

    async def _safe_call(self, handler: typing.Callable, event: typing.Any, label: str) -> None:
        try:
            await handler(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Dispatcher: unhandled exception in %s", label)
