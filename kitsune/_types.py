from __future__ import annotations
import time
import typing
from dataclasses import dataclass, field

@dataclass

class CommandMeta:
    name: str
    handler: typing.Callable
    required: int
    module_name: str = ""
@dataclass

class WatcherMeta:
    handler: typing.Callable
    filter_func: typing.Optional[typing.Callable]
    module_name: str = ""
@dataclass

class ModuleInfo:
    name: str
    description: str
    author: str
    version: str
    category: str
    commands: list[CommandMeta] = field(default_factory=list)
    is_builtin: bool = False
    source_url: str = ""
class KitsuneEvent:
    pass
@dataclass

class ModuleLoadedEvent(KitsuneEvent):
    module_name: str
    is_builtin: bool
@dataclass

class ModuleUnloadedEvent(KitsuneEvent):
    module_name: str
@dataclass

class ConfigChangedEvent(KitsuneEvent):
    module_name: str
    key: str
    old_value: typing.Any
    new_value: typing.Any
@dataclass

class PrefixChangedEvent(KitsuneEvent):
    old_prefix: str
    new_prefix: str
@dataclass

class SecurityChangedEvent(KitsuneEvent):
    action: str
    user_id: int
    role: str

class _CacheRecordBase:

    __slots__ = ("ts", "_exp")

    def __init__(self, exp: int) -> None:
        self.ts = time.time()
        self._exp = self.ts + exp

    @property
    def exp(self) -> float:
        return self._exp

    @property
    def expired(self) -> bool:
        return self._exp < time.time()
class CacheRecordEntity(_CacheRecordBase):
    __slots__ = ("entity", "_hashable_entity")

    def __init__(
        self,
        hashable_entity: typing.Any,
        resolved_entity: typing.Any,
        exp: int,
    ) -> None:
        super().__init__(exp)
        self.entity = resolved_entity
        self._hashable_entity = hashable_entity
    def __hash__(self) -> int:
        return hash(self._hashable_entity)
    def __eq__(self, other: typing.Any) -> bool:
        return isinstance(other, CacheRecordEntity) and hash(other) == hash(self)
    def __repr__(self) -> str:
        return (
            f"CacheRecordEntity(entity={type(self.entity).__name__}(...),"
            f" exp={round(self._exp)})"
        )
class CacheRecordPerms(_CacheRecordBase):
    __slots__ = ("perms", "_hashable_entity", "_hashable_user")

    def __init__(
        self,
        hashable_entity: typing.Any,
        hashable_user: typing.Any,
        resolved_perms: typing.Any,
        exp: int,
    ) -> None:
        super().__init__(exp)
        self.perms = resolved_perms
        self._hashable_entity = hashable_entity
        self._hashable_user = hashable_user
    def __hash__(self) -> int:
        return hash((self._hashable_entity, self._hashable_user))
    def __eq__(self, other: typing.Any) -> bool:
        return isinstance(other, CacheRecordPerms) and hash(other) == hash(self)
    def __repr__(self) -> str:
        return (
            f"CacheRecordPerms(perms={type(self.perms).__name__}(...),"
            f" exp={round(self._exp)})"
        )
class CacheRecordFullChannel(_CacheRecordBase):
    __slots__ = ("channel_id", "full_channel")

    def __init__(self, channel_id: typing.Any, full_channel: typing.Any, exp: int) -> None:
        super().__init__(exp)
        self.channel_id = channel_id
        self.full_channel = full_channel
    def __hash__(self) -> int:
        return hash(self.channel_id)
    def __eq__(self, other: typing.Any) -> bool:
        return isinstance(other, CacheRecordFullChannel) and hash(other) == hash(self)
    def __repr__(self) -> str:
        return (
            f"CacheRecordFullChannel(channel_id={self.channel_id},"
            f" exp={round(self._exp)})"
        )
class CacheRecordFullUser(_CacheRecordBase):
    __slots__ = ("user_id", "full_user")

    def __init__(self, user_id: typing.Any, full_user: typing.Any, exp: int) -> None:
        super().__init__(exp)
        self.user_id = user_id
        self.full_user = full_user
    def __hash__(self) -> int:
        return hash(self.user_id)
    def __eq__(self, other: typing.Any) -> bool:
        return isinstance(other, CacheRecordFullUser) and hash(other) == hash(self)
    def __repr__(self) -> str:
        return f"CacheRecordFullUser(user_id={self.user_id}, exp={round(self._exp)})"
