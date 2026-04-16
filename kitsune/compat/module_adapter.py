"""
Kitsune Universal Module Adapter
=================================
Автоматически определяет происхождение модуля (Hikka / Heroku+FTG / Kitsune)
и адаптирует его к системе Kitsune без изменения исходного кода модуля.

Поддерживаемые фреймворки:
  • Kitsune  — родной формат, проходит без изменений
  • Hikka    — @loader.command / @loader.watcher / cmd-суффикс / strings = {}
  • Heroku   — идентичен Hikka, пространство имён heroku.*
  • FTG      — Friendly-Telegram / Dragon / совместимые форки

Добавление нового фреймворка:
  1. Добавь паттерны в FRAMEWORK_SIGNATURES
  2. Создай функцию install_<framework>_shims()
  3. Зарегистрируй её в SHIM_INSTALLERS
  4. При необходимости добавь специальную обработку в post_process_class()
"""
from __future__ import annotations

import inspect
import logging
import re
import sys
import types
import typing

logger = logging.getLogger(__name__)

# ─────────────────────────── сигнатуры фреймворков ───────────────────────────

# (pattern, weight)  — чем выше вес, тем сильнее признак
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
        (r"loader\.Module\b", 3),           # FTG совместим с Hikka стилем
    ],
}

_KITSUNE_PATTERNS: list[str] = [
    r"from.*kitsune.*import",
    r"KitsuneModule",
    r"@command\(",
    r"@watcher\(",
]


def detect_framework(source: str) -> str:
    """
    Определяет фреймворк по исходному коду модуля.

    Returns:
        'kitsune' | 'hikka' | 'heroku' | 'ftg' | 'unknown'
    """
    # Быстрая проверка: Kitsune-родной модуль
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
        # Последний шанс: ищем унаследование от Module с cmd-суффиксом
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


# ─────────────────────────── установка шимов ─────────────────────────────────

def install_hikka_shims() -> None:
    """Устанавливает поддельные модули hikka.* в sys.modules."""
    from .hikka import apply as _apply_hikka
    _apply_hikka()
    logger.debug("module_adapter: hikka shims installed")


def install_heroku_shims() -> None:
    """Устанавливает поддельные модули heroku.* в sys.modules."""
    from .heroku import apply as _apply_heroku
    _apply_heroku()
    logger.debug("module_adapter: heroku shims installed")


def install_ftg_shims() -> None:
    """
    FTG/Dragon/Friendly-Telegram — устанавливает шимы под оба пространства имён.
    FTG-модули часто совместимы и с hikka-шимами, поэтому ставим оба.
    """
    install_hikka_shims()
    install_heroku_shims()

    # Дополнительные алиасы, характерные для FTG
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


# Реестр установщиков шимов — добавляй сюда новые фреймворки
SHIM_INSTALLERS: dict[str, typing.Callable[[], None]] = {
    "hikka":  install_hikka_shims,
    "heroku": install_heroku_shims,
    "ftg":    install_ftg_shims,
}


def ensure_shims(framework: str) -> None:
    """Устанавливает шимы для указанного фреймворка (идемпотентно)."""
    installer = SHIM_INSTALLERS.get(framework)
    if installer is not None:
        installer()


# ─────────────────────────── постобработка класса ────────────────────────────

def _get_cmd_name(method_name: str) -> str:
    """
    Выводит имя команды из имени метода по соглашению Hikka/Heroku/FTG.

    Примеры:
        helpcmd      → help
        help_cmd     → help
        somethingcmd → something
    """
    if method_name.endswith("_cmd"):
        return method_name[:-4]
    if method_name.endswith("cmd"):
        return method_name[:-3]
    return method_name


def post_process_class(cls: type, framework: str) -> type:
    """
    Патчит загруженный класс модуля так, чтобы Kitsune мог его зарегистрировать.

    Делает следующее:
      1. Помечает команды (_is_command, _command_name) — распознаёт как
         @loader.command()-декорированные методы, так и cmd-суффикс.
      2. Помечает наблюдателей (_is_watcher).
      3. Разрешает конфликт имён: strings-словарь vs strings()-метод.
      4. Добавляет отсутствующие методы совместимости (get/set/lookup).
    """
    if framework == "kitsune":
        return cls  # Родной модуль — без изменений

    logger.debug(
        "module_adapter: post_process_class  cls=%s  framework=%s",
        cls.__name__, framework,
    )

    # ── 1. Разрешаем конфликт strings-словарь / strings()-метод ─────────────
    _fix_strings_conflict(cls)

    # ── 2. Патчим методы ─────────────────────────────────────────────────────
    for name, obj in list(vars(cls).items()):
        if not (inspect.isfunction(obj) or inspect.iscoroutinefunction(obj)):
            continue

        _patch_command(name, obj)
        _patch_watcher(name, obj)
        _patch_inline_handler(name, obj)
        _patch_callback_handler(name, obj)

    # ── 3. Добавляем методы совместимости если их нет ───────────────────────
    _inject_compat_methods(cls)

    return cls


def _fix_strings_conflict(cls: type) -> None:
    """
    В Hikka/Heroku модулях strings = {"name": "...", ...} — это атрибут класса
    (словарь). Однако KitsuneModule.strings() — это метод. Атрибут подкласса
    перекрывает метод родителя, что ломает вызов self.strings("key").

    Решение:
      • Сохраняем словарь в cls._hikka_strings
      • Убираем атрибут strings из класса (родительский метод становится виден)
      • Родительский strings() умеет работать с _hikka_strings через fallback
    """
    raw = cls.__dict__.get("strings")
    if raw is None or not isinstance(raw, dict):
        return

    type.__setattr__(cls, "_hikka_strings", raw)

    # Ищем метод strings() в родительских классах
    parent_method = None
    for parent in cls.__mro__[1:]:
        v = parent.__dict__.get("strings")
        if callable(v):
            parent_method = v
            break

    if parent_method is not None:
        type.__setattr__(cls, "strings", parent_method)
    else:
        # Нет родительского метода — создаём простую заглушку
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
    """Помечает метод как команду Kitsune если он является командой Hikka/Heroku."""
    # Уже помечен Kitsune
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
    """Отмечает inline-обработчики (Hikka: метод с суффиксом _inline_handler)."""
    if getattr(func, "_is_inline_handler", False):
        return
    if (
        getattr(func, "is_inline_handler", False)
        or name.endswith("_inline_handler")
    ):
        func._is_inline_handler = True
        logger.debug("module_adapter:   → inline_handler %r", name)


def _patch_callback_handler(name: str, func: typing.Any) -> None:
    """Отмечает callback-обработчики (Hikka: метод с суффиксом _callback_handler)."""
    if getattr(func, "_is_callback_handler", False):
        return
    if (
        getattr(func, "is_callback_handler", False)
        or name.endswith("_callback_handler")
    ):
        func._is_callback_handler = True
        logger.debug("module_adapter:   → callback_handler %r", name)


# ─── методы совместимости (добавляются только если их нет) ────────────────────

def _inject_compat_methods(cls: type) -> None:
    """Добавляет вспомогательные методы, которые есть в Hikka но отсутствуют в Kitsune."""

    # get / set  — хранение данных Hikka-модуля в БД Kitsune
    if not _has_own_method(cls, "get"):
        def get(self, key: str, default: typing.Any = None) -> typing.Any:  # type: ignore[misc]
            return self.db.get(f"compat.{type(self).__name__}", key, default)
        cls.get = get  # type: ignore[attr-defined]

    if not _has_own_method(cls, "set"):
        def set(self, key: str, value: typing.Any) -> None:  # type: ignore[misc]
            self.db.set(f"compat.{type(self).__name__}", key, value)
        cls.set = set  # type: ignore[attr-defined]

    # lookup — поиск другого загруженного модуля
    if not _has_own_method(cls, "lookup"):
        def lookup(self, name: str) -> typing.Any:  # type: ignore[misc]
            loader_obj = getattr(self.client, "_kitsune_loader", None)
            return loader_obj.get_module(name) if loader_obj else None
        cls.lookup = lookup  # type: ignore[attr-defined]

    # allmodules — доступ ко всем модулям (Hikka совместимость)
    if not _has_own_method(cls, "allmodules"):
        @property  # type: ignore[misc]
        def allmodules(self):
            loader_obj = getattr(self.client, "_kitsune_loader", None)
            return loader_obj.modules if loader_obj else {}
        cls.allmodules = allmodules  # type: ignore[attr-defined]


def _has_own_method(cls: type, name: str) -> bool:
    """Проверяет, определён ли метод в самом классе (не унаследован)."""
    for klass in cls.__mro__:
        if name in klass.__dict__:
            return True
        if klass is object:
            break
    return False


# ─────────────────────────── оболочка для чужого класса ──────────────────────

def wrap_unknown_module(py_module: types.ModuleType) -> type | None:
    """
    Последний шанс: если после всех шимов так и не нашлось KitsuneModule-
    подкласса, пробуем обернуть любой найденный класс Module.
    Используется только для фреймворков с нестандартным базовым классом.
    """
    from ..core.loader import KitsuneModule

    for obj in vars(py_module).values():
        if not inspect.isclass(obj) or obj is KitsuneModule:
            continue
        # Ищем класс, унаследованный от какого-либо Module
        base_names = {b.__name__ for b in obj.__mro__}
        if "Module" not in base_names:
            continue

        logger.warning(
            "module_adapter: wrapping %s (not a KitsuneModule subclass) — "
            "limited compatibility",
            obj.__name__,
        )

        # Динамически вставляем KitsuneModule в цепочку наследования
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
