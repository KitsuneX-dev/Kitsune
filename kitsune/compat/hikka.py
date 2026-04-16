from __future__ import annotations

import asyncio
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

        @property
        def tg_id(self) -> int:
            return getattr(self.client, "tg_id", 0) or 0

        @tg_id.setter
        def tg_id(self, value: int) -> None:
            pass

        @property
        def _tg_id(self) -> int:
            return getattr(self.client, "tg_id", 0) or 0

        @_tg_id.setter
        def _tg_id(self, value: int) -> None:
            pass

        @property
        def _client(self) -> typing.Any:
            return self.client

        @_client.setter
        def _client(self, value: typing.Any) -> None:
            self.client = value

        @property
        def _db(self) -> typing.Any:
            return self.db

        @_db.setter
        def _db(self, value: typing.Any) -> None:
            self.db = value

        @property
        def inline(self) -> typing.Any:
            return getattr(self, "_inline", None) or getattr(self.client, "_kitsune_inline", None)

        @property
        def bot_username(self) -> typing.Optional[str]:
            inline = self.inline
            return getattr(inline, "_bot_username", None) if inline else None

        @property
        def bot_id(self) -> typing.Optional[int]:
            inline = self.inline
            if inline and hasattr(inline, "_bot"):
                bot = inline._bot
                return getattr(bot, "id", None) if bot else None
            return None

        @property
        def commands(self) -> typing.Dict[str, typing.Any]:
            return {}

        @property
        def hikka_commands(self) -> typing.Dict[str, typing.Any]:
            return {}

        @property
        def inline_handlers(self) -> typing.Dict[str, typing.Any]:
            return {}

        @property
        def hikka_inline_handlers(self) -> typing.Dict[str, typing.Any]:
            return {}

        @property
        def callback_handlers(self) -> typing.Dict[str, typing.Any]:
            return {}

        @property
        def hikka_callback_handlers(self) -> typing.Dict[str, typing.Any]:
            return {}

        @property
        def watchers(self) -> typing.Dict[str, typing.Any]:
            return {}

        @property
        def hikka_watchers(self) -> typing.Dict[str, typing.Any]:
            return {}

        async def request_join(
            self,
            peer: typing.Any,
            reason: str,
            assure_joined: bool = False,
        ) -> bool:
            """
            Request to join a channel.
            :param peer: The channel to join.
            :param reason: The reason for joining.
            :param assure_joined: If set, module will not be loaded unless the required channel is joined.
            :return: Status of the request.
            """
            try:
                channel = await self.client.get_entity(peer)
            except Exception:
                return False

            if hasattr(channel, "left") and not channel.left:
                return True

            inline = self.inline
            if inline and hasattr(inline, "_bot_username"):
                bot_username = inline._bot_username
                if bot_username:
                    try:
                        await self.client.send_message(
                            bot_username,
                            f"Request to join {peer}: {reason}",
                        )
                    except Exception:
                        pass

            return True

        async def animate(
            self,
            message: typing.Any,
            frames: typing.List[str],
            interval: typing.Union[float, int],
            *,
            inline: bool = False,
        ) -> None:
            if interval < 0.1:
                interval = 0.1

            from .. import utils as kitsune_utils

            for frame in frames:
                if inline and hasattr(self, "inline") and self.inline:
                    try:
                        message = await self.inline.form(
                            message=message,
                            text=frame,
                            reply_markup={"text": " ", "data": "empty"},
                        )
                    except Exception:
                        pass
                else:
                    try:
                        message = await kitsune_utils.answer(message, frame)
                    except Exception:
                        pass

                await asyncio.sleep(interval)

            return message

        async def invoke(
            self,
            command: str,
            args: typing.Optional[str] = None,
            peer: typing.Optional[typing.Any] = None,
            message: typing.Optional[typing.Any] = None,
            edit: bool = False,
        ) -> typing.Any:
            loader_obj = getattr(self.client, "_kitsune_loader", None)
            if not loader_obj:
                raise ValueError("Loader not found")
            
            modules = loader_obj.modules
            commands_found = False
            for mod in modules.values():
                if hasattr(mod, "hikka_commands") and command in mod.hikka_commands:
                    commands_found = True
                    break
            
            if not commands_found:
                raise ValueError(f"Command {command} not found")

            prefix = loader_obj.get_prefix()
            cmd = f"{prefix}{command} {args or ''}".strip()

            if peer:
                message = await self.client.send_message(peer, cmd)
            elif message:
                if edit:
                    message = await message.edit(cmd)
                else:
                    message = await message.respond(cmd)

            return message

        def pointer(
            self,
            key: str,
            default: typing.Any = None,
            item_type: typing.Any = None,
        ) -> typing.Any:
            return self.db.pointer(type(self).__name__, key, default, item_type)

        async def _approve(self, call: typing.Any, channel: typing.Any, event: asyncio.Event) -> None:
            pass

        async def _decline(self, call: typing.Any, channel: typing.Any, event: asyncio.Event) -> None:
            pass

        def __init__(self, client: typing.Any, db: typing.Any) -> None:
            super().__init__(client, db)

        def internal_init(self) -> None:
            self._db = self.db
            self._client = self.client
            loader_obj = getattr(self.client, "_kitsune_loader", None)
            if loader_obj:
                self.lookup = loader_obj.get_module
                self.get_prefix = loader_obj.get_prefix
                self.inline = getattr(self.client, "_kitsune_inline", None)
                self._inline = self.inline
                self.allclients = getattr(self.client, "allclients", [])
            self.tg_id = getattr(self.client, "tg_id", 0) or 0
            self._tg_id = self.tg_id

        async def on_load(self) -> None:
            await super().on_load()
            # Hikka calls client_ready(client, db) instead of on_load()
            cr = None
            for klass in type(self).__mro__:
                if klass is KitsuneCompatHikkaModule:
                    break
                v = klass.__dict__.get("client_ready")
                if v is not None:
                    cr = v
                    break
            if cr is not None:
                import inspect as _inspect
                sig = _inspect.signature(cr)
                params = [p for p in sig.parameters if p != "self"]
                if len(params) >= 2:
                    await cr(self, self.client, self.db)
                elif len(params) == 1:
                    await cr(self, self.client)
                else:
                    await cr(self)

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
    #   from ..types import CoreOverwriteError  →  kitsune.types
    #   from ..inline.types import …  →   kitsune.inline.types
    #
    # Two things are required for `from .. import X` to work:
    #   1. sys.modules["kitsune.X"] must exist
    #   2. the kitsune package object must have attribute X
    # Without (2) CPython raises ImportError even when (1) is set.

    # --- kitsune.types shim (CoreOverwriteError & friends) ---
    _types_shim = sys.modules.get("kitsune.types")
    if _types_shim is None:
        _types_shim = types.ModuleType("kitsune.types")

    class CoreOverwriteError(Exception):
        """Stub: raised by Hikka when a core module is overwritten."""

    class SelfUnload(Exception):
        """Stub: module raises this to request its own unload."""

    class StopLoop(Exception):
        """Stub: raised inside a @loader.loop to stop iteration."""

    _types_shim.CoreOverwriteError = CoreOverwriteError  # type: ignore[attr-defined]
    _types_shim.SelfUnload         = SelfUnload           # type: ignore[attr-defined]
    _types_shim.StopLoop           = StopLoop             # type: ignore[attr-defined]

    sys.modules["kitsune.types"] = _types_shim

    # --- kitsune.loader / kitsune.utils / kitsune.security ---
    sys.modules.setdefault("kitsune.loader",   loader_shim)
    sys.modules.setdefault("kitsune.utils",    utils_shim)
    sys.modules.setdefault("kitsune.security", security_shim)

    # Bind as attributes on the live kitsune package object so that
    # `from .. import loader` resolves correctly at the C-level.
    _kitsune_pkg = sys.modules.get("kitsune")
    if _kitsune_pkg is not None:
        for _attr, _mod in (
            ("loader",   sys.modules["kitsune.loader"]),
            ("utils",    sys.modules["kitsune.utils"]),
            ("security", sys.modules["kitsune.security"]),
            ("types",    _types_shim),
        ):
            if not hasattr(_kitsune_pkg, _attr):
                setattr(_kitsune_pkg, _attr, _mod)
                logger.debug("hikka_compat: bound kitsune.%s onto package object", _attr)

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
