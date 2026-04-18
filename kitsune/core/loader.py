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

def _get_adapter():
    return None

_BLOCKED_IMPORTS: frozenset[str] = frozenset({
    "subprocess", "pty", "ctypes", "multiprocessing",
    "socket", "pickle", "marshal",
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

        # Подставляем реальный префикс вместо хардкода "."
        dispatcher = getattr(getattr(self, "client", None), "_kitsune_dispatcher", None)
        prefix = dispatcher._prefix if dispatcher else "."
        if prefix != ".":
            # Заменяем точку только внутри <code>...</code> тегов
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
    **tags: typing.Any,
) -> typing.Callable:
    def decorator(func: typing.Callable) -> typing.Callable:
        func._is_watcher = True
        func._watcher_filter = filter_func
        for tag_name, tag_value in tags.items():
            setattr(func, tag_name, tag_value)
        return func
    return decorator

_BLOCKED_ATTRS: frozenset[str] = frozenset({
    "__import__", "__loader__", "__builtins__",
    "system", "popen", "Popen", "call", "run",
})

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
            else:

                self.errors.append(
                    f"Blocked dynamic __import__ call (line {node.lineno})"
                )

        if isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                attr = str(node.args[1].value)
                if attr in _BLOCKED_ATTRS:
                    self.errors.append(
                        f"Blocked getattr access to {attr!r} (line {node.lineno})"
                    )

        if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
            if node.args and isinstance(node.args[0], ast.Constant):
                src = str(node.args[0].value)
                for blocked in _BLOCKED_IMPORTS:
                    if blocked in src:
                        self.errors.append(
                            f"Blocked {node.func.id}() containing {blocked!r} (line {node.lineno})"
                        )
                        break
            else:

                self.errors.append(
                    f"Blocked dynamic eval/exec call (line {node.lineno})"
                )

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:

        if node.attr in _BLOCKED_ATTRS:
            if isinstance(node.value, ast.Name) and node.value.id in _BLOCKED_IMPORTS:
                self.errors.append(
                    f"Blocked attribute access: {node.value.id}.{node.attr} (line {node.lineno})"
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

def _extract_missing_package(exc: ImportError) -> str | None:
    name = getattr(exc, "name", None)
    if name:

        return name.split(".")[0]
    msg = str(exc)
    import re
    m = re.search(r"No module named ['\"]([a-zA-Z0-9_\-\.]+)['\"]", msg)
    if m:
        return m.group(1).split(".")[0]
    return None

_IMPORT_TO_PIP: dict[str, str] = {
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "Crypto": "pycryptodome",
    "nacl": "PyNaCl",
    "attr": "attrs",
    "magic": "python-magic",
    "usb": "pyusb",
    "serial": "pyserial",
    "google": "google-generativeai",
}

async def _pip_install(package: str) -> bool:
    pip_name = _IMPORT_TO_PIP.get(package, package)
    import os as _os
    is_termux = "com.termux" in _os.environ.get("PREFIX", "") or _os.path.isdir("/data/data/com.termux")
    # Namespace packages (e.g. google-generativeai) need --upgrade to rebuild the
    # google namespace so that sub-packages like genai become importable right away.
    _NAMESPACE_PKGS = {"google-generativeai", "google-cloud-storage", "google-auth"}
    args = [sys.executable, "-m", "pip", "install", pip_name, "--quiet", "--no-warn-script-location"]
    if pip_name in _NAMESPACE_PKGS:
        args.append("--upgrade")
    if is_termux:
        args += ["--prefer-binary", "--no-build-isolation"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode == 0:
            logger.info("Loader: installed %r successfully", pip_name)
            importlib.invalidate_caches()
            return True
        logger.warning("Loader: pip install %r failed: %s", pip_name, stderr.decode(errors="replace")[:300])
        return False
    except Exception as exc:
        logger.warning("Loader: pip install %r exception: %s", pip_name, exc)
        return False

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
        user_dir = Path.home() / ".kitsune" / "modules"
        if not user_dir.exists():
            return

        paths = sorted(user_dir.glob("*.py"))
        await asyncio.gather(*[self._load_one_user(p) for p in paths])

    async def load_from_url(self, url: str, progress_cb=None) -> KitsuneModule:
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

        return await self._load_from_path(path, is_builtin=False, progress_cb=progress_cb)

    async def load_from_file(self, path: Path, progress_cb=None) -> KitsuneModule:
        source = path.read_text(encoding="utf-8")
        _scan_ast(source, filename=str(path))
        return await self._load_from_path(path, is_builtin=False, progress_cb=progress_cb)

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

    async def _load_from_path(self, path: Path, *, is_builtin: bool, progress_cb=None) -> KitsuneModule:

        is_pkg = path.name == "__init__.py"
        if is_pkg:
            module_name = f"kitsune.modules.{path.parent.name}"
        else:
            module_name = f"kitsune.modules.{path.stem}"

        source = path.read_text(encoding="utf-8")

        if not is_builtin:
            _scan_ast(source, filename=str(path))

        _adapter = _get_adapter()
        _framework = "kitsune"
        if _adapter and not is_builtin:
            _framework = _adapter.detect_framework(source)
            if _framework not in ("kitsune", "unknown"):
                logger.info(
                    "Loader: detected foreign framework %r in %s — installing shims",
                    _framework, path.name,
                )
                if progress_cb:
                    try:
                        await progress_cb(
                            f"🔧 Определён формат модуля: <b>{_framework.capitalize()}</b>. "
                            f"Устанавливаю слой совместимости…"
                        )
                    except Exception:
                        pass
                _adapter.ensure_shims(_framework)
            elif _framework == "unknown":
                logger.warning(
                    "Loader: framework unknown for %s — loading as-is", path.name
                )

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

        try:
            spec.loader.exec_module(py_module)
        except ImportError as exc:

            missing_pkg = _extract_missing_package(exc)
            if missing_pkg and not is_builtin:
                logger.info("Loader: missing package %r — attempting auto-install", missing_pkg)
                if progress_cb:
                    try:
                        await progress_cb(f"📦 Устанавливаю зависимость <code>{missing_pkg}</code>...")
                    except Exception:
                        pass
                installed = await _pip_install(missing_pkg)
                if installed:
                    if progress_cb:
                        try:
                            await progress_cb(f"✅ Зависимость <code>{missing_pkg}</code> установлена. Загружаю модуль...")
                        except Exception:
                            pass
                    # Purge any stale/broken namespace-package entries so the
                    # freshly installed package is discovered from scratch.
                    _stale = [k for k in list(sys.modules) if k == missing_pkg or k.startswith(missing_pkg + ".")]
                    for _k in _stale:
                        sys.modules.pop(_k, None)
                    try:
                        spec.loader.exec_module(py_module)
                    except Exception as exc2:
                        sys.modules.pop(module_name, None)
                        raise ModuleLoadError(f"Execution failed after install: {exc2}") from exc2
                else:
                    sys.modules.pop(module_name, None)
                    raise ModuleLoadError(f"Failed to install dependency {missing_pkg!r}: {exc}") from exc
            else:
                sys.modules.pop(module_name, None)
                raise ModuleLoadError(f"Execution failed: {exc}") from exc
        except Exception as exc:
            sys.modules.pop(module_name, None)
            raise ModuleLoadError(f"Execution failed: {exc}") from exc

        mod_class = self._find_module_class(py_module)

        if mod_class is None and _adapter and _framework not in ("kitsune", "unknown"):
            logger.debug("Loader: KitsuneModule subclass not found directly — trying adapter wrap")
            mod_class = _adapter.wrap_unknown_module(py_module)

        if mod_class is None:
            sys.modules.pop(module_name, None)
            _hint = (
                f" (фреймворк {_framework!r} определён, но класс модуля не совместим)"
                if _framework not in ("kitsune", "unknown")
                else ""
            )
            raise ModuleLoadError(f"No KitsuneModule subclass found in {path.name}{_hint}")

        if _adapter and _framework not in ("kitsune", "unknown"):
            try:
                mod_class = _adapter.post_process_class(mod_class, _framework)
                logger.debug(
                    "Loader: post_process_class applied for %s (%s)",
                    mod_class.__name__, _framework,
                )
            except Exception as _pe:
                logger.warning(
                    "Loader: post_process_class failed for %s: %s — proceeding without it",
                    mod_class.__name__, _pe,
                )

        if not getattr(mod_class, "name", ""):
            _hikka_strings = getattr(mod_class, "_hikka_strings", {}) or {}
            _resolved = _hikka_strings.get("name") or mod_class.__name__
            mod_class.name = _resolved

        if mod_class.requires:
            missing = [r for r in mod_class.requires if r not in self._modules]
            if missing:
                sys.modules.pop(module_name, None)
                raise ModuleLoadError(
                    f"Missing dependencies: {', '.join(missing)}"
                )

        import inspect as _inspect
        try:
            _sig = _inspect.signature(mod_class.__init__)
            _params = [p for p in _sig.parameters if p != "self"]
            if len(_params) >= 2:
                mod = mod_class(self._client, self._db)
            else:
                mod = mod_class()
                mod.client = self._client
                mod._client = self._client
                mod.db = self._db
                mod._db = self._db
        except (ValueError, TypeError):
            mod = mod_class(self._client, self._db)
        mod.tg_id = self._client.tg_id
        mod._source_path = str(path)
        mod._is_builtin = is_builtin
        mod._compat_framework = _framework  

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
