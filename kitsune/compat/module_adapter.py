from __future__ import annotations

import inspect
import logging
import re
import sys
import types
import typing

logger = logging.getLogger(__name__)

FRAMEWORK_SIGNATURES: dict[str, list[tuple[str, int]]] = {
    "hikka": [
        (r"from\s+hikka\s+import", 10),
        (r"from\s+hikka\.", 10),
        (r"import\s+hikka\b", 8),
        (r"hikkatl\b", 6),
        (r"@loader\.tds\b", 5),
        (r"loader\.Module\b", 4),
        (r"loader\.command\(\)", 4),
        (r"loader\.ModuleConfig\b", 3),
        (r"loader\.ConfigValue\b", 3),
    ],
    "heroku": [
        (r"from\s+heroku\s+import", 10),
        (r"from\s+heroku\.", 10),
        (r"import\s+heroku\b", 8),
        (r"herokutl\b", 6),
        (r"heroku\.Module\b", 4),
        (r"heroku\.command\(\)", 4),
        (r"heroku\.ModuleConfig\b", 3),
    ],
    "ftg": [
        (r"from\s+FTG\s+import", 10),
        (r"from\s+tg_bot\s+import", 10),
        (r"from\s+telethon_helper\s+import", 8),
        (r"loader\.Module\b", 3),           
    ],
}

_KITSUNE_PATTERNS: list[str] = [
    r"from.*kitsune.*import",
    r"KitsuneModule",
    r"@command\(",
    r"@watcher\(",
]

def detect_framework(source: str) -> str:

    for pat in _KITSUNE_PATTERNS:
        if re.search(pat, source):
            return "kitsune"

    scores: dict[str, int] = {fw: 0 for fw in FRAMEWORK_SIGNATURES}
    for fw, patterns in FRAMEWORK_SIGNATURES.items():
        for pat, weight in patterns:
            if re.search(pat, source):
                scores[fw] += weight

    best_fw = max(scores, key=lambda k: scores[k])
    best_score = scores[best_fw]

    if best_score == 0:

        if re.search(r"class\s+\w+\s*\(\s*\w*[Mm]odule\s*\)", source) and re.search(
            r"async\s+def\s+\w+cmd\s*\(", source
        ):
            logger.debug("module_adapter: detected FTG-style module by naming convention")
            return "ftg"
        return "unknown"

    logger.debug(
        "module_adapter: detected framework=%r  scores=%s", best_fw, scores
    )
    return best_fw

def install_hikka_shims() -> None:
    from .hikka import apply as _apply_hikka
    _apply_hikka()
    logger.debug("module_adapter: hikka shims installed")

def install_heroku_shims() -> None:
    from .heroku import apply as _apply_heroku
    _apply_heroku()
    logger.debug("module_adapter: heroku shims installed")

def install_ftg_shims() -> None:
    install_hikka_shims()
    install_heroku_shims()

    _alias_modules = {
        "FTG":           "hikka",
        "tg_bot":        "hikka",
        "FTG.loader":    "hikka.loader",
        "FTG.utils":     "hikka.utils",
        "tg_bot.loader": "hikka.loader",
        "tg_bot.utils":  "hikka.utils",
    }
    for alias, real in _alias_modules.items():
        if alias not in sys.modules and real in sys.modules:
            sys.modules[alias] = sys.modules[real]

    logger.debug("module_adapter: FTG shims installed")

SHIM_INSTALLERS: dict[str, typing.Callable[[], None]] = {
    "hikka":  install_hikka_shims,
    "heroku": install_heroku_shims,
    "ftg":    install_ftg_shims,
}

def ensure_shims(framework: str) -> None:
    installer = SHIM_INSTALLERS.get(framework)
    if installer is not None:
        installer()

def _get_cmd_name(method_name: str) -> str:
    if method_name.endswith("_cmd"):
        return method_name[:-4]
    if method_name.endswith("cmd"):
        return method_name[:-3]
    return method_name

def post_process_class(cls: type, framework: str) -> type:
    if framework == "kitsune":
        return cls  

    logger.debug(
        "module_adapter: post_process_class  cls=%s  framework=%s",
        cls.__name__, framework,
    )

    _fix_strings_conflict(cls)

    for name, obj in list(vars(cls).items()):
        if not (inspect.isfunction(obj) or inspect.iscoroutinefunction(obj)):
            continue

        _patch_command(name, obj)
        _patch_watcher(name, obj)
        _patch_inline_handler(name, obj)
        _patch_callback_handler(name, obj)

    _inject_compat_methods(cls)

    return cls

def _fix_strings_conflict(cls: type) -> None:
    raw = cls.__dict__.get("strings")
    if raw is None or not isinstance(raw, dict):
        return

    type.__setattr__(cls, "_hikka_strings", raw)

    parent_method = None
    for parent in cls.__mro__[1:]:
        v = parent.__dict__.get("strings")
        if callable(v):
            parent_method = v
            break

    if parent_method is not None:
        type.__setattr__(cls, "strings", parent_method)
    else:

        def _strings_fallback(self, key: str, **kwargs: typing.Any) -> str:
            d: dict = getattr(self, "_hikka_strings", {}) or {}
            text = d.get(key, key)
            return text.format(**kwargs) if kwargs else text

        type.__setattr__(cls, "strings", _strings_fallback)

    logger.debug(
        "module_adapter: fixed strings conflict for %s (%d keys moved)",
        cls.__name__, len(raw),
    )

def _patch_command(name: str, func: typing.Any) -> None:

    if getattr(func, "_is_command", False):
        return

    is_hikka_cmd = (
        getattr(func, "is_command", False)
        or getattr(func, "is_command_func", False)
    )

    is_suffix_cmd = (
        not name.startswith("_")
        and (name.endswith("cmd") or name.endswith("_cmd"))
        and name not in ("watcher", "watcher_cmd")
    )

    if not (is_hikka_cmd or is_suffix_cmd):
        return

    func._is_command   = True
    func._command_name = getattr(func, "_command_name", None) or _get_cmd_name(name)
    func._required     = getattr(func, "_required", 0)
    func._aliases      = getattr(func, "_aliases", [])
    logger.debug("module_adapter:   → command %r → %r", name, func._command_name)

def _patch_watcher(name: str, func: typing.Any) -> None:
    if getattr(func, "_is_watcher", False):
        return
    if getattr(func, "is_watcher", False) or name == "watcher":
        func._is_watcher      = True
        func._watcher_filter  = getattr(func, "_watcher_filter", None)
        logger.debug("module_adapter:   → watcher %r", name)

def _patch_inline_handler(name: str, func: typing.Any) -> None:
    if getattr(func, "_is_inline_handler", False):
        return
    if (
        getattr(func, "is_inline_handler", False)
        or name.endswith("_inline_handler")
    ):
        func._is_inline_handler = True
        logger.debug("module_adapter:   → inline_handler %r", name)

def _patch_callback_handler(name: str, func: typing.Any) -> None:
    if getattr(func, "_is_callback_handler", False):
        return
    if (
        getattr(func, "is_callback_handler", False)
        or name.endswith("_callback_handler")
    ):
        func._is_callback_handler = True
        logger.debug("module_adapter:   → callback_handler %r", name)

def _inject_compat_methods(cls: type) -> None:

    if not _has_own_method(cls, "get"):
        def get(self, key: str, default: typing.Any = None) -> typing.Any:  
            return self.db.get(f"compat.{type(self).__name__}", key, default)
        cls.get = get  

    if not _has_own_method(cls, "set"):
        def set(self, key: str, value: typing.Any) -> None:  
            self.db.set(f"compat.{type(self).__name__}", key, value)
        cls.set = set  

    if not _has_own_method(cls, "lookup"):
        def lookup(self, name: str) -> typing.Any:  
            loader_obj = getattr(self.client, "_kitsune_loader", None)
            return loader_obj.get_module(name) if loader_obj else None
        cls.lookup = lookup  

    if not _has_own_method(cls, "allmodules"):
        @property  
        def allmodules(self):
            loader_obj = getattr(self.client, "_kitsune_loader", None)
            return loader_obj.modules if loader_obj else {}
        cls.allmodules = allmodules  

def _has_own_method(cls: type, name: str) -> bool:
    for klass in cls.__mro__:
        if name in klass.__dict__:
            return True
        if klass is object:
            break
    return False

def wrap_unknown_module(py_module: types.ModuleType) -> type | None:
    from ..core.loader import KitsuneModule

    for obj in vars(py_module).values():
        if not inspect.isclass(obj) or obj is KitsuneModule:
            continue

        base_names = {b.__name__ for b in obj.__mro__}
        if "Module" not in base_names:
            continue

        logger.warning(
            "module_adapter: wrapping %s (not a KitsuneModule subclass) — "
            "limited compatibility",
            obj.__name__,
        )

        try:
            new_bases = (KitsuneModule,) + tuple(
                b for b in obj.__bases__ if b is not object
            )
            new_cls = type(obj.__name__, new_bases, dict(obj.__dict__))
            return new_cls
        except TypeError as exc:
            logger.error("module_adapter: wrap_unknown_module failed: %s", exc)
            return None

    return None
