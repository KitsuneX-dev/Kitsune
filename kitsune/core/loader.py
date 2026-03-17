"""
Kitsune Module Loader

Improvements vs Hikka:
- AST safety scan before exec() — detects dangerous imports/calls
- Proper module unload (removes handlers from dispatcher)
- Clean module lifecycle: load → init → register → unload
- Type-safe module registry
- Hydrogram + Telethon dual-client modules supported
"""

# © Yushi (@Mikasu32), 2024-2025
# Kitsune Userbot — License: AGPLv3

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

# Imports that are blocked in user-loaded modules
_BLOCKED_IMPORTS: frozenset[str] = frozenset({
    "subprocess", "os.system", "pty", "ctypes",
    "socket", "multiprocessing",
})

# Built-in module names (loaded from kitsune/modules/)
_BUILTIN_MODULES_DIR = Path(__file__).parent.parent / "modules"


class ModuleLoadError(Exception):
    """Raised when a module fails to load."""


class ASTSecurityError(ModuleLoadError):
    """Raised when a module contains potentially dangerous code."""


# ── Base Module class ─────────────────────────────────────────────────────────

class KitsuneModule:
    """
    Base class for all Kitsune modules.

    Subclass this and define command methods with the @command decorator
    or watcher methods with the @watcher decorator.

    Example:
        class MyModule(KitsuneModule):
            name = "mymodule"
            description = "Does cool stuff"

            @command("hello", required=OWNER)
            async def hello_cmd(self, event):
                await event.reply("👋 Hello!")
    """

    name: str = ""
    description: str = ""
    author: str = ""
    version: str = "1.0"

    def __init__(self, client: typing.Any, db: typing.Any) -> None:
        self.client  = client
        self.db      = db
        self.tg_id: int = 0
        self.inline: typing.Any = None   # set by Loader after inline init

    async def on_load(self) -> None:
        """Called once after the module is loaded. Override for setup."""

    async def on_unload(self) -> None:
        """Called before the module is unloaded. Override for cleanup."""

    def strings(self, key: str, lang: str = "ru") -> str:
        """Get a localised string from the module's `strings_*` dict."""
        attr = f"strings_{lang}" if lang != "en" else "strings"
        pool = getattr(self, attr, None) or getattr(self, "strings", {})
        return pool.get(key, f"<missing:{key}>")


# ── Decorators ─────────────────────────────────────────────────────────────────

def command(name: str, required: int | None = None):
    """Mark an async method as a command handler."""
    from .security import OWNER as _OWNER
    _required = required if required is not None else _OWNER

    def decorator(func: typing.Callable) -> typing.Callable:
        func._kitsune_command = name.lower()
        func._kitsune_required = _required
        return func
    return decorator


def watcher(filter_func: typing.Callable | None = None):
    """Mark an async method as a watcher."""
    def decorator(func: typing.Callable) -> typing.Callable:
        func._kitsune_watcher = True
        func._kitsune_filter = filter_func
        return func
    return decorator


# ── AST scanner ───────────────────────────────────────────────────────────────

class _SafetyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name in _BLOCKED_IMPORTS or alias.name.split(".")[0] in _BLOCKED_IMPORTS:
                self.violations.append(f"Blocked import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        if mod in _BLOCKED_IMPORTS or mod.split(".")[0] in _BLOCKED_IMPORTS:
            self.violations.append(f"Blocked from-import: {mod}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Detect eval("...") / exec("...") at module level
        if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
            self.violations.append(f"Direct {node.func.id}() call detected")
        self.generic_visit(node)


def _ast_scan(source: str, name: str) -> None:
    """Raise ASTSecurityError if source contains blocked patterns."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ModuleLoadError(f"Syntax error in {name}: {exc}") from exc

    visitor = _SafetyVisitor()
    visitor.visit(tree)
    if visitor.violations:
        raise ASTSecurityError(
            f"Module {name!r} failed security scan:\n" + "\n".join(visitor.violations)
        )


# ── Loader ─────────────────────────────────────────────────────────────────────

class Loader:
    """
    Manages loading, unloading and reloading of KitsuneModules.

    Built-in modules are loaded from kitsune/modules/.
    User modules are loaded from ~/.kitsune/modules/.
    Remote modules can be loaded from a URL (with AST scan).
    """

    def __init__(
        self,
        client: typing.Any,
        db: typing.Any,
        dispatcher: typing.Any,
    ) -> None:
        self._client     = client
        self._db         = db
        self._dispatcher = dispatcher
        # module_name → (module_instance, source_path_or_url)
        self._modules: dict[str, tuple[KitsuneModule, str]] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    async def load_all_builtin(self) -> None:
        """Load every .py file from kitsune/modules/."""
        for path in sorted(_BUILTIN_MODULES_DIR.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                await self.load_from_file(path, builtin=True)
            except Exception:
                logger.exception("Loader: failed to load builtin %s", path.name)

    async def load_all_user(self) -> None:
        """Load every .py file from ~/.kitsune/modules/."""
        user_dir = Path.home() / ".kitsune" / "modules"
        user_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(user_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                await self.load_from_file(path, builtin=False)
            except ASTSecurityError as exc:
                logger.error("Loader: security violation in %s — %s", path.name, exc)
            except Exception:
                logger.exception("Loader: failed to load user module %s", path.name)

    async def load_from_file(self, path: Path, builtin: bool = False) -> KitsuneModule:
        source = path.read_text(encoding="utf-8")
        return await self._load_source(source, str(path), path.stem)

    async def load_from_url(self, url: str) -> KitsuneModule:
        """Download and load a module from a URL after AST scan."""
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            source = resp.text

        name = url.rstrip("/").split("/")[-1].removesuffix(".py")
        return await self._load_source(source, url, name)

    async def load_from_source(self, source: str, name: str) -> KitsuneModule:
        return await self._load_source(source, f"<dynamic:{name}>", name)

    async def unload(self, module_name: str) -> bool:
        entry = self._modules.pop(module_name.lower(), None)
        if entry is None:
            return False
        mod_instance, _ = entry
        try:
            await mod_instance.on_unload()
        except Exception:
            logger.exception("Loader: on_unload() failed for %s", module_name)
        self._dispatcher.unregister_watchers_for(mod_instance)
        for attr in dir(mod_instance):
            method = getattr(mod_instance, attr, None)
            if callable(method) and hasattr(method, "_kitsune_command"):
                self._dispatcher.unregister_command(method._kitsune_command)
        # Remove from sys.modules if present
        sys.modules.pop(f"kitsune.modules.{module_name.lower()}", None)
        logger.info("Loader: unloaded %s", module_name)
        return True

    @property
    def modules(self) -> dict[str, KitsuneModule]:
        return {k: v[0] for k, v in self._modules.items()}

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _load_source(self, source: str, origin: str, name: str) -> KitsuneModule:
        # 1. Security scan (skip for builtins to save startup time)
        if not origin.startswith(str(_BUILTIN_MODULES_DIR)):
            _ast_scan(source, name)

        # 2. Compile & exec in isolated namespace
        module_ns: dict[str, typing.Any] = {
            "__name__": f"kitsune.modules.{name.lower()}",
            "__file__": origin,
            "__loader__": _SourceLoader(source),
        }
        try:
            code = compile(source, origin, "exec")
            exec(code, module_ns)  # noqa: S102
        except Exception as exc:
            raise ModuleLoadError(f"Failed to exec module {name!r}: {exc}") from exc

        # 3. Find KitsuneModule subclass
        cls = next(
            (
                v for v in module_ns.values()
                if isinstance(v, type)
                and issubclass(v, KitsuneModule)
                and v is not KitsuneModule
            ),
            None,
        )
        if cls is None:
            raise ModuleLoadError(f"No KitsuneModule subclass found in {name!r}")

        # 4. Instantiate and initialise
        module_name = (cls.name or name).lower()
        if module_name in self._modules:
            await self.unload(module_name)

        instance: KitsuneModule = cls(self._client, self._db)
        instance.tg_id = getattr(self._client, "tg_id", 0)
        await instance.on_load()

        # 5. Register commands and watchers
        for attr_name in dir(instance):
            method = getattr(instance, attr_name, None)
            if not callable(method):
                continue
            if hasattr(method, "_kitsune_command"):
                self._dispatcher.register_command(
                    method._kitsune_command,
                    method,
                    method._kitsune_required,
                )
            if getattr(method, "_kitsune_watcher", False):
                self._dispatcher.register_watcher(
                    method,
                    getattr(method, "_kitsune_filter", None),
                )

        self._modules[module_name] = (instance, origin)
        logger.info("Loader: loaded module %r v%s from %s", module_name, instance.version, origin)
        return instance


class _SourceLoader:
    """Minimal loader so werkzeug debugger can fetch module source."""
    def __init__(self, source: str) -> None:
        self._source = source

    def get_source(self) -> str:
        return self._source
