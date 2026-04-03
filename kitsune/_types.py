from __future__ import annotations

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
