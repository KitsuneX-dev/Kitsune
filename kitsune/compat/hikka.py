from __future__ import annotations

import logging
import sys
import types
import typing

logger = logging.getLogger(__name__)

_SHIM_APPLIED = False

def _make_compat_module_base() -> type:
    from ..core.loader import KitsuneModule, ModuleConfig, ConfigValue

    class KitsuneCompatHikkaModule(KitsuneModule):

        def __init_subclass__(cls, **kw: typing.Any) -> None:  
            super().__init_subclass__(**kw)
            raw = cls.__dict__.get("strings")
            if raw is not None and isinstance(raw, dict):
                type.__setattr__(cls, "_hikka_strings", raw)
                type.__setattr__(cls, "strings", KitsuneCompatHikkaModule.strings)
                logger.debug(
                    "hikka_compat: fixed strings conflict for %s (%d keys)",
                    cls.__name__, len(raw),
                )

        def strings(self, key: str, **kwargs: typing.Any) -> str:  
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
        def allmodules(self) -> typing.Any:  
            loader_obj = getattr(self.client, "_kitsune_loader", None)
            return loader_obj.modules if loader_obj else {}

        def __init__(self, client: typing.Any, db: typing.Any) -> None:
            super().__init__(client, db)

    return KitsuneCompatHikkaModule

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

class _ValidatorStub:
    class _Base:
        def validate(self, v: typing.Any) -> typing.Any:
            return v

    @staticmethod
    def String(*_: typing.Any, **__: typing.Any) -> "_ValidatorStub._Base":    return _ValidatorStub._Base()
    @staticmethod
    def Integer(*_: typing.Any, **__: typing.Any) -> "_ValidatorStub._Base":   return _ValidatorStub._Base()
    @staticmethod
    def Boolean(*_: typing.Any, **__: typing.Any) -> "_ValidatorStub._Base":   return _ValidatorStub._Base()
    @staticmethod
    def Choice(*_: typing.Any, **__: typing.Any) -> "_ValidatorStub._Base":    return _ValidatorStub._Base()
    @staticmethod
    def Emoji(*_: typing.Any, **__: typing.Any) -> "_ValidatorStub._Base":     return _ValidatorStub._Base()
    @staticmethod
    def RegExp(*_: typing.Any, **__: typing.Any) -> "_ValidatorStub._Base":    return _ValidatorStub._Base()
    @staticmethod
    def Float(*_: typing.Any, **__: typing.Any) -> "_ValidatorStub._Base":     return _ValidatorStub._Base()
    @staticmethod
    def Series(*_: typing.Any, **__: typing.Any) -> "_ValidatorStub._Base":    return _ValidatorStub._Base()
    @staticmethod
    def Hidden(*_: typing.Any, **__: typing.Any) -> "_ValidatorStub._Base":    return _ValidatorStub._Base()
    @staticmethod
    def URL(*_: typing.Any, **__: typing.Any) -> "_ValidatorStub._Base":       return _ValidatorStub._Base()

def apply() -> None:
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

    # --- fallback for is_serializable (in case of outdated kitsune.utils) ---
    def _is_serializable_fallback(value: typing.Any) -> bool:
        import json
        try:
            json.dumps(value)
            return True
        except (TypeError, ValueError):
            return False

    def _safe_bind(shim: types.ModuleType, attr: str, source: typing.Any, fallback: typing.Any = None) -> None:
        val = getattr(source, attr, None)
        if val is None:
            if fallback is not None:
                setattr(shim, attr, fallback)
                logger.warning("hikka_compat: kitsune.utils.%s not found — using built-in fallback", attr)
            else:
                logger.warning("hikka_compat: kitsune.utils.%s not found — skipping (hikka modules may break)", attr)
            return
        setattr(shim, attr, val)

    utils_shim = types.ModuleType("hikka.utils")
    _safe_bind(utils_shim, "escape_html",     kitsune_utils)
    _safe_bind(utils_shim, "chunks",          kitsune_utils)
    _safe_bind(utils_shim, "run_sync",        kitsune_utils)
    _safe_bind(utils_shim, "find_caller",     kitsune_utils)
    _safe_bind(utils_shim, "is_serializable", kitsune_utils, _is_serializable_fallback)
    _safe_bind(utils_shim, "get_args",        kitsune_utils)
    _safe_bind(utils_shim, "get_args_raw",    kitsune_utils)
    _safe_bind(utils_shim, "get_args_html",   kitsune_utils)
    _safe_bind(utils_shim, "answer",          kitsune_utils)
    _safe_bind(utils_shim, "answer_file",     kitsune_utils)

    hikka_shim = types.ModuleType("hikka")
    hikka_shim.loader   = loader_shim
    hikka_shim.security = security_shim
    hikka_shim.utils    = utils_shim

    sys.modules["hikka"]          = hikka_shim
    sys.modules["hikka.loader"]   = loader_shim
    sys.modules["hikka.security"] = security_shim
    sys.modules["hikka.utils"]    = utils_shim

    # Hikka modules loaded as kitsune.modules.X do relative imports:
    #   from .. import loader, utils   →   kitsune.loader / kitsune.utils
    #   from ..inline.types import …  →   kitsune.inline.types
    # Register shims under those names so the imports resolve correctly.
    sys.modules.setdefault("kitsune.loader",   loader_shim)
    sys.modules.setdefault("kitsune.utils",    utils_shim)
    sys.modules.setdefault("kitsune.security", security_shim)

    # kitsune.inline.types  (used by ImageGen and similar modules)
    try:
        from ..inline import types as _inline_types  # type: ignore
        sys.modules.setdefault("kitsune.inline.types", _inline_types)
    except Exception:
        _inline_types_stub = types.ModuleType("kitsune.inline.types")

        class _InlineCall:  # minimal stub
            async def edit(self, *a, **kw): ...
            async def answer(self, *a, **kw): ...
            async def delete(self, *a, **kw): ...

        _inline_types_stub.InlineCall = _InlineCall
        sys.modules.setdefault("kitsune.inline",       types.ModuleType("kitsune.inline"))
        sys.modules.setdefault("kitsune.inline.types", _inline_types_stub)
        logger.warning("hikka_compat: kitsune.inline.types not found — using stub")

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

    for _pyro in ("hydrogram", "pyrogram"):
        try:
            _m = __import__(_pyro)
            sys.modules.setdefault("hikkapyro", _m)
            break
        except ImportError:
            pass

    _SHIM_APPLIED = True
    logger.debug("hikka_compat: shims applied")
