from __future__ import annotations

import ast
import asyncio
import importlib
import importlib.util
import inspect
import logging
import os
import sys
import typing
from pathlib import Path
from types import ModuleType

logger = logging.getLogger(__name__)

_BLOCKED_IMPORTS: frozenset[str] = frozenset({
    "subprocess", "pty", "ctypes", "multiprocessing",
    "socket", "importlib", "pickle", "marshal",
    "code", "codeop", "compileall", "py_compile",
    "shelve", "dbm", "zipimport", "zipapp",
    "runpy", "distutils",
})

_BUILTIN_MODULES_DIR = Path(__file__).parent.parent / "modules"


class ModuleLoadError(Exception):
    pass


class ASTSecurityError(ModuleLoadError):
    pass


class ConfigValue:

    def __init__(
        self,
        key: str,
        default: typing.Any = None,
        doc: str = "",
        validator: typing.Any = None,
    ) -> None:
        self.key = key
        self.default = default
        self.doc = doc
        self.validator = validator
        self.value = default

    def set(self, raw_value: typing.Any) -> None:
        if self.validator is not None:
            from ..validators import ValidationError
            try:
                self.value = self.validator.validate(raw_value)
            except ValidationError:
                raise
        else:
            self.value = raw_value


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
        text = event.message.raw_text or event.message.text or ""
        if text.startswith(prefix):
            parts = text.split(maxsplit=1)
            return parts[1] if len(parts) > 1 else ""
        return ""

    def strings(self, key: str, **kwargs: typing.Any) -> str:
        db = getattr(self, "db", None)
        lang = db.get("kitsune.core", "lang", "ru") if db else "ru"

        strings_key = f"strings_{lang}" if lang != "en" else "strings"
        strings = getattr(self, strings_key, None) or getattr(self, "strings_ru", None) or getattr(self, "strings", {})

        text = strings.get(key, key) if isinstance(strings, dict) else key
        return text.format(**kwargs) if kwargs else text

    def _load_config_from_db(self) -> None:
        if self.config is None:
            return
        db_key = f"kitsune.config.{self.name}"
        for key in self.config.keys():
            saved = self.db.get(db_key, key, None)
            if saved is not None:
                try:
                    self.config[key] = saved
                except Exception:
                    pass


def command(
    name: str | None = None,
    *,
    required: int = 0,
    aliases: list[str] | None = None,
) -> typing.Callable:
    def decorator(func: typing.Callable) -> typing.Callable:
        func._is_command = True
        func._command_name = name or func.__name__.removesuffix("_cmd")
        func._required = required
        func._aliases = aliases or []
        return func
    return decorator


def watcher(
    filter_func: typing.Callable | None = None,
) -> typing.Callable:
    def decorator(func: typing.Callable) -> typing.Callable:
        func._is_watcher = True
        func._watcher_filter = filter_func
        return func
    return decorator


class _ASTScanner(ast.NodeVisitor):

    def __init__(self) -> None:
        self.errors: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in _BLOCKED_IMPORTS:
                self.errors.append(f"Blocked import: {alias.name} (line {node.lineno})")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root = node.module.split(".")[0]
            if root in _BLOCKED_IMPORTS:
                self.errors.append(f"Blocked import: {node.module} (line {node.lineno})")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "__import__":
            if node.args and isinstance(node.args[0], ast.Constant):
                root = str(node.args[0].value).split(".")[0]
                if root in _BLOCKED_IMPORTS:
                    self.errors.append(
                        f"Blocked __import__: {node.args[0].value} (line {node.lineno})"
                    )
        self.generic_visit(node)


def _scan_ast(source: str, filename: str = "<module>") -> None:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        raise ModuleLoadError(f"Syntax error: {exc}") from exc

    scanner = _ASTScanner()
    scanner.visit(tree)

    if scanner.errors:
        raise ASTSecurityError(
            "Security scan failed:\n" + "\n".join(f"  • {e}" for e in scanner.errors)
        )


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

    async def load_all_builtin(self) -> None:
        if not _BUILTIN_MODULES_DIR.exists():
            return

        for path in sorted(_BUILTIN_MODULES_DIR.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                await self._load_from_path(path, is_builtin=True)
            except Exception:
                logger.exception("Loader: failed to load builtin %s", path.name)

    async def load_all_user(self) -> None:
        user_dir = Path.home() / ".kitsune" / "modules"
        if not user_dir.exists():
            return

        for path in sorted(user_dir.glob("*.py")):
            try:
                await self._load_from_path(path, is_builtin=False)
            except Exception:
                logger.exception("Loader: failed to load user module %s", path.name)

    async def load_from_url(self, url: str) -> KitsuneModule:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                source = await resp.text()

        _scan_ast(source, filename=url)

        user_dir = Path.home() / ".kitsune" / "modules"
        user_dir.mkdir(parents=True, exist_ok=True)

        filename = url.rstrip("/").split("/")[-1]
        if not filename.endswith(".py"):
            filename += ".py"

        path = user_dir / filename
        path.write_text(source, encoding="utf-8")

        return await self._load_from_path(path, is_builtin=False)

    async def load_from_file(self, path: Path) -> KitsuneModule:
        source = path.read_text(encoding="utf-8")
        _scan_ast(source, filename=str(path))
        return await self._load_from_path(path, is_builtin=False)

    async def unload_module(self, name: str) -> bool:
        mod = self._modules.get(name.lower())
        if mod is None:
            return False

        try:
            await mod.on_unload()
        except Exception:
            logger.exception("Loader: on_unload failed for %s", name)

        for cmd_name in list(self._dispatcher._commands):
            handler, _ = self._dispatcher._commands[cmd_name]
            if getattr(handler, "__self__", None) is mod:
                self._dispatcher.unregister_command(cmd_name)

        self._dispatcher.unregister_watchers_for(mod)

        from ..events import bus
        bus.unsubscribe_all(mod)

        del self._modules[name.lower()]
        logger.info("Loader: unloaded %s", name)
        return True

    async def reload_module(self, name: str) -> KitsuneModule:
        mod = self._modules.get(name.lower())
        if mod is None:
            raise ModuleLoadError(f"Module {name!r} not loaded")

        source_info = getattr(mod, "_source_path", None)
        source_url = getattr(mod, "_source_url", None)

        await self.unload_module(name)

        if source_url:
            return await self.load_from_url(source_url)
        if source_info:
            return await self._load_from_path(Path(source_info), is_builtin=False)

        raise ModuleLoadError(f"Cannot reload {name!r}: source unknown")

    async def _load_from_path(self, path: Path, *, is_builtin: bool) -> KitsuneModule:
        source = path.read_text(encoding="utf-8")

        if not is_builtin:
            _scan_ast(source, filename=str(path))

        module_name = f"kitsune.modules.{path.stem}"

        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ModuleLoadError(f"Cannot create module spec for {path}")

        py_module = importlib.util.module_from_spec(spec)
        py_module.__loader__ = spec.loader
        sys.modules[module_name] = py_module

        try:
            spec.loader.exec_module(py_module)
        except Exception as exc:
            del sys.modules[module_name]
            raise ModuleLoadError(f"Execution failed: {exc}") from exc

        mod_class = self._find_module_class(py_module)
        if mod_class is None:
            del sys.modules[module_name]
            raise ModuleLoadError(f"No KitsuneModule subclass found in {path.name}")

        if mod_class.requires:
            missing = [r for r in mod_class.requires if r not in self._modules]
            if missing:
                del sys.modules[module_name]
                raise ModuleLoadError(
                    f"Missing dependencies: {', '.join(missing)}"
                )

        mod = mod_class(self._client, self._db)
        mod.tg_id = self._client.tg_id
        mod._source_path = str(path)
        mod._is_builtin = is_builtin

        mod._load_config_from_db()

        existing = self._modules.get(mod.name.lower())
        if existing:
            await self.unload_module(mod.name)

        await mod.on_load()
        self._modules[mod.name.lower()] = mod
        self._register_module(mod)

        from .._types import ModuleLoadedEvent
        from ..events import bus
        bus.emit_sync(ModuleLoadedEvent(module_name=mod.name, is_builtin=is_builtin))

        logger.info("Loader: loaded %s v%s (%s)", mod.name, mod.version, path.name)
        return mod

    def _find_module_class(self, py_module: ModuleType) -> type | None:
        for obj in vars(py_module).values():
            if (
                inspect.isclass(obj)
                and issubclass(obj, KitsuneModule)
                and obj is not KitsuneModule
            ):
                return obj
        return None

    def _register_module(self, mod: KitsuneModule) -> None:
        for _, method in inspect.getmembers(mod, predicate=inspect.ismethod):
            if getattr(method, "_is_command", False):
                name = method._command_name
                required = method._required
                self._dispatcher.register_command(name, method, required)

                for alias in getattr(method, "_aliases", []):
                    self._dispatcher.register_command(alias, method, required)

            if getattr(method, "_is_watcher", False):
                filter_func = method._watcher_filter
                self._dispatcher.register_watcher(method, filter_func)
