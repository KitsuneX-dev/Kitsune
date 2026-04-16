"""
Kitsune ← Hikka compatibility shim
====================================
Эмулирует пространства имён hikka.*, hikkatl.* и hikkapyro.*
так, чтобы модули, написанные для Hikka, загружались в Kitsune.

Структура шима повторяет публичный API Hikka:
  hikka.loader.Module          → KitsuneCompatHikkaModule
  hikka.loader.command         → совместимый декоратор команды
  hikka.loader.watcher         → совместимый декоратор наблюдателя
  hikka.loader.inline_handler  → совместимый декоратор inline-обработчика
  hikka.loader.callback_handler→ совместимый декоратор callback-обработчика
  hikka.loader.tds             → no-op декоратор (translatable docstrings)
  hikka.loader.ModuleConfig    → KitsuneModuleConfig (alias)
  hikka.loader.ConfigValue     → KitsuneConfigValue (alias)
  hikka.loader.validators      → заглушка validators
  hikka.utils.*                → Kitsune utils
  hikka.security.*             → Kitsune security constants

Добавление нового фреймворка — см. module_adapter.py.
"""
from __future__ import annotations

import logging
import sys
import types
import typing

logger = logging.getLogger(__name__)

_SHIM_APPLIED = False


# ─────────────────────────── совместимый базовый класс ───────────────────────

def _make_compat_module_base() -> type:
    """
    Создаёт KitsuneCompatHikkaModule — базовый класс для Hikka-модулей.

    Добавляет поверх KitsuneModule все методы, которые ожидают Hikka-модули:
      strings(key)  — с учётом _hikka_strings dict
      get / set     — хранение данных в БД
      lookup        — поиск другого загруженного модуля
      allmodules    — доступ ко всем модулям
    """
    from ..core.loader import KitsuneModule, ModuleConfig, ConfigValue

    class KitsuneCompatHikkaModule(KitsuneModule):
        """Базовый класс для модулей в стиле Hikka."""

        # Hikka-модули делают strings = {"name": "X", ...} — это перекрывает
        # метод strings() из KitsuneModule.  __init_subclass__ исправляет это.
        def __init_subclass__(cls, **kw: typing.Any) -> None:  # type: ignore[override]
            super().__init_subclass__(**kw)
            raw = cls.__dict__.get("strings")
            if raw is not None and isinstance(raw, dict):
                type.__setattr__(cls, "_hikka_strings", raw)
                type.__setattr__(cls, "strings", KitsuneCompatHikkaModule.strings)
                logger.debug(
                    "hikka_compat: fixed strings conflict for %s (%d keys)",
                    cls.__name__, len(raw),
                )

        def strings(self, key: str, **kwargs: typing.Any) -> str:  # type: ignore[override]
            db = getattr(self, "db", None)
            lang = db.get("kitsune.core", "lang", "ru") if db else "ru"
            candidates = [
                getattr(self, f"strings_{lang}", None) if lang != "en" else None,
                getattr(self, "strings_ru", None),
                getattr(self, "_hikka_strings", None),
            ]
            for d in candidates:
                if isinstance(d, dict) and key in d:
                    text = d[key]
                    return text.format(**kwargs) if kwargs else text
            return key

        def get(self, key: str, default: typing.Any = None) -> typing.Any:
            return self.db.get(f"hikka.{type(self).__name__}", key, default)

        def set(self, key: str, value: typing.Any) -> None:
            self.db.set(f"hikka.{type(self).__name__}", key, value)

        def lookup(self, name: str, *, include_dragon: bool = False) -> typing.Any:
            loader_obj = getattr(self.client, "_kitsune_loader", None)
            return loader_obj.get_module(name) if loader_obj else None

        @property
        def allmodules(self) -> typing.Any:  # type: ignore[misc]
            loader_obj = getattr(self.client, "_kitsune_loader", None)
            return loader_obj.modules if loader_obj else {}

        def __init__(self, client: typing.Any, db: typing.Any) -> None:
            super().__init__(client, db)

    return KitsuneCompatHikkaModule


# ─────────────────────────── декораторы ──────────────────────────────────────

def _command_decorator(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
    def _wrap(func: typing.Callable) -> typing.Callable:
        func.is_command    = True
        func._is_command   = True
        if args and isinstance(args[0], str):
            cmd_name = args[0]
        else:
            raw = func.__name__
            cmd_name = raw[:-4] if raw.endswith("_cmd") else (
                raw[:-3] if raw.endswith("cmd") else raw
            )
        func._command_name  = kwargs.get("name", cmd_name)
        func._required      = kwargs.get("required", 0)
        func._aliases       = list(kwargs.get("aliases") or [])
        return func

    if len(args) == 1 and callable(args[0]) and not kwargs:
        return _wrap(args[0])
    return _wrap


def _watcher_decorator(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
    def _wrap(func: typing.Callable) -> typing.Callable:
        func.is_watcher      = True
        func._is_watcher     = True
        func._watcher_filter = kwargs.get("filter_func", None)
        for k, v in kwargs.items():
            setattr(func, k, v)
        return func

    if len(args) == 1 and callable(args[0]) and not kwargs:
        return _wrap(args[0])
    return _wrap


def _inline_handler_decorator(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
    def _wrap(func: typing.Callable) -> typing.Callable:
        func.is_inline_handler  = True
        func._is_inline_handler = True
        return func

    if len(args) == 1 and callable(args[0]) and not kwargs:
        return _wrap(args[0])
    return _wrap


def _callback_handler_decorator(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
    def _wrap(func: typing.Callable) -> typing.Callable:
        func.is_callback_handler  = True
        func._is_callback_handler = True
        return func

    if len(args) == 1 and callable(args[0]) and not kwargs:
        return _wrap(args[0])
    return _wrap


def _tds(cls: type) -> type:
    """@loader.tds — no-op в Kitsune (строки поддерживаются нативно)."""
    return cls


def _loop_decorator(
    interval: int = 5,
    *,
    autostart: bool = False,
    wait_before: bool = False,
    stop_clause: typing.Any = None,
    **_: typing.Any,
) -> typing.Callable:
    def _wrap(func: typing.Callable) -> typing.Callable:
        func._is_loop        = True
        func._loop_interval  = interval
        func._loop_autostart = autostart
        return func
    return _wrap


# ─────────────────────────── заглушка validators ─────────────────────────────

class _ValidatorStub:
    """Минимальная заглушка Hikka-валидаторов."""
    class _Base:
        def validate(self, v: typing.Any) -> typing.Any:
            return v

    @staticmethod
    def String(**_: typing.Any) -> "_ValidatorStub._Base":    return _ValidatorStub._Base()
    @staticmethod
    def Integer(**_: typing.Any) -> "_ValidatorStub._Base":   return _ValidatorStub._Base()
    @staticmethod
    def Boolean(**_: typing.Any) -> "_ValidatorStub._Base":   return _ValidatorStub._Base()
    @staticmethod
    def Choice(**_: typing.Any) -> "_ValidatorStub._Base":    return _ValidatorStub._Base()
    @staticmethod
    def Emoji(**_: typing.Any) -> "_ValidatorStub._Base":     return _ValidatorStub._Base()
    @staticmethod
    def RegExp(**_: typing.Any) -> "_ValidatorStub._Base":    return _ValidatorStub._Base()
    @staticmethod
    def Float(**_: typing.Any) -> "_ValidatorStub._Base":     return _ValidatorStub._Base()
    @staticmethod
    def Series(**_: typing.Any) -> "_ValidatorStub._Base":    return _ValidatorStub._Base()
    @staticmethod
    def Hidden(**_: typing.Any) -> "_ValidatorStub._Base":    return _ValidatorStub._Base()
    @staticmethod
    def URL(**_: typing.Any) -> "_ValidatorStub._Base":       return _ValidatorStub._Base()


# ─────────────────────────── apply() ─────────────────────────────────────────

def apply() -> None:
    """Устанавливает Hikka-шимы в sys.modules (идемпотентно)."""
    global _SHIM_APPLIED
    if _SHIM_APPLIED:
        return

    from ..core.loader import ModuleConfig, ConfigValue
    from ..core.security import (
        OWNER, SUDO, SUPPORT, GROUP_OWNER, GROUP_ADMIN,
        GROUP_ADMIN_ANY, GROUP_MEMBER, PM, EVERYONE, BITMAP,
    )
    from .. import utils as kitsune_utils

    CompatModule = _make_compat_module_base()

    # ── hikka.loader ─────────────────────────────────────────────────────────
    loader_shim = types.ModuleType("hikka.loader")
    loader_shim.Module           = CompatModule
    loader_shim.command          = _command_decorator
    loader_shim.watcher          = _watcher_decorator
    loader_shim.inline_handler   = _inline_handler_decorator
    loader_shim.callback_handler = _callback_handler_decorator
    loader_shim.tds              = _tds
    loader_shim.translatable_docstring = _tds
    loader_shim.loop             = _loop_decorator
    loader_shim.ModuleConfig     = ModuleConfig
    loader_shim.ConfigValue      = ConfigValue
    loader_shim.validators       = _ValidatorStub
    loader_shim.owner            = OWNER
    loader_shim.group_owner      = GROUP_OWNER
    loader_shim.group_admin      = GROUP_ADMIN
    loader_shim.group_member     = GROUP_MEMBER
    loader_shim.pm               = PM
    loader_shim.unrestricted     = EVERYONE
    loader_shim.inline_everyone  = EVERYONE

    # ── hikka.security ───────────────────────────────────────────────────────
    security_shim = types.ModuleType("hikka.security")
    security_shim.OWNER           = OWNER
    security_shim.SUDO            = SUDO
    security_shim.SUPPORT         = SUPPORT
    security_shim.GROUP_OWNER     = GROUP_OWNER
    security_shim.GROUP_ADMIN     = GROUP_ADMIN
    security_shim.GROUP_ADMIN_ANY = GROUP_ADMIN_ANY
    security_shim.GROUP_MEMBER    = GROUP_MEMBER
    security_shim.PM              = PM
    security_shim.EVERYONE        = EVERYONE
    security_shim.BITMAP          = BITMAP
    security_shim.sudo            = SUDO
    security_shim.support         = SUPPORT

    # ── hikka.utils ──────────────────────────────────────────────────────────
    utils_shim = types.ModuleType("hikka.utils")
    utils_shim.escape_html     = kitsune_utils.escape_html
    utils_shim.chunks          = kitsune_utils.chunks
    utils_shim.run_sync        = kitsune_utils.run_sync
    utils_shim.find_caller     = kitsune_utils.find_caller
    utils_shim.is_serializable = kitsune_utils.is_serializable
    utils_shim.get_args        = kitsune_utils.get_args
    utils_shim.get_args_raw    = kitsune_utils.get_args_raw
    utils_shim.get_args_html   = kitsune_utils.get_args_html
    utils_shim.answer          = kitsune_utils.answer
    utils_shim.answer_file     = kitsune_utils.answer_file

    # ── hikka (корневой) ─────────────────────────────────────────────────────
    hikka_shim = types.ModuleType("hikka")
    hikka_shim.loader   = loader_shim
    hikka_shim.security = security_shim
    hikka_shim.utils    = utils_shim

    sys.modules["hikka"]          = hikka_shim
    sys.modules["hikka.loader"]   = loader_shim
    sys.modules["hikka.security"] = security_shim
    sys.modules["hikka.utils"]    = utils_shim

    # ── hikkatl → telethon ───────────────────────────────────────────────────
    try:
        import telethon
        sys.modules.setdefault("hikkatl",                 telethon)
        sys.modules.setdefault("hikkatl.tl",              telethon.tl)
        sys.modules.setdefault("hikkatl.tl.types",        telethon.tl.types)
        sys.modules.setdefault("hikkatl.tl.functions",    telethon.tl.functions)
        sys.modules.setdefault("hikkatl.extensions",      telethon.extensions)
        sys.modules.setdefault("hikkatl.extensions.html", telethon.extensions.html)
        sys.modules.setdefault("hikkatl.tl.tlobject",     telethon.tl.tlobject)
        sys.modules.setdefault("hikkatl.events",          telethon.events)
    except ImportError:
        logger.debug("hikka_compat: telethon not available")

    # ── hikkapyro → pyrogram / hydrogram ─────────────────────────────────────
    for _pyro in ("hydrogram", "pyrogram"):
        try:
            _m = __import__(_pyro)
            sys.modules.setdefault("hikkapyro", _m)
            break
        except ImportError:
            pass

    _SHIM_APPLIED = True
    logger.debug("hikka_compat: shims applied")
