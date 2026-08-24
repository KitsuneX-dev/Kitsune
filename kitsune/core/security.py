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

ALL = (1 << 14) - 1

_CACHE_TTL = 60.0

_DB_KEY    = "kitsune.security"


class SecurityGroup(typing.NamedTuple):

    name: str
    users: typing.List[int]
    permissions: typing.List[dict]

class SecurityManager:
    def __init__(self, client: typing.Any, db: typing.Any) -> None:
        self._client = client
        self._db     = db
        self._me: typing.Any = None
        self._me_id: int | None = None
        self._cache: dict[tuple[int, int], tuple[int, float]] = {}
        self._lock = asyncio.Lock()
        self._sgroups: dict[str, SecurityGroup] = {}
        self._tsec_user: list[typing.Any]
        self._tsec_chat: list[typing.Any]
        try:
            from ..pointers import PointerList
            self._tsec_user = PointerList(db, _DB_KEY, "tsec_user", [])
            self._tsec_chat = PointerList(db, _DB_KEY, "tsec_chat", [])
        except Exception:
            logger.exception("SecurityManager: failed to init tsec PointerLists")
            self._tsec_user = []
            self._tsec_chat = []
    async def init(self) -> None:
        cached_me = getattr(self._client, "tg_me", None)
        cached_id = getattr(self._client, "tg_id", None)
        if cached_me is not None:
            self._me = cached_me
            try:
                self._me_id = int(cached_me.id)
            except Exception:
                self._me_id = int(cached_id) if cached_id else None
        elif cached_id:
            try:
                self._me_id = int(cached_id)
            except Exception:
                self._me_id = None
        if self._me is None:
            try:
                me = await self._client.get_me()
            except Exception:
                logger.exception("SecurityManager.init: get_me() raised")
                me = None
            if me is not None:
                self._me = me
                try:
                    self._me_id = int(me.id)
                except Exception:
                    pass
                if not hasattr(self._client, "tg_me") or getattr(self._client, "tg_me", None) is None:
                    try:
                        self._client.tg_me = me
                    except Exception:
                        pass
                if not hasattr(self._client, "tg_id") or not getattr(self._client, "tg_id", None):
                    try:
                        self._client.tg_id = int(me.id)
                    except Exception:
                        pass
        if self._me_id is None:
            logger.warning(
                "SecurityManager.init: owner id is still unknown — "
                "OWNER permission checks will be unavailable until first successful get_me()."
            )
    async def _ensure_me(self) -> None:
        if self._me_id is not None:
            return
        cached_me = getattr(self._client, "tg_me", None)
        cached_id = getattr(self._client, "tg_id", None)
        if cached_me is not None and self._me is None:
            self._me = cached_me
        if cached_id and self._me_id is None:
            try:
                self._me_id = int(cached_id)
            except Exception:
                pass
        if self._me_id is None:
            await self.init()
    async def check(
        self,
        message: typing.Any,
        required: typing.Union[int, typing.Callable],
        *,
        command: str | None = None,
        module_name: str | None = None,
        inline_cmd: str | None = None,
        user_id: int | None = None,
    ) -> bool:
        await self._ensure_me()
        self._reload_rights()
        config = self.get_flags(required)
        if not config:
            return False
        if user_id is None:
            user_id = getattr(message, "sender_id", None)
        if user_id is None:
            return False
        if self._me_id is not None and user_id == self._me_id:
            return True
        if user_id in self._owner_ids():
            return True
        if user_id in (self._db.get("kitsune.main", "blacklist_users", []) or []):
            return False
        if message is None:
            return self._check_tsec_inline(user_id, inline_cmd or "") or bool(
                config & EVERYONE
            )
        try:
            from ..utils import get_chat_id
            chat_id = get_chat_id(message)
        except Exception:
            chat_id = getattr(message, "chat_id", None)
        if command or module_name:
            if self._match_tsec(user_id, chat_id, command, module_name):
                return True
        resolved = await self._resolve(message, user_id)
        return bool(resolved & config)
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
    @property
    def default(self) -> int:
        return self._db.get(_DB_KEY, "default", DEFAULT_PERMISSIONS)
    def _owner_ids(self) -> list[int]:
        owners: list[int] = []
        if self._me_id is not None:
            owners.append(self._me_id)
        co_owners = self._db.get(_DB_KEY, "co_owners", [])
        if isinstance(co_owners, list):
            owners.extend(int(o) for o in co_owners)
        return owners
    def apply_sgroups(self, sgroups: dict[str, SecurityGroup]) -> None:
        self._sgroups = sgroups or {}
    @property
    def sgroups(self) -> dict[str, SecurityGroup]:
        return self._sgroups
    @property
    def tsec_user(self):
        return self._tsec_user
    @property
    def tsec_chat(self):
        return self._tsec_chat
    def _reload_rights(self) -> None:
        now = time.time()
        for info in list(self._tsec_user):
            if info.get("expires") and info["expires"] < now:
                try:
                    self._tsec_user.remove(info)
                except ValueError:
                    pass
        for info in list(self._tsec_chat):
            if info.get("expires") and info["expires"] < now:
                try:
                    self._tsec_chat.remove(info)
                except ValueError:
                    pass
    def add_rule(
        self,
        target_type: str,
        target: typing.Any,
        rule: str,
        duration: int,
    ) -> None:
        if target_type not in {"chat", "user"}:
            raise ValueError(f"Invalid target_type: {target_type}")
        if all(
            not rule.startswith(rule_type)
            for rule_type in {"command", "module", "inline"}
        ):
            raise ValueError(f"Invalid rule: {rule}")
        if duration < 0:
            raise ValueError(f"Invalid duration: {duration}")
        from ..utils import get_display_name, get_entity_url
        (self._tsec_chat if target_type == "chat" else self._tsec_user).append(
            {
                "target": target.id,
                "rule_type": rule.split("/")[0],
                "rule": rule.split("/", maxsplit=1)[1],
                "expires": int(time.time() + duration) if duration else 0,
                "entity_name": get_display_name(target),
                "entity_url": get_entity_url(target),
            }
        )
    def remove_rules(self, target_type: str, target_id: int) -> bool:
        any_ = False
        pointer = self._tsec_user if target_type == "user" else (
            self._tsec_chat if target_type == "chat" else None
        )
        if pointer is None:
            return False
        for rule in list(pointer):
            if rule["target"] == target_id:
                pointer.remove(rule)
                any_ = True
        return any_
    def remove_rule(self, target_type: str, target_id: int, rule_cont: str) -> bool:
        any_ = False
        pointer = self._tsec_user if target_type == "user" else (
            self._tsec_chat if target_type == "chat" else None
        )
        if pointer is None:
            return False
        for rule in list(pointer):
            if rule["target"] == target_id and rule["rule"] == rule_cont:
                pointer.remove(rule)
                any_ = True
        return any_
    def get_flags(self, func: typing.Union[typing.Callable, int]) -> int:
        if isinstance(func, int):
            config = func
        else:
            config = self._db.get(_DB_KEY, "masks", {}).get(
                f"{func.__module__}.{func.__name__}",
                getattr(func, "security", getattr(func, "_required", None) or self.default),
            )
        if not isinstance(config, int):
            config = self.default
        if config & ~ALL and not config & EVERYONE:
            logger.error("Security config contains unknown bits: %s", config)
            return 0
        return config & self._db.get(_DB_KEY, "bounding_mask", ALL)
    def _check_tsec_inline(self, user_id: int, command: str) -> bool:
        return bool(command) and any(
            (
                rule["target"] == user_id
                and rule["rule_type"] == "inline"
                and rule["rule"] == command
            )
            for rule in self._tsec_user
        )
    def check_tsec(self, user_id: int, command: str) -> bool:
        for info in list(self._sgroups.values()):
            if user_id in info.users:
                for permission in info.permissions:
                    if (
                        permission["rule_type"] in {"command", "module"}
                        and permission["rule"] == command
                    ):
                        return True
        commands = self._commands_map()
        for info in list(self._tsec_user):
            if info["target"] == user_id and (
                info["rule_type"] == "command"
                and info["rule"] == command
                or info["rule_type"] == "module"
                and command in commands
                and info["rule"] == commands[command].__class__.__name__
            ):
                return True
        return False
    def _commands_map(self) -> dict:
        loader = getattr(self._client, "_kitsune_loader", None)
        if loader is None:
            return {}
        commands: dict = {}
        try:
            for mod in loader.get_modules().values():
                for attr in dir(mod):
                    if attr.startswith("__"):
                        continue
                    method = getattr(mod, attr, None)
                    cmd_name = getattr(method, "_command_name", None)
                    if cmd_name:
                        commands[cmd_name] = mod
        except Exception:
            logger.debug("SecurityManager: failed to build commands map", exc_info=True)
        return commands
    def _match_tsec(
        self,
        user_id: int,
        chat_id: int | None,
        command: str | None,
        module_name: str | None,
    ) -> bool:
        for info in list(self._sgroups.values()):
            if user_id in info.users:
                for permission in info.permissions:
                    if (
                        permission["rule_type"] == "command"
                        and command
                        and permission["rule"] == command
                    ):
                        logger.debug("sgroup match for command %s", command)
                        return True
                    if (
                        permission["rule_type"] == "module"
                        and module_name
                        and permission["rule"] == module_name
                    ):
                        logger.debug("sgroup match for module %s", module_name)
                        return True
        for info in list(self._tsec_user):
            if info["target"] == user_id:
                if info["rule_type"] == "command" and command and info["rule"] == command:
                    logger.debug("tsec user match for command %s", command)
                    return True
                if (
                    info["rule_type"] == "module"
                    and module_name
                    and info["rule"] == module_name
                ):
                    logger.debug("tsec user match for module %s", module_name)
                    return True
        if chat_id is not None:
            for info in list(self._tsec_chat):
                if info["target"] == chat_id:
                    if info["rule_type"] == "command" and command and info["rule"] == command:
                        logger.debug("tsec chat match for command %s", command)
                        return True
                    if (
                        info["rule_type"] == "module"
                        and module_name
                        and info["rule"] == module_name
                    ):
                        logger.debug("tsec chat match for module %s", module_name)
                        return True
        return False
    async def _resolve(self, message: typing.Any, sender_id: int) -> int:
        bits = 0
        if self._me_id is not None and sender_id == self._me_id:
            bits |= OWNER
        co_owners = self._db.get("kitsune.security", "co_owners", [])
        if isinstance(co_owners, list) and sender_id in co_owners:
            bits |= OWNER
        if sender_id in self.get_sudo_users():
            bits |= SUDO
        if sender_id in self.get_support_users():
            bits |= SUPPORT
        chat_id = getattr(message, "chat_id", None)
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
            get_perms = getattr(self._client, "get_perms_cached", None)
            if callable(get_perms):
                participant = await get_perms(chat_id, user_id)
            else:
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
