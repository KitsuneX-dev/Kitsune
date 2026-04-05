# ©️ Kitsune Userbot
# Основан на herokutl (форк Telethon) с DEFAULT_PORT=443 и поддержкой unix-сокетов.
# Совместим с Heroku-стилем патчинга через secure/patcher.py.

from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import time
import typing

from herokutl import TelegramClient
from herokutl import __name__ as __base_name__
from herokutl import helpers
from herokutl._updates import ChannelState, Entity, EntityType, SessionState
from herokutl.hints import EntityLike
from herokutl.network import MTProtoSender
from herokutl.tl import functions
from herokutl.tl.alltlobjects import LAYER
from herokutl.tl.functions.channels import GetFullChannelRequest
from herokutl.tl.functions.users import GetFullUserRequest
from herokutl.tl.tlobject import TLRequest
from herokutl.tl.types import (
    ChannelFull,
    Message,
    Updates,
    UpdatesCombined,
    UpdateShort,
    User,
    UserFull,
)
from herokutl.utils import is_list_like

if typing.TYPE_CHECKING:
    from .database.manager import DatabaseManager
    from .core.dispatcher import CommandDispatcher

logger = logging.getLogger(__name__)


# ─── Вспомогательные типы кэша ───────────────────────────────────────────────

def _hashable(value: typing.Any) -> bool:
    try:
        hash(value)
    except TypeError:
        return False
    return True


class CacheRecordEntity:
    def __init__(self, hashable_entity, resolved_entity: EntityLike, exp: int):
        self.entity = copy.deepcopy(resolved_entity)
        self._hashable_entity = copy.deepcopy(hashable_entity)
        self._exp = round(time.time() + exp)
        self.ts = time.time()

    @property
    def expired(self) -> bool:
        return self._exp < time.time()

    def __hash__(self) -> int:
        return hash(self._hashable_entity)

    def __eq__(self, other) -> bool:
        return hash(other) == hash(self)

    def __repr__(self) -> str:
        return f"CacheRecordEntity(entity={type(self.entity).__name__}, exp={self._exp})"


class CacheRecordPerms:
    def __init__(self, hashable_entity, hashable_user, resolved_perms, exp: int):
        self.perms = copy.deepcopy(resolved_perms)
        self._hashable_entity = copy.deepcopy(hashable_entity)
        self._hashable_user = copy.deepcopy(hashable_user)
        self._exp = round(time.time() + exp)
        self.ts = time.time()

    @property
    def expired(self) -> bool:
        return self._exp < time.time()

    def __hash__(self) -> int:
        return hash((self._hashable_entity, self._hashable_user))

    def __eq__(self, other) -> bool:
        return hash(other) == hash(self)


class CacheRecordFullChannel:
    def __init__(self, channel_id: int, full_channel: ChannelFull, exp: int):
        self.channel_id = channel_id
        self.full_channel = full_channel
        self._exp = round(time.time() + exp)
        self.ts = time.time()

    @property
    def expired(self) -> bool:
        return self._exp < time.time()


class CacheRecordFullUser:
    def __init__(self, user_id: int, full_user: UserFull, exp: int):
        self.user_id = user_id
        self.full_user = full_user
        self._exp = round(time.time() + exp)
        self.ts = time.time()

    @property
    def expired(self) -> bool:
        return self._exp < time.time()


# ─── Основной клиент ─────────────────────────────────────────────────────────

class KitsuneTelegramClient(TelegramClient):
    """
    Telethon-клиент на базе herokutl (DEFAULT_PORT=443).

    Ключевые отличия от стандартного TelegramClient:
    - connect() принимает unix_socket_path для работы через proxy-демон
      (используется вместе с secure/patcher.py при Docker-деплое)
    - Умный кэш entity / permissions / fullchannel / fulluser
    - Защита от принудительной подписки модулей через _forbidden_constructors
    - Сквозная передача raw-обновлений через raw_updates_processor
    """

    def __init__(self, session, *args, **kwargs):
        super().__init__(session, *args, **kwargs)

        # Кэши
        self._kitsune_entity_cache: typing.Dict[typing.Union[str, int], CacheRecordEntity] = {}
        self._kitsune_perms_cache: typing.Dict[typing.Union[str, int], typing.Dict] = {}
        self._kitsune_fullchannel_cache: typing.Dict[typing.Union[str, int], CacheRecordFullChannel] = {}
        self._kitsune_fulluser_cache: typing.Dict[typing.Union[str, int], CacheRecordFullUser] = {}

        # Защита конструкторов
        self._forbidden_constructors: typing.List[int] = []

        # Raw-обновления
        self._raw_updates_processor: typing.Optional[typing.Callable] = None

        # Публичные атрибуты (заполняются снаружи)
        self.tg_id: int = 0
        self.tg_me: typing.Optional[User] = None
        self.hydrogram: typing.Any = None
        self.kitsune_db: typing.Optional["DatabaseManager"] = None
        self.kitsune_dispatcher: typing.Optional["CommandDispatcher"] = None

    # ── connect() с поддержкой unix-сокета ───────────────────────────────────

    async def connect(self, unix_socket_path: typing.Optional[str] = None) -> None:
        """
        Подключается к Telegram.

        :param unix_socket_path: Путь до unix-сокета proxy-демона.
            Если задан — всё соединение идёт через него (нужен secure/patcher.py).
            Если None — стандартное TCP-подключение на порту 443.
        """
        if self.session is None:
            raise ValueError("KitsuneTelegramClient нельзя переиспользовать после logout")

        if self._loop is None:
            self._loop = helpers.get_running_loop()
        elif self._loop != helpers.get_running_loop():
            raise RuntimeError(
                "asyncio event loop не должен меняться после создания клиента "
                "(см. FAQ Telethon)"
            )

        connection = self._connection(
            self.session.server_address,
            self.session.port,
            self.session.dc_id,
            loggers=self._log,
            proxy=self._proxy,
            local_addr=self._local_addr,
        )

        # Если передан unix-сокет — патчим соединение (Heroku-стиль)
        if unix_socket_path is not None:
            if hasattr(connection, "set_unix_socket"):
                connection.set_unix_socket(unix_socket_path)
            else:
                logger.warning(
                    "connect: unix_socket_path задан, но ConnectionTcpFull "
                    "не поддерживает set_unix_socket — используй secure/patcher.py"
                )

        if not await self._sender.connect(connection):
            return  # Уже подключены

        self.session.auth_key = self._sender.auth_key
        self.session.save()

        if self._catch_up:
            ss = SessionState(0, 0, False, 0, 0, 0, 0, None)
            cs = []
            for entity_id, state in self.session.get_update_states():
                if entity_id == 0:
                    ss = SessionState(
                        0, 0, False,
                        state.pts, state.qts,
                        int(state.date.timestamp()),
                        state.seq, None,
                    )
                else:
                    cs.append(ChannelState(entity_id, state.pts))

            self._message_box.load(ss, cs)
            for state in cs:
                try:
                    entity = self.session.get_input_entity(state.channel_id)
                except ValueError:
                    self._log[__name__].warning(
                        "Нет access_hash в кэше для канала %s, catch-up пропущен",
                        state.channel_id,
                    )
                else:
                    self._mb_entity_cache.put(
                        Entity(EntityType.CHANNEL, entity.channel_id, entity.access_hash)
                    )

        self._init_request.query = functions.help.GetConfigRequest()
        req = self._init_request
        if self._no_updates:
            req = functions.InvokeWithoutUpdatesRequest(req)
        await self._sender.send(functions.InvokeWithLayerRequest(LAYER, req))

        if self._message_box.is_empty():
            me = await self.get_me()
            if me:
                await self._on_login(me)

        self._updates_handle = self.loop.create_task(self._update_loop())
        self._keepalive_handle = self.loop.create_task(self._keepalive_loop())

    # ── raw_updates_processor ─────────────────────────────────────────────────

    @property
    def raw_updates_processor(self) -> typing.Optional[typing.Callable]:
        return self._raw_updates_processor

    @raw_updates_processor.setter
    def raw_updates_processor(self, value: typing.Callable):
        if self._raw_updates_processor is not None:
            raise ValueError("raw_updates_processor уже установлен")
        if not callable(value):
            raise ValueError("raw_updates_processor должен быть callable")
        self._raw_updates_processor = value

    def _handle_update(
        self,
        update: typing.Union[Updates, UpdatesCombined, UpdateShort],
    ):
        if self._raw_updates_processor is not None:
            self._raw_updates_processor(update)
        super()._handle_update(update)

    # ── Кэш entity ───────────────────────────────────────────────────────────

    async def get_entity(
        self,
        entity: EntityLike,
        exp: int = 5 * 60,
        force: bool = False,
    ):
        """
        Получает entity с кэшированием.

        :param exp: Время жизни записи в секундах (0 = бесконечно)
        :param force: Принудительно обновить кэш
        """
        if not _hashable(entity):
            try:
                hashable_entity = next(
                    getattr(entity, attr)
                    for attr in ("user_id", "channel_id", "chat_id", "id")
                    if getattr(entity, attr, None)
                )
            except StopIteration:
                logger.debug("get_entity: не удалось получить hashable из %s, fallback", entity)
                return await super().get_entity(entity)
        else:
            hashable_entity = entity

        if str(hashable_entity).startswith("-100"):
            hashable_entity = int(str(hashable_entity)[4:])

        if (
            not force
            and hashable_entity
            and hashable_entity in self._kitsune_entity_cache
            and (
                not exp
                or self._kitsune_entity_cache[hashable_entity].ts + exp > time.time()
            )
        ):
            logger.debug("get_entity: кэш → %s", hashable_entity)
            return copy.deepcopy(self._kitsune_entity_cache[hashable_entity].entity)

        resolved = await super().get_entity(entity)

        if resolved:
            record = CacheRecordEntity(hashable_entity, resolved, exp)
            self._kitsune_entity_cache[hashable_entity] = record

            if getattr(resolved, "id", None):
                self._kitsune_entity_cache[resolved.id] = record

            if getattr(resolved, "username", None):
                self._kitsune_entity_cache[f"@{resolved.username}"] = record
                self._kitsune_entity_cache[resolved.username] = record

        return copy.deepcopy(resolved)

    async def force_get_entity(self, *args, **kwargs):
        """Принудительно запрашивает entity из API, игнорируя кэш."""
        return await self.get_entity(*args, force=True, **kwargs)

    def invalidate_entity(self, entity: typing.Union[int, str]) -> None:
        """Удаляет запись об entity из кэша."""
        self._kitsune_entity_cache.pop(entity, None)

    def purge_entity_cache(self) -> None:
        """Удаляет просроченные записи из кэша entity."""
        now = time.time()
        stale = [k for k, r in self._kitsune_entity_cache.items() if r.expired]
        for k in stale:
            del self._kitsune_entity_cache[k]

    # ── Кэш permissions ───────────────────────────────────────────────────────

    async def get_perms_cached(
        self,
        entity: EntityLike,
        user: typing.Optional[EntityLike] = None,
        exp: int = 5 * 60,
        force: bool = False,
    ):
        """Получает права пользователя в чате с кэшированием."""
        entity = await self.get_entity(entity)
        user = await self.get_entity(user) if user else None

        def _to_hashable(obj):
            if not _hashable(obj):
                try:
                    return next(
                        getattr(obj, a)
                        for a in ("user_id", "channel_id", "chat_id", "id")
                        if getattr(obj, a, None)
                    )
                except StopIteration:
                    return None
            return obj

        h_entity = _to_hashable(entity)
        h_user = _to_hashable(user)

        if h_entity and str(h_entity).isdigit() and int(h_entity) < 0:
            h_entity = int(str(h_entity)[4:])
        if h_user and str(h_user).isdigit() and int(h_user) < 0:
            h_user = int(str(h_user)[4:])

        if (
            not force
            and h_entity
            and h_user
            and h_user in self._kitsune_perms_cache.get(h_entity, {})
            and (
                not exp
                or self._kitsune_perms_cache[h_entity][h_user].ts + exp > time.time()
            )
        ):
            return copy.deepcopy(self._kitsune_perms_cache[h_entity][h_user].perms)

        resolved = await self.get_permissions(entity, user)

        if resolved and h_entity and h_user:
            record = CacheRecordPerms(h_entity, h_user, resolved, exp)
            self._kitsune_perms_cache.setdefault(h_entity, {})[h_user] = record

            def _save(key):
                if getattr(user, "id", None):
                    self._kitsune_perms_cache.setdefault(key, {})[user.id] = record
                if getattr(user, "username", None):
                    self._kitsune_perms_cache.setdefault(key, {})[f"@{user.username}"] = record
                    self._kitsune_perms_cache.setdefault(key, {})[user.username] = record

            if getattr(entity, "id", None):
                _save(entity.id)
            if getattr(entity, "username", None):
                _save(f"@{entity.username}")
                _save(entity.username)

        return copy.deepcopy(resolved)

    # ── Кэш FullChannel / FullUser ────────────────────────────────────────────

    async def get_fullchannel(
        self,
        entity: EntityLike,
        exp: int = 300,
        force: bool = False,
    ) -> ChannelFull:
        """Получает ChannelFull с кэшированием."""
        h = entity
        if not _hashable(entity):
            try:
                h = next(
                    getattr(entity, a)
                    for a in ("channel_id", "chat_id", "id")
                    if getattr(entity, a, None)
                )
            except StopIteration:
                return await self(GetFullChannelRequest(channel=entity))

        if str(h).isdigit() and int(h) < 0:
            h = int(str(h)[4:])

        if (
            not force
            and h in self._kitsune_fullchannel_cache
            and not self._kitsune_fullchannel_cache[h].expired
            and self._kitsune_fullchannel_cache[h].ts + exp > time.time()
        ):
            return self._kitsune_fullchannel_cache[h].full_channel

        result = await self(GetFullChannelRequest(channel=entity))
        self._kitsune_fullchannel_cache[h] = CacheRecordFullChannel(h, result, exp)
        return result

    async def get_fulluser(
        self,
        entity: EntityLike,
        exp: int = 300,
        force: bool = False,
    ) -> UserFull:
        """Получает UserFull с кэшированием."""
        h = entity
        if not _hashable(entity):
            try:
                h = next(
                    getattr(entity, a)
                    for a in ("user_id", "chat_id", "id")
                    if getattr(entity, a, None)
                )
            except StopIteration:
                return await self(GetFullUserRequest(entity))

        if str(h).isdigit() and int(h) < 0:
            h = int(str(h)[4:])

        if (
            not force
            and h in self._kitsune_fulluser_cache
            and not self._kitsune_fulluser_cache[h].expired
            and self._kitsune_fulluser_cache[h].ts + exp > time.time()
        ):
            return self._kitsune_fulluser_cache[h].full_user

        result = await self(GetFullUserRequest(entity))
        self._kitsune_fulluser_cache[h] = CacheRecordFullUser(h, result, exp)
        return result

    # ── Защита конструкторов ──────────────────────────────────────────────────

    def forbid_constructor(self, constructor: int) -> None:
        """Запрещает вызов TL-конструктора (для защиты от авто-подписок в модулях)."""
        self._forbidden_constructors = list(set(self._forbidden_constructors + [constructor]))

    def forbid_constructors(self, constructors: typing.List[int]) -> None:
        self._forbidden_constructors = list(set(self._forbidden_constructors + constructors))

    async def _call(
        self,
        sender: MTProtoSender,
        request: TLRequest,
        ordered: bool = False,
        flood_sleep_threshold: typing.Optional[int] = None,
    ):
        not_tuple = False
        if not is_list_like(request):
            not_tuple = True
            request = (request,)

        allowed = []
        for item in request:
            if item.CONSTRUCTOR_ID in self._forbidden_constructors:
                logger.debug(
                    "Заблокирован запрещённый конструктор %s (%s)",
                    item.__class__.__name__,
                    item.CONSTRUCTOR_ID,
                )
                continue
            allowed.append(item)

        if not allowed:
            return

        return await super()._call(
            sender,
            allowed[0] if not_tuple else tuple(allowed),
            ordered,
            flood_sleep_threshold,
        )

    # ── Topic guesser (отправка в треды) ─────────────────────────────────────

    @staticmethod
    def _find_msg_in_frame(chat_id: int, frame: inspect.FrameInfo) -> typing.Optional[Message]:
        return next(
            (
                obj
                for obj in frame.frame.f_locals.values()
                if isinstance(obj, Message)
                and getattr(obj.reply_to, "forum_topic", False)
                and chat_id == getattr(obj.peer_id, "channel_id", None)
            ),
            None,
        )

    async def _find_topic_in_stack(
        self,
        chat: EntityLike,
        stack: typing.List[inspect.FrameInfo],
    ) -> typing.Optional[int]:
        chat_id = (await self.get_entity(chat, exp=0)).id
        msg = next(
            (self._find_msg_in_frame(chat_id, fi) for fi in stack if self._find_msg_in_frame(chat_id, fi)),
            None,
        )
        if msg:
            return msg.reply_to.reply_to_top_id or msg.reply_to.reply_to_msg_id
        return None

    async def _topic_guesser(self, native, stack, *args, **kwargs):
        no_retry = kwargs.pop("_topic_no_retry", False)
        try:
            return await native(*args, **kwargs)
        except Exception as exc:
            if no_retry or "TopicDeleted" not in type(exc).__name__:
                raise
            topic = await self._find_topic_in_stack(args[0], stack)
            if not topic:
                raise
            kwargs["reply_to"] = topic
            kwargs["_topic_no_retry"] = True
            return await self._topic_guesser(native, stack, *args, **kwargs)

    async def send_message(self, *args, **kwargs) -> Message:
        return await self._topic_guesser(super().send_message, inspect.stack(), *args, **kwargs)

    async def send_file(self, *args, **kwargs) -> Message:
        return await self._topic_guesser(super().send_file, inspect.stack(), *args, **kwargs)
