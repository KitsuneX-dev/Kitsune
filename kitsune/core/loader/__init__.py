from __future__ import annotations
import asyncio
import importlib
import importlib.util
import inspect
import logging
import sys
import typing
from pathlib import Path
from types import ModuleType

logger = logging.getLogger(__name__)


_BUILTIN_MODULES_DIR_CACHED: Path | None = None


class _SyncSetResult:

    __slots__ = ("_result", "_awaitable")

    def __init__(
        self,
        result: bool = True,
        awaitable: typing.Optional[typing.Awaitable[typing.Any]] = None,
    ) -> None:
        self._result = result
        self._awaitable = awaitable

    def __await__(self) -> typing.Generator[typing.Any, None, bool]:
        async def _coro() -> bool:
            if self._awaitable is not None:
                res = await self._awaitable
                return bool(res) if res is not None else True
            return self._result
        return _coro().__await__()

    def __bool__(self) -> bool:
        return bool(self._result)


def _sync_set(db: typing.Any, owner: str, key: str, value: typing.Any) -> _SyncSetResult:
    setter = getattr(db, "set_sync", None) or getattr(db, "force_set", None)
    if setter is not None:
        result = setter(owner, key, value)
        return _SyncSetResult(bool(result) if result is not None else True)
    coro = db.set(owner, key, value)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        task = loop.create_task(coro)
        return _SyncSetResult(True, awaitable=task)
    return _SyncSetResult(bool(asyncio.new_event_loop().run_until_complete(coro)))


def _get_builtin_modules_dir() -> Path:
    global _BUILTIN_MODULES_DIR_CACHED
    if _BUILTIN_MODULES_DIR_CACHED is not None:
        return _BUILTIN_MODULES_DIR_CACHED
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "kitsune" / "modules")
        candidates.append(Path(meipass) / "modules")
    try:
        candidates.append(Path(__file__).resolve().parent.parent / "modules")
    except (NameError, OSError):
        pass
    try:
        import kitsune as _kitsune_pkg
        pkg_file = getattr(_kitsune_pkg, "__file__", None)
        if pkg_file:
            candidates.append(Path(pkg_file).resolve().parent / "modules")
    except Exception:
        pass
    executable_dir = Path(sys.executable).resolve().parent
    candidates.append(executable_dir / "kitsune" / "modules")
    candidates.append(executable_dir / "modules")
    chosen: Path | None = None
    for cand in candidates:
        try:
            if cand.exists() and cand.is_dir():
                chosen = cand
                break
        except OSError:
            continue
    if chosen is None:
        chosen = candidates[0] if candidates else Path.cwd() / "modules"
    _BUILTIN_MODULES_DIR_CACHED = chosen
    return chosen

class _BuiltinModulesDirProxy:
    def __fspath__(self) -> str:
        return str(_get_builtin_modules_dir())
    def __str__(self) -> str:
        return str(_get_builtin_modules_dir())
    def __repr__(self) -> str:
        return repr(_get_builtin_modules_dir())
    def __truediv__(self, other: typing.Any) -> Path:
        return _get_builtin_modules_dir() / other
    def exists(self) -> bool:
        return _get_builtin_modules_dir().exists()
    def glob(self, pattern: str):
        return _get_builtin_modules_dir().glob(pattern)
    def iterdir(self):
        return _get_builtin_modules_dir().iterdir()
    def is_dir(self) -> bool:
        return _get_builtin_modules_dir().is_dir()
    def resolve(self) -> Path:
        return _get_builtin_modules_dir().resolve()
    @property
    def name(self) -> str:
        return _get_builtin_modules_dir().name
    @property
    def parent(self) -> Path:
        return _get_builtin_modules_dir().parent

_BUILTIN_MODULES_DIR = _BuiltinModulesDirProxy()

class ModuleLoadError(Exception):
    pass
class ASTSecurityError(ModuleLoadError):
    pass


class LegacyApiError(ModuleLoadError):
    pass


from . import ast_scanner as _ast_scanner  
from . import dependency_resolver as _dependency_resolver  
from . import disk_cache as _disk_cache  
from .ast_scanner import (  
    LEGACY_API_BLOCK_MESSAGE,
    _ALIAS_TRACKED_MODULES,
    _AST_CACHE_MAX_SIZE,
    _ASYNC_SUBPROCESS_ATTRS,
    _ASTScanner,
    _BLOCKED_ATTRS,
    _BLOCKED_IMPORTS,
    _DANGEROUS_OS_ATTRS,
    _DESTRUCTIVE_ATTR_NAMES,
    _DESTRUCTIVE_ATTRS,
    _FORMAT_METHODS,
    _HARD_ATTR_NAMES,
    _HARD_DUNDER_ATTRS,
    _HARD_ESCAPE_ATTRS,
    _INDIRECT_ATTR_HELPERS,
    _INTROSPECTION_ATTRS,
    _KITSUNE_API_NAMES,
    _MODULE_REGISTRY_METHODS,
    _SANDBOX_ESCAPE_ATTRS,
    _SENSITIVE_ATTR_NAMES,
    _SENSITIVE_MODULE_KEYS,
    _SENSITIVE_PATH_HINTS,
    _SOFT_ATTR_NAMES,
    _SOFT_ESCAPE_ATTRS,
    _WILDCARD_BLOCKED_MODULES,
    _ast_cache,
    _ast_cache_clear,
    _scan_ast,
    _scan_ast_with_cache,
    detect_legacy_api,
)
from .disk_cache import (  
    _AST_SCAN_OK_FILENAME,
    _AST_SCAN_OK_FLUSH_EVERY,
    _AST_SCAN_OK_MAX_SIZE,
    _ast_scan_ok_path,
    _load_ast_scan_cache,
    _remember_ast_scan_ok,
    flush_ast_scan_cache,
)
from .dependency_resolver import (  
    _IMPORT_TO_PIP,
    _LAST_PIP_STDERR,
    _PIP_INSTALL_TIMEOUT,
    _PIP_STDERR_TAIL,
    _SYSTEM_UTIL_TO_PKG,
    _build_pip_base_cmd,
    _ensure_pip_deps,
    _ensure_system_deps,
    _extract_missing_package,
    _is_permission_error,
    _is_termux,
    _pip_install,
    _record_pip_stderr,
    _run_cmd,
    _system_install,
    get_last_pip_stderr,
)


_LOADER_SUBMODULES = (_ast_scanner, _disk_cache, _dependency_resolver)


def _detect_legacy_or_raise(source: str, *, origin: str = "<module>") -> None:
    legacy = detect_legacy_api(source)
    if not legacy:
        return
    logger.warning(
        "Loader: blocked incompatible legacy (Hikka/Heroku) module %s: %s",
        origin, legacy,
    )
    raise LegacyApiError(LEGACY_API_BLOCK_MESSAGE)


class _LoaderPackage(ModuleType):

    def __setattr__(self, name: str, value: typing.Any) -> None:
        for _mod in _LOADER_SUBMODULES:
            if hasattr(_mod, name):
                setattr(_mod, name, value)
        super().__setattr__(name, value)

    def __getattr__(self, name: str) -> typing.Any:
        for _mod in _LOADER_SUBMODULES:
            try:
                return getattr(_mod, name)
            except AttributeError:
                continue
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


sys.modules[__name__].__class__ = _LoaderPackage


class ConfigValue:
    def __init__(
        self,
        key: str,
        default: typing.Any = None,
        doc: str = "",
        validator: typing.Any = None,
        on_change: typing.Callable[[], typing.Any] | None = None,
    ) -> None:
        self.key = key
        self.default = default
        self.doc = doc
        self.validator = validator
        self.on_change = on_change
        self.value = default
    def set(self, raw_value: typing.Any) -> None:
        if self.validator is not None:
            from ...validators import ValidationError
            try:
                self.value = self.validator.validate(raw_value)
            except ValidationError:
                raise
        else:
            self.value = raw_value
        if self.on_change is None:
            return
        try:
            result = self.on_change()
            if inspect.isawaitable(result):
                import asyncio as _asyncio
                coro = typing.cast("typing.Coroutine[typing.Any, typing.Any, typing.Any]", result)
                try:
                    _asyncio.get_running_loop().create_task(coro)
                except RuntimeError:
                    coro.close()
        except Exception:
            logger.exception("ConfigValue(%s): on_change raised", self.key)
class ModuleConfig:
    def __init__(self, *values: ConfigValue) -> None:
        self._config: dict[str, ConfigValue] = {v.key: v for v in values}
    def __getitem__(self, key: str) -> typing.Any:
        return self._config[key].value
    def __setitem__(self, key: str, value: typing.Any) -> None:
        self._config[key].set(value)
    def __contains__(self, key: object) -> bool:
        return key in self._config
    def __iter__(self):
        return iter(self._config)
    def keys(self):
        return self._config.keys()
    def items(self):
        return {k: v.value for k, v in self._config.items()}.items()
    def get_default(self, key: str) -> typing.Any:
        return self._config[key].default
    def get_doc(self, key: str) -> str:
        return self._config[key].doc
    def get_validator(self, key: str) -> typing.Any:
        return self._config[key].validator
    def get_config_value(self, key: str) -> ConfigValue:
        return self._config[key]
class KitsuneModule:
    name: str = ""
    description: str = ""
    author: str = ""
    version: str = "1.0"
    icon: str = "📦"
    category: str = "other"
    requires: typing.ClassVar[list[str]] = []

    pip_requires: typing.ClassVar[list[str]] = []

    system_requires: typing.ClassVar[list[str]] = []
    def __init__(self, client: typing.Any, db: typing.Any) -> None:
        self.client = client
        self.db = db
        self.tg_id: int = 0
        self.inline: typing.Any = None
        if not hasattr(self, "config"):
            self.config: ModuleConfig | None = None
    async def on_load(self) -> None:
        pass
    async def on_unload(self) -> None:
        pass
    def get_args(self, event: "typing.Any") -> str:
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        prefix = dispatcher._prefix if dispatcher else "."
        text = (
            getattr(event.message, "_kitsune_alias_text", None)
            or event.message.raw_text
            or event.message.text
            or ""
        )
        if text.startswith(prefix):
            remainder = text[len(prefix):].lstrip()
            parts = remainder.split(maxsplit=1)
            return parts[1] if len(parts) > 1 else ""
        return ""
    def strings(self, key: str, **kwargs: typing.Any) -> str:
        db = getattr(self, "db", None)
        lang = db.get("kitsune.core", "lang", "ru") if db else "ru"
        strings_key = f"strings_{lang}"
        strings = getattr(self, strings_key, None) or getattr(self, "strings_ru", None) or getattr(self, "strings_en", {})
        text: typing.Any = None
        if isinstance(strings, dict) and key in strings:
            text = strings[key]
        if text is None:
            translator = getattr(getattr(self, "client", None), "_kitsune_translator", None)
            if translator is not None:
                try:
                    translator.set_language(lang)
                    qual = f"{type(self).__module__}.{type(self).__name__}"
                    found = translator.get_module_string(qual, key, lang)
                    if found is None:
                        found = translator.get_module_string(type(self).__name__, key, lang)
                    if found is not None:
                        text = found
                except Exception:
                    pass
        if text is None:
            text = strings.get(key, key) if isinstance(strings, dict) else key
        dispatcher = getattr(getattr(self, "client", None), "_kitsune_dispatcher", None)
        prefix = dispatcher._prefix if dispatcher else "."
        if prefix != ".":
            import re as _re
            text = _re.sub(
                r'(<code>)\.([\w])',
                lambda m: m.group(1) + prefix + m.group(2),
                text,
            )
        return text.format(**kwargs) if kwargs else text
    def _load_config_from_db(self) -> None:
        if self.config is None:
            return
        db_key = f"kitsune.config.{self.name.lower()}"
        for key in self.config.keys():
            saved = self.db.get(db_key, key, None)
            if saved is not None:
                try:
                    self.config[key] = saved
                except Exception:
                    pass
    def get_prefix(self, userbot: typing.Optional[str] = None) -> str:
        loader = getattr(self.client, "_kitsune_loader", None)
        if loader is not None and hasattr(loader, "get_prefix"):
            return loader.get_prefix(userbot)
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        return dispatcher._prefix if dispatcher else "."
    def lookup(self, name: str) -> typing.Optional["KitsuneModule"]:
        loader = getattr(self.client, "_kitsune_loader", None)
        if loader is None:
            return None
        module = loader.get_module(name)
        if module is not None:
            return module
        target = name.lower()
        for mod in loader.modules.values():
            if type(mod).__name__.lower() == target:
                return mod
        return None
    def get(self, key: str, default: typing.Any = None) -> typing.Any:
        return self.db.get(type(self).__name__, key, default)
    def set(self, key: str, value: typing.Any) -> "_SyncSetResult":
        return _sync_set(self.db, type(self).__name__, key, value)
    def pointer(
        self,
        key: str,
        default: typing.Any = None,
        item_type: typing.Any = None,
    ) -> typing.Any:
        return self.db.pointer(type(self).__name__, key, default, item_type)
    async def invoke(
        self,
        command: str,
        args: typing.Optional[str] = None,
        peer: typing.Any = None,
        message: typing.Any = None,
        edit: bool = False,
    ) -> typing.Any:
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        if dispatcher is None:
            raise RuntimeError("invoke: dispatcher is not available")
        entry = dispatcher._commands.get(command.lower())
        if entry is None:
            raise ValueError(f"Command {command} not found")
        if message is None and peer is None:
            raise ValueError("Either peer or message must be specified")
        cmd = f"{self.get_prefix()}{command} {args or ''}".strip()
        if peer is not None:
            sent = await self.client.send_message(peer, cmd)
        else:
            target = typing.cast(typing.Any, message)
            sent = await target.edit(cmd) if edit else await target.respond(cmd)
        handler = entry[0]
        from telethon import events as _tl_events
        ev = _tl_events.NewMessage.Event(sent)
        ev._client = self.client
        await handler(ev)
        return sent
    async def animate(
        self,
        message: typing.Any,
        frames: typing.List[str],
        interval: typing.Union[float, int],
        *,
        inline: bool = False,
    ) -> typing.Any:
        from ... import utils
        if interval < 0.1:
            logger.warning(
                "animate: interval raised to 0.1s to avoid floodwaits"
            )
            interval = 0.1
        inline_api = getattr(self.client, "_kitsune_inline", None) or getattr(
            self.client, "inline", None
        )
        for frame in frames:
            is_inline_msg = type(message).__name__ == "InlineMessage"
            if is_inline_msg and inline:
                await message.edit(frame)
            elif inline and inline_api is not None:
                message = await inline_api.form(
                    text=frame,
                    message=message,
                    reply_markup={"text": "\u0020\u2800", "data": "empty"},
                )
            else:
                message = await utils.answer(message, frame)
            await asyncio.sleep(interval)
        return message
    async def request_join(
        self,
        peer: typing.Any,
        reason: str,
        assure_joined: typing.Optional[bool] = False,
    ) -> bool:
        from ... import utils
        from telethon.tl.types import Channel

        inline_api = getattr(self.client, "_kitsune_inline", None) or getattr(
            self.client, "inline", None
        )
        if inline_api is None:
            raise RuntimeError("request_join: inline bot is not available")

        channel = await self.client.get_entity(peer)
        declined = self.db.get("kitsune.main", "declined_joins", [])
        if getattr(channel, "id", None) in declined:
            if assure_joined:
                raise RuntimeError(
                    f"You need to join @{getattr(channel, 'username', '?')} "
                    "in order to use this module"
                )
            return False
        if not isinstance(channel, Channel):
            raise TypeError("`peer` field must be a channel")
        if not getattr(channel, "left", True):
            return True

        event = asyncio.Event()
        event.status = False  

        async def _approve(call: typing.Any) -> None:
            try:
                from telethon.tl.functions.channels import JoinChannelRequest
                await self.client(JoinChannelRequest(channel))
            except Exception:
                logger.debug("request_join: join failed", exc_info=True)
            event.status = True  
            event.set()
            try:
                await call.edit(
                    f"\u2705 Joined <b>{utils.escape_html(channel.title)}</b>"
                )
            except Exception:
                pass

        async def _decline(call: typing.Any) -> None:
            await self.db.set(
                "kitsune.main",
                "declined_joins",
                list(set(declined + [channel.id])),
            )
            event.status = False  
            event.set()
            try:
                await call.edit(
                    f"\u2716\ufe0f Declined joining "
                    f"<b>{utils.escape_html(channel.title)}</b>"
                )
            except Exception:
                pass

        await inline_api.form(
            text=(
                f"\U0001f465 Module <b>{type(self).__name__}</b> requests to join "
                f"<b>{utils.escape_html(channel.title)}</b>\n\n"
                f"<b>Reason:</b> {utils.escape_html(reason)}"
            ),
            message=self.tg_id,
            reply_markup=[
                {"text": "\U0001f4ab Approve", "callback": _approve},
                {"text": "\u2716\ufe0f Decline", "callback": _decline},
            ],
        )
        await event.wait()
        if assure_joined and not event.status:  
            raise RuntimeError(
                f"You need to join @{getattr(channel, 'username', '?')} "
                "in order to use this module"
            )
        return bool(event.status)  
class StopLoop(Exception):
    pass


async def _loop_stop_placeholder() -> bool:
    return True


class InfiniteLoop:

    def __init__(
        self,
        func: typing.Callable,
        interval: int,
        autostart: bool,
        wait_before: bool,
        stop_clause: typing.Optional[str],
    ) -> None:
        self.func = func
        self.interval = interval
        self.autostart = autostart
        self._wait_before = wait_before
        self._stop_clause = stop_clause
        self.status = False
        self._module_instance: typing.Any = None
        self._instance_ready = asyncio.Event()
        self._task: typing.Optional["asyncio.Task"] = None
        self._wait_for_stop = asyncio.Event()

    @property
    def module_instance(self) -> typing.Any:
        return self._module_instance

    @module_instance.setter
    def module_instance(self, value: typing.Any) -> None:
        self._module_instance = value
        if value is None:
            self._instance_ready.clear()
        else:
            self._instance_ready.set()

    def _db_owner(self) -> str:
        name = getattr(self.module_instance, "name", None) or type(
            self.module_instance
        ).__name__
        return f"kitsune.loop.{name.lower()}"

    def _flag_set(self, value: bool) -> None:
        db = getattr(self.module_instance, "db", None)
        if db is None or not self._stop_clause:
            return
        try:
            db.set_sync(self._db_owner(), self._stop_clause, value)
        except Exception:
            logger.debug("InfiniteLoop: could not set stop_clause flag", exc_info=True)

    def _flag_get(self) -> bool:
        db = getattr(self.module_instance, "db", None)
        if db is None or not self._stop_clause:
            return True
        try:
            return bool(db.get(self._db_owner(), self._stop_clause, False))
        except Exception:
            return False

    def _on_task_done(self, *_: typing.Any) -> None:
        self._wait_for_stop.set()

    def start(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        if self._task is None:
            logger.debug("Started loop for method %s", self.func)
            self._task = asyncio.ensure_future(self.actual_loop(*args, **kwargs))
        else:
            logger.debug("Attempted to start already running loop %s", self.func)

    def stop(self, *args: typing.Any, **kwargs: typing.Any) -> "asyncio.Future":
        if self._task:
            logger.debug("Stopped loop for method %s", self.func)
            self._wait_for_stop = asyncio.Event()
            self.status = False
            task = self._task
            self._task = None
            task.add_done_callback(self._on_task_done)
            task.cancel()
            return asyncio.ensure_future(self._wait_for_stop.wait())
        logger.debug("Loop %s is not running", self.func)
        return asyncio.ensure_future(_loop_stop_placeholder())

    async def actual_loop(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        await self._instance_ready.wait()

        if isinstance(self._stop_clause, str) and self._stop_clause:
            self._flag_set(True)

        self.status = True

        try:
            while self.status:
                if self._wait_before:
                    await asyncio.sleep(self.interval)

                if (
                    isinstance(self._stop_clause, str)
                    and self._stop_clause
                    and not self._flag_get()
                ):
                    break

                try:
                    await self.func(self.module_instance, *args, **kwargs)
                except StopLoop:
                    break
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Error running loop %s!", self.func)

                if not self._wait_before:
                    await asyncio.sleep(self.interval)
        finally:
            self.status = False
            self._wait_for_stop.set()

    def __del__(self) -> None:
        try:
            if self._task:
                self._task.cancel()
        except Exception:
            pass


def loop(
    interval: int = 5,
    autostart: bool = False,
    wait_before: bool = False,
    stop_clause: typing.Optional[str] = None,
) -> typing.Callable:

    def wrapped(func: typing.Callable) -> InfiniteLoop:
        return InfiniteLoop(func, interval, autostart, wait_before, stop_clause)

    return wrapped


def command(
    name: str | None = None,
    *,
    required: "int | str" = 0,
    aliases: list[str] | None = None,
    incoming: bool = False,
    ru_doc: str | None = None,
    en_doc: str | None = None,
) -> typing.Callable:
    if required is not None and not isinstance(required, (int, str)):
        raise TypeError(
            f"@command(required=...) must be int (bitmask) or str (role name), "
            f"got {type(required).__name__}"
        )
    if isinstance(required, str) and not required.strip():
        raise ValueError("@command(required=...) string role name must be non-empty")
    def decorator(func: typing.Callable) -> typing.Callable:
        meta = typing.cast(typing.Any, func)
        meta._is_command = True
        meta._command_name = name or func.__name__.removesuffix("_cmd")
        meta._required = required
        meta._aliases = aliases or []
        meta._ru_doc = ru_doc
        meta._en_doc = en_doc
        meta._incoming = bool(incoming) or isinstance(required, str)
        return func
    return decorator
def watcher(
    filter_func: typing.Callable | None = None,
    **tags: typing.Any,
) -> typing.Callable:
    def decorator(func: typing.Callable) -> typing.Callable:
        meta = typing.cast(typing.Any, func)
        meta._is_watcher = True
        meta._watcher_filter = filter_func
        for tag_name, tag_value in tags.items():
            setattr(func, tag_name, tag_value)
        return func
    return decorator
def inline_handler(
    *,
    only_own: bool = False,
) -> typing.Callable:
    def decorator(func: typing.Callable) -> typing.Callable:
        meta = typing.cast(typing.Any, func)
        meta._is_inline_handler = True
        meta._inline_only_own   = only_own
        return func
    return decorator


_INIT_SIGNATURE_CACHE: dict[type, int] = {}

def _module_param_count(mod_class: type) -> int:
    cached = _INIT_SIGNATURE_CACHE.get(mod_class)
    if cached is not None:
        return cached
    try:
        init = typing.cast(typing.Any, getattr(mod_class, "__init__", None))
        sig = inspect.signature(init)
        count = sum(1 for p in sig.parameters if p != "self")
    except (ValueError, TypeError):
        count = 2
    _INIT_SIGNATURE_CACHE[mod_class] = count
    return count
class Loader:
    def __init__(
        self,
        client: typing.Any,
        db: typing.Any,
        dispatcher: typing.Any,
    ) -> None:
        self._client = client
        self._db = db
        self._dispatcher = dispatcher
        self._modules: dict[str, KitsuneModule] = {}
    @property
    def modules(self) -> dict[str, KitsuneModule]:
        return self._modules
    def get_modules(self) -> dict[str, KitsuneModule]:
        return dict(self._modules)
    def get_module(self, name: str) -> KitsuneModule | None:
        return self._modules.get(name.lower())
    def get_prefix(self, userbot: typing.Optional[str] = None) -> str:
        key = "dragon.prefix" if userbot == "dragon" else "kitsune.main"
        default = "," if userbot == "dragon" else "."
        return self._db.get(key, "command_prefix", default)
    async def _load_one_builtin(self, path: Path) -> None:
        try:
            await self._load_from_path(path, is_builtin=True)
        except ModuleLoadError as exc:
            if "No KitsuneModule subclass" in str(exc):
                logger.debug("Loader: skipping %s (no module class)", path.name)
            else:
                logger.warning("Loader: failed to load builtin %s: %s", path.name, exc)
        except Exception:
            logger.warning("Loader: failed to load builtin %s", path.name, exc_info=True)
    async def _load_one_user(self, path: Path) -> None:
        try:
            await self._load_from_path(path, is_builtin=False)
        except Exception:
            logger.exception("Loader: failed to load user module %s", path.name)
    async def load_all_builtin(self) -> None:
        if not _BUILTIN_MODULES_DIR.exists():
            return
        paths = [
            p for p in sorted(_BUILTIN_MODULES_DIR.glob("*.py"))
            if not p.name.startswith("_")
        ]
        pkg_paths = [
            p / "__init__.py"
            for p in sorted(_BUILTIN_MODULES_DIR.iterdir())
            if p.is_dir() and not p.name.startswith("_") and (p / "__init__.py").exists()
        ]
        await asyncio.gather(*[self._load_one_builtin(p) for p in paths + pkg_paths])
    async def load_all_user(self) -> None:
        from ...paths import data_dir as _kdd
        user_dir = _kdd() / "modules"
        if not user_dir.exists():
            return
        paths = sorted(user_dir.glob("*.py"))
        await asyncio.gather(*[self._load_one_user(p) for p in paths])
    async def load_from_url(
        self,
        url: str,
        progress_cb=None,
        on_soft_findings: typing.Callable[
            [list[str]], typing.Awaitable[bool]
        ] | None = None,
    ) -> KitsuneModule:
        import aiohttp
        from ...net.http_pool import get_shared_session
        session = get_shared_session()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            source = await resp.text()
        _detect_legacy_or_raise(source, origin=url)
        findings = _scan_ast_with_cache(source, filename=url)
        if findings and on_soft_findings is not None:
            proceed = await on_soft_findings(findings)
            if not proceed:
                raise ModuleLoadError(
                    "Установка отменена пользователем: "
                    "обнаружены подозрительные конструкции"
                )
        from ...paths import data_dir as _kdd
        user_dir = _kdd() / "modules"
        user_dir.mkdir(parents=True, exist_ok=True)
        filename = url.rstrip("/").split("/")[-1]
        if not filename.endswith(".py"):
            filename += ".py"
        path = user_dir / filename
        path.write_text(source, encoding="utf-8")
        return await self._load_from_path(
            path, is_builtin=False, progress_cb=progress_cb,
            already_scanned=True, prefetched_source=source,
        )
    async def load_from_file(
        self,
        path: Path,
        progress_cb=None,
        on_soft_findings: typing.Callable[
            [list[str]], typing.Awaitable[bool]
        ] | None = None,
    ) -> KitsuneModule:
        source = path.read_text(encoding="utf-8")
        _detect_legacy_or_raise(source, origin=str(path))
        findings = _scan_ast_with_cache(source, filename=str(path))
        if findings and on_soft_findings is not None:
            proceed = await on_soft_findings(findings)
            if not proceed:
                raise ModuleLoadError(
                    "Установка отменена пользователем: "
                    "обнаружены подозрительные конструкции"
                )
        return await self._load_from_path(
            path, is_builtin=False, progress_cb=progress_cb,
            already_scanned=True, prefetched_source=source,
        )
    def _purge_sys_modules(self, mod: KitsuneModule) -> None:
        module_name = getattr(mod, "_py_module_name", None)
        if not module_name:
            source_path = getattr(mod, "_source_path", None)
            if source_path:
                path = Path(source_path)
                if path.name == "__init__.py":
                    module_name = f"kitsune.modules.{path.parent.name}"
                else:
                    module_name = f"kitsune.modules.{path.stem}"
        if not module_name:
            return
        prefix = module_name + "."
        to_remove = [
            key for key in list(sys.modules)
            if key == module_name or key.startswith(prefix)
        ]
        for key in to_remove:
            sys.modules.pop(key, None)
        importlib.invalidate_caches()

    def _unregister_inline_handlers_for(self, mod: KitsuneModule) -> None:
        _inline = getattr(self._client, "inline", None)
        if _inline is None:
            return
        for _, method in inspect.getmembers(mod, predicate=inspect.ismethod):
            if getattr(method, "_is_inline_handler", False):
                if hasattr(_inline, "unregister_inline_handler"):
                    try:
                        _inline.unregister_inline_handler(method)
                    except Exception as _ie:
                        logger.debug(
                            "Loader: unregister inline_handler %r failed: %s",
                            getattr(method, "__name__", "?"), _ie,
                        )

    async def unload_module(self, name: str) -> bool:
        found = self._modules.get(name.lower())
        if found is None:
            return False
        mod: KitsuneModule = found
        try:
            await mod.on_unload()
        except Exception:
            logger.exception("Loader: on_unload failed for %s", name)
        for _, attr in inspect.getmembers(mod):
            if isinstance(attr, InfiniteLoop):
                logger.debug("Loader: stopping loop %s in %s", attr.func, name)
                try:
                    await asyncio.wait_for(attr.stop(), timeout=5.0)
                except (asyncio.TimeoutError, Exception):
                    logger.debug(
                        "Loader: loop %s did not stop cleanly", attr.func, exc_info=True
                    )
        for cmd_name in list(self._dispatcher._commands):
            entry = self._dispatcher._commands[cmd_name]
            handler = entry[0]
            owner = entry[2] if len(entry) > 2 else None
            if getattr(handler, "__self__", None) is mod or owner is mod:
                self._dispatcher.unregister_command(cmd_name)
        self._dispatcher.unregister_watchers_for(mod)
        self._unregister_inline_handlers_for(mod)
        from ...events import bus
        bus.unsubscribe_all(mod)
        del self._modules[name.lower()]
        self._purge_sys_modules(mod)
        logger.info("Loader: unloaded %s", name)
        return True
    async def reload_module(self, name: str, progress_cb=None) -> KitsuneModule:
        mod = self._modules.get(name.lower())
        if mod is None:
            raise ModuleLoadError(f"Module {name!r} not loaded")
        source_info = getattr(mod, "_source_path", None)
        source_url = getattr(mod, "_source_url", None)
        await self.unload_module(name)
        if source_url:
            return await self.load_from_url(source_url, progress_cb=progress_cb)
        if source_info:
            return await self._load_from_path(Path(source_info), is_builtin=False, progress_cb=progress_cb)
        raise ModuleLoadError(f"Cannot reload {name!r}: source unknown")
    async def _load_from_path(
        self,
        path: Path,
        *,
        is_builtin: bool,
        progress_cb=None,
        already_scanned: bool = False,
        prefetched_source: str | None = None,
    ) -> KitsuneModule:
        is_pkg = path.name == "__init__.py"
        if is_pkg:
            module_name = f"kitsune.modules.{path.parent.name}"
        else:
            module_name = f"kitsune.modules.{path.stem}"
        source = prefetched_source if prefetched_source is not None else path.read_text(encoding="utf-8")
        if not is_builtin:
            _detect_legacy_or_raise(source, origin=str(path))
        if not is_builtin and not already_scanned:
            _scan_ast_with_cache(source, filename=str(path))
        spec = importlib.util.spec_from_file_location(
            module_name, path,
            submodule_search_locations=[str(path.parent)] if is_pkg else None,
        )
        if spec is None or spec.loader is None:
            raise ModuleLoadError(f"Cannot create module spec for {path}")
        py_module = importlib.util.module_from_spec(spec)
        py_module.__loader__ = spec.loader
        if is_pkg:
            py_module.__path__ = [str(path.parent)]
            py_module.__package__ = module_name
        sys.modules[module_name] = py_module

        if not is_builtin:

            _pre_pip: list[str] = []
            _pre_sys: list[str] = []
            try:
                _pre_tree = __import__("ast").parse(source)
                for _node in __import__("ast").walk(_pre_tree):
                    if isinstance(_node, __import__("ast").ClassDef):
                        for _stmt in _node.body:
                            if (
                                isinstance(_stmt, __import__("ast").Assign)
                                and len(_stmt.targets) == 1
                                and isinstance(_stmt.targets[0], __import__("ast").Name)
                            ):
                                _tname = _stmt.targets[0].id
                                if _tname == "pip_requires" and isinstance(_stmt.value, __import__("ast").List):
                                    _pre_pip = [
                                        elt.s for elt in _stmt.value.elts
                                        if isinstance(elt, __import__("ast").Constant)
                                    ]
                                elif _tname == "system_requires" and isinstance(_stmt.value, __import__("ast").List):
                                    _pre_sys = [
                                        elt.s for elt in _stmt.value.elts
                                        if isinstance(elt, __import__("ast").Constant)
                                    ]
            except Exception:
                pass

            _all_pre_deps = _pre_pip
            _all_pre_sys = _pre_sys

            if _all_pre_deps or _all_pre_sys:
                if progress_cb:
                    try:
                        _dep_names = ", ".join(
                            f"<code>{_IMPORT_TO_PIP.get(d, d)}</code>"
                            for d in _all_pre_deps
                        )
                        _sys_names = ", ".join(f"<code>{s}</code>" for s in _all_pre_sys)
                        _parts = []
                        if _dep_names:
                            _parts.append(_dep_names)
                        if _sys_names:
                            _parts.append(_sys_names)
                        await progress_cb(
                            f"🦊 Kitsune настраивает нужные компоненты… {', '.join(_parts)}..."
                        )
                    except Exception:
                        pass

                if _all_pre_deps:
                    _, _pip_failed = await _ensure_pip_deps(_all_pre_deps, progress_cb=None)
                    if _pip_failed:
                        logger.warning(
                            "Loader: pre-install failed for pip deps: %s", _pip_failed
                        )
                if _all_pre_sys:
                    _, _sys_failed = await _ensure_system_deps(_all_pre_sys, progress_cb=progress_cb)
                    if _sys_failed:
                        logger.warning(
                            "Loader: pre-install failed for system deps: %s", _sys_failed
                        )

        _MAX_RETRIES = 15
        _installed_this_session: set[str] = set()
        for _attempt in range(_MAX_RETRIES + 1):
            try:
                spec.loader.exec_module(py_module)
                break
            except ImportError as exc:
                if is_builtin or _attempt >= _MAX_RETRIES:
                    sys.modules.pop(module_name, None)
                    if _attempt >= _MAX_RETRIES:
                        raise ModuleLoadError(
                            f"🦊 Kitsune: попытки автоустановки зависимостей исчерпаны… {exc}"
                        ) from exc
                    raise ModuleLoadError(f"Execution failed: {exc}") from exc
                missing_pkg = _extract_missing_package(exc)
                if not missing_pkg:
                    sys.modules.pop(module_name, None)
                    raise ModuleLoadError(f"Execution failed: {exc}") from exc
                if missing_pkg in _installed_this_session:

                    sys.modules.pop(module_name, None)
                    raise ModuleLoadError(
                        f"🦊 Kitsune: пакет {missing_pkg!r} установлен, загрузка модуля не удалась… {exc}"
                    ) from exc
                logger.info(
                    "Loader: missing package %r (attempt %d) — attempting auto-install",
                    missing_pkg, _attempt + 1,
                )
                if progress_cb:
                    try:
                        await progress_cb(
                            f"📦 Устанавливаю зависимость "
                            f"<code>{_IMPORT_TO_PIP.get(missing_pkg, missing_pkg)}</code>"
                            f" ({_attempt + 1})..."
                        )
                    except Exception:
                        pass
                installed = await _pip_install(missing_pkg)
                if installed:
                    _installed_this_session.add(missing_pkg)
                    if progress_cb:
                        try:
                            await progress_cb(
                                f"✅ <code>{_IMPORT_TO_PIP.get(missing_pkg, missing_pkg)}</code>"
                                f" установлена. Продолжаю загрузку..."
                            )
                        except Exception:
                            pass

                    _stale = [
                        k for k in list(sys.modules)
                        if k == missing_pkg or k.startswith(missing_pkg + ".")
                    ]
                    for _k in _stale:
                        sys.modules.pop(_k, None)
                    importlib.invalidate_caches()

                    sys.modules.pop(module_name, None)
                    py_module = importlib.util.module_from_spec(spec)
                    py_module.__loader__ = spec.loader
                    if is_pkg:
                        py_module.__path__ = [str(path.parent)]
                        py_module.__package__ = module_name
                    sys.modules[module_name] = py_module

                else:
                    sys.modules.pop(module_name, None)
                    pip_tail = get_last_pip_stderr(missing_pkg)
                    detail = f" | pip stderr: {pip_tail}" if pip_tail else ""
                    raise ModuleLoadError(
                        f"Не удалось установить зависимость {missing_pkg!r}: {exc}{detail}"
                    ) from exc
            except Exception as exc:
                sys.modules.pop(module_name, None)
                raise ModuleLoadError(f"Execution failed: {exc}") from exc
        found_class = self._find_module_class(py_module)
        if found_class is None:
            sys.modules.pop(module_name, None)
            raise ModuleLoadError(f"No KitsuneModule subclass found in {path.name}")
        mod_class = typing.cast("type[KitsuneModule]", found_class)
        if not getattr(mod_class, "name", ""):
            mod_class.name = mod_class.__name__
        if mod_class.requires:
            missing = [r for r in mod_class.requires if r not in self._modules]
            if missing:
                sys.modules.pop(module_name, None)
                raise ModuleLoadError(
                    f"Missing dependencies: {', '.join(missing)}"
                )
        param_count = _module_param_count(mod_class)
        mod: typing.Any
        factory = typing.cast(typing.Any, mod_class)
        try:
            if param_count >= 2:
                mod = factory(self._client, self._db)
            else:
                mod = factory()
                mod.client = self._client
                mod._client = self._client
                mod.db = self._db
                mod._db = self._db
        except (ValueError, TypeError):
            mod = factory(self._client, self._db)
        mod.tg_id = self._client.tg_id
        mod._source_path = str(path)
        mod._py_module_name = module_name
        mod._is_builtin = is_builtin
        mod._load_config_from_db()
        existing = self._modules.get(mod.name.lower())
        if existing:
            await self.unload_module(mod.name)
        await mod.on_load()
        self._modules[mod.name.lower()] = mod
        self._register_module(mod)
        from ..._types import ModuleLoadedEvent
        from ...events import bus
        bus.emit_sync(ModuleLoadedEvent(module_name=mod.name, is_builtin=is_builtin))
        logger.info("Loader: loaded %s v%s (%s)", mod.name, mod.version, path.name)
        return mod
    def _find_module_class(self, py_module: ModuleType) -> type | None:
        module_name = getattr(py_module, "__name__", "")
        candidates: list[type] = []
        for obj in vars(py_module).values():
            if not inspect.isclass(obj):
                continue
            if obj is KitsuneModule:
                continue
            if getattr(obj, "__module__", "") != module_name:
                continue
            try:
                is_direct = issubclass(obj, KitsuneModule)
            except TypeError:
                is_direct = False
            if is_direct:
                candidates.append(obj)
                continue
            if self._inherits_kitsune_module(obj):
                candidates.append(obj)
        if not candidates:
            return None
        for obj in candidates:
            if not obj.__subclasses__():
                return obj
        return candidates[0]

    @staticmethod
    def _inherits_kitsune_module(obj: type) -> bool:
        canonical = f"{KitsuneModule.__module__}.{KitsuneModule.__qualname__}"
        for base in inspect.getmro(obj):
            if base is object:
                continue
            base_id = f"{getattr(base, '__module__', '')}.{getattr(base, '__qualname__', '')}"
            if base.__name__ == "KitsuneModule" and base is not obj:
                return True
            if base_id == canonical and base is not obj:
                return True
        return False
    def _register_module(self, mod: KitsuneModule) -> None:
        for _, attr in inspect.getmembers(mod):
            if isinstance(attr, InfiniteLoop):
                attr.module_instance = mod
                if attr.autostart:
                    try:
                        attr.start()
                    except Exception:
                        logger.exception(
                            "Loader: failed to autostart loop in %s", mod.name
                        )
        for _, method in inspect.getmembers(mod, predicate=inspect.ismethod):
            meta = typing.cast(typing.Any, method)
            if getattr(method, "_is_command", False):
                name = meta._command_name
                required = meta._required
                self._dispatcher.register_command(name, method, required, module=mod)
                for alias in getattr(method, "_aliases", []):
                    self._dispatcher.register_command(alias, method, required, module=mod)
            if getattr(method, "_is_watcher", False):
                filter_func = meta._watcher_filter
                self._dispatcher.register_watcher(method, filter_func, module=mod)
            if getattr(method, "_is_inline_handler", False):
                _inline = getattr(self._client, "inline", None)
                if _inline and hasattr(_inline, "register_inline_handler"):
                    try:
                        _inline.register_inline_handler(method)
                    except Exception as _ie:
                        logger.debug(
                            "Loader: register inline_handler %r failed: %s",
                            getattr(method, "__name__", "?"), _ie,
                        )
            if getattr(method, "_is_callback_handler", False):
                _inline = getattr(self._client, "inline", None)
                if _inline and hasattr(_inline, "register_callback_handler"):
                    try:
                        _inline.register_callback_handler(method)
                    except Exception as _ce:
                        logger.debug(
                            "Loader: register callback_handler %r failed: %s",
                            getattr(method, "__name__", "?"), _ce,
                        )
