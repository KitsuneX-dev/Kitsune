from __future__ import annotations
import ast
import asyncio
import hashlib
import importlib
import importlib.util
import inspect
import logging
import os
import shlex
import sys
import typing
import shutil
from collections import OrderedDict
from pathlib import Path
from types import ModuleType

logger = logging.getLogger(__name__)

_AST_CACHE_MAX_SIZE: int = 128
_PIP_INSTALL_TIMEOUT: float = 300.0
_PIP_STDERR_TAIL: int = 200
_LAST_PIP_STDERR: dict[str, str] = {}

_BLOCKED_IMPORTS: frozenset[str] = frozenset({
    "subprocess", "pty", "ctypes", "multiprocessing",
    "socket", "pickle", "marshal",
    "code", "codeop", "compileall", "py_compile",
    "shelve", "dbm", "zipimport", "zipapp",
    "runpy", "distutils",
})

_DANGEROUS_OS_ATTRS: frozenset[str] = frozenset({
    "system", "popen", "execv", "execve", "execvp", "execvpe",
    "execl", "execle", "execlp", "execlpe",
    "spawnl", "spawnle", "spawnlp", "spawnlpe",
    "spawnv", "spawnve", "spawnvp", "spawnvpe",
    "fork", "forkpty", "kill",
})

_BLOCKED_ATTRS: frozenset[str] = frozenset({
    "__import__", "__loader__", "__builtins__",
    "system", "popen", "Popen", "call", "run",
})

_BUILTIN_MODULES_DIR_CACHED: Path | None = None

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
        text = event.message.raw_text or event.message.text or ""
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
def command(
    name: str | None = None,
    *,
    required: "int | str" = 0,
    aliases: list[str] | None = None,
    incoming: bool = False,
) -> typing.Callable:
    if required is not None and not isinstance(required, (int, str)):
        raise TypeError(
            f"@command(required=...) must be int (bitmask) or str (role name), "
            f"got {type(required).__name__}"
        )
    if isinstance(required, str) and not required.strip():
        raise ValueError("@command(required=...) string role name must be non-empty")
    def decorator(func: typing.Callable) -> typing.Callable:
        func._is_command = True
        func._command_name = name or func.__name__.removesuffix("_cmd")
        func._required = required
        func._aliases = aliases or []
        func._incoming = bool(incoming) or isinstance(required, str)
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
def inline_handler(
    *,
    only_own: bool = False,
) -> typing.Callable:
    def decorator(func: typing.Callable) -> typing.Callable:
        func._is_inline_handler = True
        func._inline_only_own   = only_own
        return func
    return decorator
class _ASTScanner(ast.NodeVisitor):
    def __init__(self) -> None:
        self.errors: list[str] = []

    @staticmethod
    def _is_dynamic_arg(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant):
            return False
        return True

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

        if isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "importlib":
                if not node.args:
                    self.errors.append(
                        f"Blocked importlib.import_module without arguments (line {node.lineno})"
                    )
                elif self._is_dynamic_arg(node.args[0]):

                    self.errors.append(
                        f"Blocked dynamic importlib.import_module call (line {node.lineno})"
                    )
                else:
                    root = str(node.args[0].value).split(".")[0]
                    if root in _BLOCKED_IMPORTS:
                        self.errors.append(
                            f"Blocked importlib.import_module: {node.args[0].value!r} (line {node.lineno})"
                        )
        if isinstance(node.func, ast.Name) and node.func.id in ("exec", "eval"):
            for arg in node.args:
                if isinstance(arg, ast.Call):
                    if isinstance(arg.func, ast.Attribute) and arg.func.attr in (
                        "b64decode", "b32decode", "b16decode", "decode",
                        "decompress", "decodestring",
                    ):
                        self.errors.append(
                            f"Blocked obfuscated {node.func.id}() with encoded payload (line {node.lineno})"
                        )
                    if isinstance(arg.func, ast.Attribute) and isinstance(arg.func.value, ast.Call):
                        inner = arg.func.value
                        if isinstance(inner.func, ast.Name) and inner.func.id == "__import__":
                            self.errors.append(
                                f"Blocked obfuscated {node.func.id}() via __import__ chain (line {node.lineno})"
                            )

        if isinstance(node.func, ast.Name) and node.func.id == "__import__":
            if not node.args:
                self.errors.append(
                    f"Blocked __import__ without arguments (line {node.lineno})"
                )
            elif self._is_dynamic_arg(node.args[0]):

                self.errors.append(
                    f"Blocked dynamic __import__ call (line {node.lineno})"
                )
            else:
                root = str(node.args[0].value).split(".")[0]
                if root in _BLOCKED_IMPORTS:
                    self.errors.append(
                        f"Blocked __import__: {node.args[0].value} (line {node.lineno})"
                    )
        if isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                attr = str(node.args[1].value)
                if attr in _BLOCKED_ATTRS or attr in _DANGEROUS_OS_ATTRS:
                    self.errors.append(
                        f"Blocked getattr access to {attr!r} (line {node.lineno})"
                    )
        if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec", "compile"):
            if not node.args:
                self.errors.append(
                    f"Blocked {node.func.id} without arguments (line {node.lineno})"
                )
            elif self._is_dynamic_arg(node.args[0]):

                self.errors.append(
                    f"Blocked dynamic {node.func.id} call (line {node.lineno})"
                )
            else:
                src = str(node.args[0].value)
                low = src.lower()
                bad_tokens = list(_BLOCKED_IMPORTS) + ["__import__", "__builtins__", "os.system", "os.popen", "os.exec"]
                for blocked in bad_tokens:
                    if blocked in low:
                        self.errors.append(
                            f"Blocked {node.func.id}() containing {blocked!r} (line {node.lineno})"
                        )
                        break
        if isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            base = node.func.value
            if isinstance(base, ast.Name):
                if base.id == "os" and attr_name in _DANGEROUS_OS_ATTRS:
                    self.errors.append(
                        f"Blocked os.{attr_name}() call (line {node.lineno})"
                    )
        self.generic_visit(node)
    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _BLOCKED_ATTRS:
            if isinstance(node.value, ast.Name) and node.value.id in _BLOCKED_IMPORTS:
                self.errors.append(
                    f"Blocked attribute access: {node.value.id}.{node.attr} (line {node.lineno})"
                )
        if isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr in _DANGEROUS_OS_ATTRS:
            self.errors.append(
                f"Blocked os.{node.attr} access (line {node.lineno})"
            )
        if node.attr in ("__builtins__", "__loader__", "__import__"):
            self.errors.append(
                f"Blocked dunder attribute access: {node.attr} (line {node.lineno})"
            )
        self.generic_visit(node)
    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.value, ast.Name) and node.value.id == "__builtins__":
            self.errors.append(
                f"Blocked __builtins__ subscript access (line {node.lineno})"
            )
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            ns_func = node.value.func.id
            if ns_func in ("globals", "locals", "vars"):
                slice_node = node.slice
                if isinstance(slice_node, ast.Index):
                    slice_node = slice_node.value
                if isinstance(slice_node, ast.Constant):
                    key = str(slice_node.value)
                    if (
                        key in _BLOCKED_IMPORTS
                        or key in _BLOCKED_ATTRS
                        or key in _DANGEROUS_OS_ATTRS
                        or key in ("os", "sys", "builtins", "__builtins__", "__import__")
                    ):
                        self.errors.append(
                            f"Blocked {ns_func}()[{key!r}] subscript access (line {node.lineno})"
                        )
                else:
                    self.errors.append(
                        f"Blocked dynamic {ns_func}()[...] subscript access (line {node.lineno})"
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
_ast_cache: OrderedDict[str, ast.AST] = OrderedDict()

def _scan_ast_with_cache(source: str, filename: str = "<module>") -> None:
    key = hashlib.sha256(source.encode()).hexdigest()
    cached = _ast_cache.get(key)
    if cached is not None:
        _ast_cache.move_to_end(key)
        return
    _scan_ast(source, filename)
    _ast_cache[key] = ast.parse(source, filename=filename)
    _ast_cache.move_to_end(key)
    while len(_ast_cache) > _AST_CACHE_MAX_SIZE:
        _ast_cache.popitem(last=False)

def _ast_cache_clear() -> None:
    _ast_cache.clear()
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
    "matplotlib": "matplotlib",
    "numpy": "numpy",
    "spotipy": "spotipy",
    "mutagen": "mutagen",
    "pydub": "pydub",
    "qrcode": "qrcode",
    "aiofiles": "aiofiles",
    "fake_useragent": "fake-useragent",
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

async def _run_cmd(args: list[str], timeout: float | None = None) -> tuple[bool, str]:
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        if timeout is not None:
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                return False, f"command timed out after {timeout:.0f}s"
        else:
            _, stderr = await proc.communicate()
        return proc.returncode == 0, stderr.decode(errors="replace")
    except FileNotFoundError:
        return False, "command not found"
    except Exception as exc:
        return False, str(exc)

def _is_permission_error(stderr: str) -> bool:
    _permission_markers = (
        "permission denied",
        "could not open lock file",
        "are you root",
        "operation not permitted",
        "eacces",
        "eperm",
    )
    low = stderr.lower()
    return any(m in low for m in _permission_markers)

def _build_pip_base_cmd() -> list[str]:
    override = os.environ.get("KITSUNE_PIP_CMD", "").strip()
    if override:
        try:
            parts = shlex.split(override)
        except ValueError:
            parts = []
        if parts:
            return parts
    return [sys.executable, "-m", "pip"]

def _record_pip_stderr(package: str, pip_name: str, stderr: str) -> None:
    tail = (stderr or "").strip()
    if len(tail) > _PIP_STDERR_TAIL:
        tail = tail[-_PIP_STDERR_TAIL:]
    _LAST_PIP_STDERR[package] = tail
    if pip_name != package:
        _LAST_PIP_STDERR[pip_name] = tail

def get_last_pip_stderr(package: str) -> str:
    return _LAST_PIP_STDERR.get(package, "")

async def _pip_install(package: str) -> bool:
    pip_name = _IMPORT_TO_PIP.get(package, package)
    is_termux = "com.termux" in os.environ.get("PREFIX", "") or os.path.isdir("/data/data/com.termux")
    _NAMESPACE_PKGS = {"google-generativeai", "google-cloud-storage", "google-auth"}
    base = _build_pip_base_cmd()
    args = base + ["install", pip_name, "--quiet", "--no-warn-script-location"]
    if pip_name in _NAMESPACE_PKGS:
        args.append("--upgrade")
    if is_termux:
        args += ["--prefer-binary", "--no-build-isolation"]

    ok, stderr = await _run_cmd(args, timeout=_PIP_INSTALL_TIMEOUT)
    if ok:
        logger.info("Loader: pip installed %r successfully", pip_name)
        _LAST_PIP_STDERR.pop(package, None)
        _LAST_PIP_STDERR.pop(pip_name, None)
        importlib.invalidate_caches()
        return True

    if _is_permission_error(stderr):
        logger.info("Loader: pip install %r failed with permission error, retrying with sudo", pip_name)
        ok, stderr = await _run_cmd(["sudo"] + args, timeout=_PIP_INSTALL_TIMEOUT)
        if ok:
            logger.info("Loader: pip installed %r successfully (sudo)", pip_name)
            _LAST_PIP_STDERR.pop(package, None)
            _LAST_PIP_STDERR.pop(pip_name, None)
            importlib.invalidate_caches()
            return True
        logger.warning("Loader: pip install %r failed even with sudo: %s", pip_name, stderr[:300])
    else:
        logger.warning("Loader: pip install %r failed: %s", pip_name, stderr[:300])

    _record_pip_stderr(package, pip_name, stderr)
    return False

_SYSTEM_UTIL_TO_PKG: dict[str, dict[str, str]] = {
    "ffmpeg":    {"apt": "ffmpeg",       "termux": "ffmpeg"},
    "ffprobe":   {"apt": "ffmpeg",       "termux": "ffmpeg"},
    "convert":   {"apt": "imagemagick",  "termux": "imagemagick"},
    "wget":      {"apt": "wget",         "termux": "wget"},
    "curl":      {"apt": "curl",         "termux": "curl"},
    "yt-dlp":    {"apt": "yt-dlp",       "termux": "yt-dlp"},
    "gallery-dl":{"apt": "gallery-dl",   "termux": "gallery-dl"},
}

def _is_termux() -> bool:
    import os as _os
    return "com.termux" in _os.environ.get("PREFIX", "") or _os.path.isdir("/data/data/com.termux")

async def _system_install(utility: str) -> bool:
    pkg_map = _SYSTEM_UTIL_TO_PKG.get(utility)
    if not pkg_map:
        logger.warning("Loader: no system package known for utility %r", utility)
        return False

    if _is_termux():

        cmd = ["termux-pkg", "install", "-y", pkg_map["termux"]]
        ok, stderr = await _run_cmd(cmd)
        if ok:
            logger.info("Loader: system package for %r installed (termux)", utility)
            return True
        logger.warning("Loader: termux-pkg install %r failed: %s", utility, stderr[:200])
        return False

    cmd = ["apt-get", "install", "-y", "--no-install-recommends", pkg_map["apt"]]
    ok, stderr = await _run_cmd(cmd)
    if ok:
        logger.info("Loader: system package for %r installed successfully", utility)
        return True

    if _is_permission_error(stderr):
        logger.info(
            "Loader: apt-get for %r failed with permission error, retrying with sudo", utility
        )
        ok, stderr = await _run_cmd(["sudo"] + cmd)
        if ok:
            logger.info("Loader: system package for %r installed successfully (sudo)", utility)
            return True
        logger.warning(
            "Loader: apt-get install %r failed even with sudo: %s", utility, stderr[:200]
        )
    else:
        logger.warning("Loader: apt-get install %r failed: %s", utility, stderr[:200])

    return False

async def _ensure_pip_deps(
    deps: list[str],
    progress_cb=None,
    already_installed: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    ok: list[str] = []
    failed: list[str] = []
    if already_installed is None:
        already_installed = set()
    for dep in deps:
        if dep in already_installed:
            ok.append(dep)
            continue
        pip_name = _IMPORT_TO_PIP.get(dep, dep)
        if progress_cb:
            try:
                await progress_cb(
                    f"📦 Устанавливаю зависимость <code>{pip_name}</code>..."
                )
            except Exception:
                pass
        if await _pip_install(dep):
            ok.append(dep)
            already_installed.add(dep)
        else:
            failed.append(pip_name)
    return ok, failed

async def _ensure_system_deps(
    utils: list[str],
    progress_cb=None,
) -> tuple[list[str], list[str]]:
    ok: list[str] = []
    failed: list[str] = []
    for util in utils:
        if shutil.which(util) is not None:
            ok.append(util)
            continue
        if progress_cb:
            try:
                await progress_cb(
                    f"🔧 Устанавливаю системную утилиту <code>{util}</code>..."
                )
            except Exception:
                pass
        if await _system_install(util):
            if shutil.which(util) is not None:
                ok.append(util)
            else:
                logger.warning("Loader: %r installed but still not found in PATH", util)
                failed.append(util)
        else:
            failed.append(util)
    return ok, failed

_INIT_SIGNATURE_CACHE: dict[type, int] = {}

def _module_param_count(mod_class: type) -> int:
    cached = _INIT_SIGNATURE_CACHE.get(mod_class)
    if cached is not None:
        return cached
    try:
        sig = inspect.signature(mod_class.__init__)
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
        _scan_ast_with_cache(source, filename=url)
        user_dir = Path.home() / ".kitsune" / "modules"
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
    async def load_from_file(self, path: Path, progress_cb=None) -> KitsuneModule:
        source = path.read_text(encoding="utf-8")
        _scan_ast_with_cache(source, filename=str(path))
        return await self._load_from_path(
            path, is_builtin=False, progress_cb=progress_cb,
            already_scanned=True, prefetched_source=source,
        )
    async def unload_module(self, name: str) -> bool:
        mod = self._modules.get(name.lower())
        if mod is None:
            return False
        try:
            await mod.on_unload()
        except Exception:
            logger.exception("Loader: on_unload failed for %s", name)
        for cmd_name in list(self._dispatcher._commands):
            entry = self._dispatcher._commands[cmd_name]
            handler = entry[0]
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
        mod_class = self._find_module_class(py_module)
        if mod_class is None:
            sys.modules.pop(module_name, None)
            raise ModuleLoadError(f"No KitsuneModule subclass found in {path.name}")
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
        try:
            if param_count >= 2:
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
                self._dispatcher.register_command(name, method, required, module=mod)
                for alias in getattr(method, "_aliases", []):
                    self._dispatcher.register_command(alias, method, required, module=mod)
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
