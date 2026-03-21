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

class KitsuneModule:

    name: str = ""
    description: str = ""
    author: str = ""
    version: str = "1.0"

    icon: str = "📦"

    category: str = "other"

    requires: typing.ClassVar[list[str]] = []

    def __init__(self, client: typing.Any, db: typing.Any) -> None:
        self.client  = client
        self.db      = db
        self.tg_id: int = 0
        self.inline: typing.Any = None

    async def on_load(self) -> None:
        pass

    async def on_unload(self) -> None:
        pass

    def get_args(self, event: "typing.Any") -> str:
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        prefix = dispatcher._prefix if dispatcher else "."
        text = event.message.raw_text or event.message.text or ""
        if text.startswith(prefix):
            text = text[len(prefix):]
        parts = text.split(maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else ""

    def strings(self, key: str, lang: str = "ru") -> str:
        attr = f"strings_{lang}" if lang != "en" else "strings_en"
        pool = getattr(self, attr, None)

        if not isinstance(pool, dict):
            pool = getattr(self, "strings_en", None)

        if not isinstance(pool, dict):
            cls_attr = vars(type(self)).get("strings")
            if isinstance(cls_attr, dict):
                pool = cls_attr

        if not isinstance(pool, dict):
            return f"<missing:{key}>"

        return pool.get(key, f"<missing:{key}>")

def command(name: str, required: int | None = None):
    from .security import OWNER as _OWNER
    _required = required if required is not None else _OWNER

    def decorator(func: typing.Callable) -> typing.Callable:
        func._kitsune_command = name.lower()
        func._kitsune_required = _required
        return func
    return decorator

def watcher(filter_func: typing.Callable | None = None):
    def decorator(func: typing.Callable) -> typing.Callable:
        func._kitsune_watcher = True
        func._kitsune_filter = filter_func
        return func
    return decorator

class _SafetyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top = alias.name.split(".")[0]
            if alias.name in _BLOCKED_IMPORTS or top in _BLOCKED_IMPORTS:
                self.violations.append(f"Blocked import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        top = mod.split(".")[0]
        if mod in _BLOCKED_IMPORTS or top in _BLOCKED_IMPORTS:
            self.violations.append(f"Blocked from-import: {mod}")
        if top == "os":
            _DANGEROUS_OS = {
                "system", "popen", "exec", "execve", "execl", "execvp",
                "spawnl", "spawnle", "spawnlp", "fork", "forkpty",
            }
            for alias in (node.names or []):
                if alias.name in _DANGEROUS_OS:
                    self.violations.append(f"Blocked os.{alias.name} import")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            if node.func.id in ("eval", "exec", "compile"):
                self.violations.append(f"Dangerous built-in call: {node.func.id}()")
            if node.func.id == "__import__":
                if node.args and isinstance(node.args[0], ast.Constant):
                    mod = str(node.args[0].value).split(".")[0]
                    if mod in _BLOCKED_IMPORTS:
                        self.violations.append(f"Blocked __import__({mod!r})")
        if isinstance(node.func, ast.Attribute):
            _DANGEROUS_ATTRS = {
                "system", "popen", "execve", "execl", "execvp",
                "fork", "forkpty", "spawnl",
            }
            if node.func.attr in _DANGEROUS_ATTRS:
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                    self.violations.append(f"Dangerous call: os.{node.func.attr}()")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        _ESCAPE_ATTRS = {"__subclasses__", "__builtins__", "__globals__", "__code__"}
        if node.attr in _ESCAPE_ATTRS:
            self.violations.append(f"Blocked dangerous attribute access: .{node.attr}")
        self.generic_visit(node)

def _ast_scan(source: str, name: str) -> None:
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

class Loader:

    def __init__(
        self,
        client: typing.Any,
        db: typing.Any,
        dispatcher: typing.Any,
    ) -> None:
        self._client     = client
        self._db         = db
        self._dispatcher = dispatcher
        self._modules: dict[str, tuple[KitsuneModule, str]] = {}

    async def load_all_builtin(self) -> None:
        for path in sorted(_BUILTIN_MODULES_DIR.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                await self.load_from_file(path, builtin=True)
            except Exception:
                logger.exception("Loader: failed to load builtin %s", path.name)

    async def load_all_user(self) -> None:
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
        sys.modules.pop(f"kitsune.modules.{module_name.lower()}", None)
        logger.info("Loader: unloaded %s", module_name)
        return True

    @property
    def modules(self) -> dict[str, KitsuneModule]:
        return {k: v[0] for k, v in self._modules.items()}

    async def _load_source(self, source: str, origin: str, name: str) -> KitsuneModule:
        is_builtin = origin.startswith(str(_BUILTIN_MODULES_DIR))
        if not is_builtin:
            _ast_scan(source, name)

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

        module_name = (cls.name or name).lower()
        missing = [
            req for req in (cls.requires or [])
            if req.lower() not in self._modules
        ]
        if missing:
            raise ModuleLoadError(
                f"Module {module_name!r} requires {missing} — load them first"
            )

        if module_name in self._modules:
            await self.unload(module_name)

        instance: KitsuneModule = cls(self._client, self._db)
        instance.tg_id = getattr(self._client, "tg_id", 0)
        await instance.on_load()

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
    def __init__(self, source: str) -> None:
        self._source = source

    def get_source(self) -> str:
        return self._source
