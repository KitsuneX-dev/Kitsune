
from __future__ import annotations

import asyncio
import logging
import time
import typing

from telethon import TelegramClient
from telethon.sessions import SQLiteSession, MemorySession

logger = logging.getLogger(__name__)

_ENTITY_TTL = 300.0

class KitsuneTelegramClient(TelegramClient):

    def __init__(self, session: str | SQLiteSession | MemorySession, *args, **kwargs) -> None:
        super().__init__(session, *args, **kwargs)
        self.tg_id:     int          = 0
        self.tg_me:     typing.Any   = None
        self.hydrogram: typing.Any   = None
        self._entity_cache: dict[int | str, tuple[typing.Any, float]] = {}
        self._entity_lock = asyncio.Lock()

    async def get_entity_cached(self, entity: int | str) -> typing.Any:
        now = time.monotonic()
        async with self._entity_lock:
            cached = self._entity_cache.get(entity)
            if cached and now < cached[1]:
                return cached[0]

        result = await self.get_entity(entity)

        async with self._entity_lock:
            self._entity_cache[entity] = (result, now + _ENTITY_TTL)

        return result

    def invalidate_entity(self, entity: int | str) -> None:
        self._entity_cache.pop(entity, None)

    def purge_entity_cache(self) -> None:
        now = time.monotonic()
        stale = [k for k, (_, exp) in self._entity_cache.items() if now >= exp]
        for k in stale:
            del self._entity_cache[k]
