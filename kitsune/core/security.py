from __future__ import annotations

import asyncio
import logging
import time
import typing

logger = logging.getLogger(__name__)

OWNER                    = 1 << 0
SUDO                     = 1 << 1
SUPPORT                  = 1 << 2
GROUP_OWNER              = 1 << 3
GROUP_ADMIN_ADD_ADMINS   = 1 << 4
GROUP_ADMIN_CHANGE_INFO  = 1 << 5
GROUP_ADMIN_BAN_USERS    = 1 << 6
GROUP_ADMIN_DELETE_MSGS  = 1 << 7
GROUP_ADMIN_PIN_MESSAGES = 1 << 8
GROUP_ADMIN_INVITE_USERS = 1 << 9
GROUP_ADMIN              = 1 << 10
GROUP_MEMBER             = 1 << 11
PM                       = 1 << 12
EVERYONE                 = 1 << 13

BITMAP: dict[str, int] = {k: v for k, v in globals().items() if isinstance(v, int) and v > 0}

GROUP_ADMIN_ANY = (
    GROUP_ADMIN_ADD_ADMINS | GROUP_ADMIN_CHANGE_INFO | GROUP_ADMIN_BAN_USERS
    | GROUP_ADMIN_DELETE_MSGS | GROUP_ADMIN_PIN_MESSAGES | GROUP_ADMIN_INVITE_USERS
    | GROUP_ADMIN
)

DEFAULT_PERMISSIONS = OWNER
_CACHE_TTL = 60.0
_DB_KEY    = "kitsune.security"

class SecurityManager:

    def __init__(self, client: typing.Any, db: typing.Any) -> None:
        self._client = client
        self._db     = db
        self._me: typing.Any = None
        self._cache: dict[tuple[int, int], tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        self._me = await self._client.get_me()

    async def check(self, message: typing.Any, required: int) -> bool:
        if self._me is None:
            await self.init()

        sender_id: int = message.sender_id
        if sender_id is None:
            return False

        if sender_id == self._me.id and (required & OWNER):
            return True

        resolved = await self._resolve(message, sender_id)
        return bool(resolved & required)

    def get_sudo_users(self) -> list[int]:
        return self._db.get(_DB_KEY, "sudo", [])

    def get_support_users(self) -> list[int]:
        return self._db.get(_DB_KEY, "support", [])

    async def add_sudo(self, user_id: int) -> None:
        users = list(set(self.get_sudo_users() + [user_id]))
        await self._db.set(_DB_KEY, "sudo", users)

    async def remove_sudo(self, user_id: int) -> None:
        users = [u for u in self.get_sudo_users() if u != user_id]
        await self._db.set(_DB_KEY, "sudo", users)

    async def _resolve(self, message: typing.Any, sender_id: int) -> int:
        bits = 0

        if sender_id == self._me.id:
            bits |= OWNER

        if sender_id in self.get_sudo_users():
            bits |= SUDO
        if sender_id in self.get_support_users():
            bits |= SUPPORT

        chat_id = message.chat_id
        if chat_id is None:
            return bits

        if chat_id == sender_id:
            bits |= PM
        else:
            bits |= await self._resolve_group_bits(chat_id, sender_id)

        bits |= EVERYONE
        return bits

    async def _resolve_group_bits(self, chat_id: int, user_id: int) -> int:
        cache_key = (chat_id, user_id)
        now = time.monotonic()

        async with self._lock:
            if cache_key in self._cache:
                cached_bits, expires = self._cache[cache_key]
                if now < expires:
                    return cached_bits

        bits = GROUP_MEMBER
        try:
            from telethon.tl.types import (
                ChannelParticipantCreator,
                ChannelParticipantAdmin,
                ChatParticipantCreator,
                ChatParticipantAdmin,
            )
            participant = await self._client.get_permissions(chat_id, user_id)

            if getattr(participant, "is_creator", False):
                bits |= GROUP_OWNER
            if getattr(participant, "is_admin", False):
                bits |= GROUP_ADMIN
                rights = getattr(participant, "banned_rights", None) or getattr(
                    participant, "admin_rights", None
                )
                if rights:
                    if getattr(rights, "add_admins", False):
                        bits |= GROUP_ADMIN_ADD_ADMINS
                    if getattr(rights, "change_info", False):
                        bits |= GROUP_ADMIN_CHANGE_INFO
                    if getattr(rights, "ban_users", False):
                        bits |= GROUP_ADMIN_BAN_USERS
                    if getattr(rights, "delete_messages", False):
                        bits |= GROUP_ADMIN_DELETE_MSGS
                    if getattr(rights, "pin_messages", False):
                        bits |= GROUP_ADMIN_PIN_MESSAGES
                    if getattr(rights, "invite_users", False):
                        bits |= GROUP_ADMIN_INVITE_USERS
        except Exception:
            pass

        async with self._lock:
            self._cache[cache_key] = (bits, now + _CACHE_TTL)

        return bits

    def invalidate_cache(self, chat_id: int | None = None) -> None:
        if chat_id is None:
            self._cache.clear()
        else:
            for key in [k for k in self._cache if k[0] == chat_id]:
                del self._cache[key]
