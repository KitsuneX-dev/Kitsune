from __future__ import annotations
import asyncio
import inspect
import logging
import socket
import time
import typing

from telethon import TelegramClient
from telethon.sessions import SQLiteSession, MemorySession
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.utils import is_list_like

from ._types import (
    CacheRecordEntity,
    CacheRecordFullChannel,
    CacheRecordFullUser,
    CacheRecordPerms,
)

logger = logging.getLogger(__name__)

_ENTITY_TTL = 300.0

_PERMS_TTL = 300.0

_FULL_TTL = 300.0

_ID_ATTRS = ("user_id", "channel_id", "chat_id", "id")

_KEEPALIVE_IDLE = 60
_KEEPALIVE_INTVL = 20
_KEEPALIVE_CNT = 5
_USER_TIMEOUT_MS = 30000


def _tune_socket(sock: socket.socket) -> None:
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (OSError, AttributeError):
        pass
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except (OSError, AttributeError):
        pass


    if hasattr(socket, "TCP_KEEPIDLE"):
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, _KEEPALIVE_IDLE)
        except OSError:
            pass
    if hasattr(socket, "TCP_KEEPINTVL"):
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, _KEEPALIVE_INTVL)
        except OSError:
            pass
    if hasattr(socket, "TCP_KEEPCNT"):
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, _KEEPALIVE_CNT)
        except OSError:
            pass
    if hasattr(socket, "TCP_USER_TIMEOUT"):
        try:
            sock.setsockopt(
                socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, _USER_TIMEOUT_MS
            )
        except OSError:
            pass
_PATCHED_OPEN_CONNECTION = False

def _install_socket_tuner() -> None:
    global _PATCHED_OPEN_CONNECTION
    if _PATCHED_OPEN_CONNECTION:
        return
    _orig = asyncio.open_connection
    async def _open_connection(*args, **kwargs):
        reader, writer = await _orig(*args, **kwargs)
        try:
            sock = writer.get_extra_info("socket")
            if sock is not None:
                _tune_socket(sock)
        except Exception:
            pass
        return reader, writer
    asyncio.open_connection = _open_connection
    _PATCHED_OPEN_CONNECTION = True
_install_socket_tuner()

def hashable(value: typing.Any) -> bool:
    try:
        hash(value)
    except TypeError:
        return False
    return True
def normalize_entity_key(value: typing.Any) -> typing.Any:
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return raw
        if raw.startswith(("http://", "https://", "t.me/", "tg://")):
            return raw.lower()
        candidate = raw[1:] if raw.startswith("@") else raw
        if candidate.lstrip("-").isdigit():
            value = int(candidate)
        else:
            return candidate.lower()
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value >= 0:
            return value
        digits = str(-value)
        if digits.startswith("100") and len(digits) > 3:
            return int(digits[3:])
        return -value
    return value
def _extract_id(entity: typing.Any) -> typing.Any:
    for attr in _ID_ATTRS:
        got = getattr(entity, attr, None)
        if got:
            return got
    return None
def _entity_keys(resolved: typing.Any) -> list[typing.Any]:
    keys: list[typing.Any] = []
    entity_id = getattr(resolved, "id", None)
    if entity_id:
        keys.append(normalize_entity_key(entity_id))
    username = getattr(resolved, "username", None)
    if username:
        keys.append(normalize_entity_key(username))
    for extra in getattr(resolved, "usernames", None) or []:
        extra_name = getattr(extra, "username", None) or extra
        if isinstance(extra_name, str) and extra_name:
            keys.append(normalize_entity_key(extra_name))
    phone = getattr(resolved, "phone", None)
    if isinstance(phone, str) and phone:
        keys.append(normalize_entity_key(f"+{phone.lstrip('+')}"))
    return keys
_MODULE_BASE: typing.Any = None

def _module_base() -> typing.Any:
    global _MODULE_BASE
    if _MODULE_BASE is None:
        try:
            from .core.loader import KitsuneModule
            _MODULE_BASE = KitsuneModule
        except Exception:
            _MODULE_BASE = False
    return _MODULE_BASE or None
def _called_from_external_module() -> typing.Any:
    base = _module_base()
    if base is None:
        return None
    frame = inspect.currentframe()
    try:
        depth = 0
        while frame is not None and depth < 60:
            frame = frame.f_back
            depth += 1
            if frame is None:
                break
            candidate = frame.f_locals.get("self")
            if candidate is None or not isinstance(candidate, base):
                continue
            if getattr(candidate, "_is_builtin", False):
                continue
            return candidate
    finally:
        del frame
    return None
class _HookedUpdatesQueue(asyncio.Queue):

    def __init__(self, client: "KitsuneTelegramClient", *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._kitsune_client = client
    def _run_processor(self, item: typing.Any) -> None:
        processor = getattr(self._kitsune_client, "_raw_updates_processor", None)
        if processor is None:
            return
        try:
            result = processor(item)
            if inspect.isawaitable(result):
                asyncio.ensure_future(result)
        except Exception:
            logger.exception("raw_updates_processor raised")
    def put_nowait(self, item: typing.Any) -> None:
        self._run_processor(item)
        super().put_nowait(item)
    async def put(self, item: typing.Any) -> None:
        self._run_processor(item)
        await super().put(item)
class KitsuneTelegramClient(TelegramClient):
    def __init__(self, session: str | SQLiteSession | MemorySession, *args, **kwargs) -> None:
        super().__init__(session, *args, **kwargs)
        self.tg_id:     int          = 0
        self.tg_me:     typing.Any   = None
        self.hydrogram: typing.Any   = None
        self._entity_cache:      dict[typing.Any, CacheRecordEntity] = {}
        self._perms_cache:       dict[typing.Any, dict[typing.Any, CacheRecordPerms]] = {}
        self._fullchannel_cache: dict[typing.Any, CacheRecordFullChannel] = {}
        self._fulluser_cache:    dict[typing.Any, CacheRecordFullUser] = {}
        self._forbidden_constructors: list[int] = []
        self._raw_updates_processor: typing.Optional[typing.Callable[[typing.Any], typing.Any]] = None
        self._entity_lock = asyncio.Lock()
        try:
            self._updates_queue = _HookedUpdatesQueue(self)
        except Exception:
            logger.debug("KitsuneTelegramClient: updates queue hook unavailable", exc_info=True)

    @property
    def entity_cache(self) -> dict[typing.Any, CacheRecordEntity]:
        return self._entity_cache

    @property
    def perms_cache(self) -> dict[typing.Any, dict[typing.Any, CacheRecordPerms]]:
        return self._perms_cache

    @property
    def fullchannel_cache(self) -> dict[typing.Any, CacheRecordFullChannel]:
        return self._fullchannel_cache

    @property
    def fulluser_cache(self) -> dict[typing.Any, CacheRecordFullUser]:
        return self._fulluser_cache

    @property
    def forbidden_constructors(self) -> list[int]:
        return list(self._forbidden_constructors)

    @property
    def raw_updates_processor(self) -> typing.Optional[typing.Callable[[typing.Any], typing.Any]]:
        return self._raw_updates_processor

    @raw_updates_processor.setter
    def raw_updates_processor(self, value: typing.Callable[[typing.Any], typing.Any]) -> None:
        if self._raw_updates_processor is not None:
            raise ValueError("raw_updates_processor is already set")
        if not callable(value):
            raise ValueError("raw_updates_processor must be callable")
        self._raw_updates_processor = value
    def _hashable_key(self, entity: typing.Any) -> typing.Any:
        if hashable(entity) and not hasattr(entity, "CONSTRUCTOR_ID"):
            return normalize_entity_key(entity)
        extracted = _extract_id(entity)
        if extracted is None:
            return None
        return normalize_entity_key(extracted)
    async def get_entity(
        self,
        entity: typing.Any,
        exp: int = int(_ENTITY_TTL),
        force: bool = False,
    ) -> typing.Any:
        if is_list_like(entity):
            return await super().get_entity(entity)
        key = self._hashable_key(entity)
        if key is None:
            logger.debug("tl_cache: no cache key for %r, resolving directly", entity)
            return await super().get_entity(entity)
        if not force:
            async with self._entity_lock:
                record = self._entity_cache.get(key)
                if record is not None and (not exp or record.ts + exp > time.time()):
                    return record.entity
                if record is not None:
                    self._entity_cache.pop(key, None)
        resolved = await super().get_entity(entity)
        if resolved is not None:
            record = CacheRecordEntity(key, resolved, exp or int(_ENTITY_TTL))
            async with self._entity_lock:
                self._entity_cache[key] = record
                for extra_key in _entity_keys(resolved):
                    self._entity_cache[extra_key] = record
        return resolved
    async def get_entity_cached(
        self,
        entity: typing.Any,
        exp: int = int(_ENTITY_TTL),
        force: bool = False,
    ) -> typing.Any:
        return await self.get_entity(entity, exp=exp, force=force)
    async def force_get_entity(self, entity: typing.Any, *args, **kwargs) -> typing.Any:
        return await self.get_entity(entity, *args, force=True, **kwargs)
    async def get_perms_cached(
        self,
        entity: typing.Any,
        user: typing.Any = None,
        exp: int = int(_PERMS_TTL),
        force: bool = False,
    ) -> typing.Any:
        entity_key = self._hashable_key(entity)
        user_key = self._hashable_key(user) if user is not None else None
        if entity_key is None or (user is not None and user_key is None):
            return await self.get_permissions(entity, user)
        if not force:
            async with self._entity_lock:
                record = self._perms_cache.get(entity_key, {}).get(user_key)
                if record is not None and (not exp or record.ts + exp > time.time()):
                    return record.perms
                if record is not None:
                    self._perms_cache.get(entity_key, {}).pop(user_key, None)
        resolved = await self.get_permissions(entity, user)
        if resolved is not None:
            record = CacheRecordPerms(entity_key, user_key, resolved, exp or int(_PERMS_TTL))
            async with self._entity_lock:
                self._perms_cache.setdefault(entity_key, {})[user_key] = record
        return resolved
    async def get_fullchannel(
        self,
        entity: typing.Any,
        exp: int = int(_FULL_TTL),
        force: bool = False,
    ) -> typing.Any:
        key = self._hashable_key(entity)
        if key is None:
            return await self(GetFullChannelRequest(channel=entity))
        if not force:
            record = self._fullchannel_cache.get(key)
            if record is not None and not record.expired and record.ts + exp > time.time():
                return record.full_channel
        result = await self(GetFullChannelRequest(channel=entity))
        self._fullchannel_cache[key] = CacheRecordFullChannel(
            key, result, exp or int(_FULL_TTL),
        )
        return result
    async def get_fulluser(
        self,
        entity: typing.Any,
        exp: int = int(_FULL_TTL),
        force: bool = False,
    ) -> typing.Any:
        key = self._hashable_key(entity)
        if key is None:
            return await self(GetFullUserRequest(id=entity))
        if not force:
            record = self._fulluser_cache.get(key)
            if record is not None and not record.expired and record.ts + exp > time.time():
                return record.full_user
        result = await self(GetFullUserRequest(id=entity))
        self._fulluser_cache[key] = CacheRecordFullUser(
            key, result, exp or int(_FULL_TTL),
        )
        return result
    def invalidate_entity(self, entity: typing.Any) -> None:
        key = self._hashable_key(entity)
        if key is None:
            return
        record = self._entity_cache.pop(key, None)
        if record is not None:
            for cached_key in [k for k, v in self._entity_cache.items() if v is record]:
                del self._entity_cache[cached_key]
            for extra_key in _entity_keys(record.entity):
                self._entity_cache.pop(extra_key, None)
        self._perms_cache.pop(key, None)
        for perms in self._perms_cache.values():
            perms.pop(key, None)
        self._fullchannel_cache.pop(key, None)
        self._fulluser_cache.pop(key, None)
    def purge_entity_cache(self) -> None:
        for cache in (self._entity_cache, self._fullchannel_cache, self._fulluser_cache):
            for key in [k for k, v in cache.items() if v.expired]:
                del cache[key]
        for entity_key in list(self._perms_cache):
            perms = self._perms_cache[entity_key]
            for user_key in [k for k, v in perms.items() if v.expired]:
                del perms[user_key]
            if not perms:
                del self._perms_cache[entity_key]
    def forbid_constructor(self, constructor: int) -> None:
        if constructor is None:
            return
        self._forbidden_constructors = sorted(
            set(self._forbidden_constructors) | {int(constructor)}
        )
    def forbid_constructors(self, constructors: typing.Iterable[int]) -> None:
        self._forbidden_constructors = sorted(
            {int(c) for c in constructors if c is not None}
        )
    def allow_constructor(self, constructor: int) -> None:
        self._forbidden_constructors = [
            c for c in self._forbidden_constructors if c != int(constructor)
        ]
    async def _call(
        self,
        sender: typing.Any,
        request: typing.Any,
        ordered: bool = False,
        flood_sleep_threshold: typing.Optional[int] = None,
    ) -> typing.Any:
        if not self._forbidden_constructors:
            return await super()._call(sender, request, ordered, flood_sleep_threshold)
        not_tuple = not is_list_like(request)
        requests = (request,) if not_tuple else tuple(request)
        allowed = []
        for item in requests:
            constructor_id = getattr(item, "CONSTRUCTOR_ID", None)
            if constructor_id in self._forbidden_constructors:
                offender = _called_from_external_module()
                if offender is not None:
                    logger.warning(
                        "🛡 Заблокирован %s из внешнего модуля %s",
                        type(item).__name__,
                        getattr(offender, "name", type(offender).__name__),
                    )
                    continue
            allowed.append(item)
        if not allowed:
            return None
        return await super()._call(
            sender,
            allowed[0] if not_tuple else tuple(allowed),
            ordered,
            flood_sleep_threshold,
        )
