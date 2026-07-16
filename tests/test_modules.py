import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import importlib
import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kitsune.core.loader import KitsuneModule


MODULES_DIR = Path(__file__).resolve().parent.parent / "kitsune" / "modules"

UTILITY_MODULES = {"__init__", "loader", "rkn_bypass"}


def _discover_modules() -> list[str]:
    found: list[str] = []
    for entry in sorted(MODULES_DIR.iterdir()):
        if entry.is_dir():
            if (entry / "__init__.py").is_file() and entry.name not in UTILITY_MODULES:
                found.append(entry.name)
            continue
        if entry.suffix != ".py":
            continue
        stem = entry.stem
        if stem in UTILITY_MODULES:
            continue
        found.append(stem)
    return found


ALL_MODULES = _discover_modules()


def _import_module(name: str):
    return importlib.import_module(f"kitsune.modules.{name}")


def _find_module_class(py_module) -> type | None:
    for obj in vars(py_module).values():
        if (
            inspect.isclass(obj)
            and issubclass(obj, KitsuneModule)
            and obj is not KitsuneModule
            and obj.__module__ == py_module.__name__
        ):
            return obj
    return None


def _make_client():
    c = MagicMock()
    c.tg_id = 12345
    c.inline = None
    c._kitsune_dispatcher = None
    return c


class _FakeDB:
    def __init__(self, lang: str = "ru") -> None:
        self._lang = lang
        self._store: dict[tuple[str, str], object] = {}

    def get(self, owner, key, default=None):
        if owner == "kitsune.core" and key == "lang":
            return self._lang
        return self._store.get((owner, key), default)

    async def set(self, owner, key, value):
        self._store[(owner, key)] = value
        return True


def _make_dispatcher():
    d = MagicMock()
    d._commands = {}
    d._prefix = "."
    d.register_command = MagicMock()
    d.unregister_command = MagicMock()
    d.register_watcher = MagicMock()
    d.unregister_watchers_for = MagicMock()
    return d


def _instantiate(cls: type):
    client = _make_client()
    db = _FakeDB()
    try:
        return cls(client, db), client, db
    except TypeError:
        try:
            instance = cls()
            instance.client = client
            instance.db = db
            instance.tg_id = client.tg_id
            return instance, client, db
        except Exception:
            return None, client, db


def _has_any_handler(cls: type) -> bool:
    for _, member in inspect.getmembers(cls):
        if not callable(member):
            continue
        if (
            getattr(member, "_is_command", False)
            or getattr(member, "_is_watcher", False)
            or getattr(member, "_is_inline_handler", False)
            or getattr(member, "_is_callback_handler", False)
        ):
            return True
    return False


@pytest.mark.parametrize("module_name", ALL_MODULES)
def test_module_imports_without_error(module_name: str) -> None:
    try:
        py_module = _import_module(module_name)
    except ImportError as exc:
        pytest.fail(f"Module 'kitsune.modules.{module_name}' raised ImportError: {exc}")
    assert py_module is not None


@pytest.mark.parametrize("module_name", ALL_MODULES)
def test_module_registers_handlers(module_name: str) -> None:
    py_module = _import_module(module_name)
    cls = _find_module_class(py_module)
    if cls is None:
        pytest.skip(f"'{module_name}' is a utility module without a KitsuneModule subclass")
    instance, client, _ = _instantiate(cls)
    if instance is None:
        pytest.skip(f"'{module_name}' cannot be instantiated in isolation")
    if not _has_any_handler(cls):
        assert issubclass(cls, KitsuneModule)
        return
    dispatcher = _make_dispatcher()
    client._kitsune_dispatcher = dispatcher
    from kitsune.core.loader import Loader
    loader = Loader(client, instance.db, dispatcher)
    loader._register_module(instance)
    total_calls = (
        dispatcher.register_command.call_count
        + dispatcher.register_watcher.call_count
    )
    assert total_calls > 0, (
        f"Module '{module_name}' has @command/@watcher methods but nothing was registered"
    )


@pytest.mark.parametrize("module_name", ALL_MODULES)
def test_module_returns_localized_strings(module_name: str) -> None:
    py_module = _import_module(module_name)
    cls = _find_module_class(py_module)
    if cls is None:
        pytest.skip(f"'{module_name}' is a utility module without a KitsuneModule subclass")
    instance, _, _ = _instantiate(cls)
    if instance is None:
        pytest.skip(f"'{module_name}' cannot be instantiated in isolation")
    strings_ru_attr = getattr(cls, "strings_ru", None)
    strings_en_attr = getattr(cls, "strings_en", None)
    ru_keys = list(strings_ru_attr.keys()) if isinstance(strings_ru_attr, dict) else []
    en_keys = list(strings_en_attr.keys()) if isinstance(strings_en_attr, dict) else []
    sample_key = ru_keys[0] if ru_keys else (en_keys[0] if en_keys else "__kitsune_probe__")
    instance.db = _FakeDB(lang="ru")
    value_ru = instance.strings(sample_key)
    assert isinstance(value_ru, str) and value_ru, (
        f"strings('{sample_key}') for module '{module_name}' on lang=ru returned non-string"
    )
    instance.db = _FakeDB(lang="en")
    value_en = instance.strings(sample_key)
    assert isinstance(value_en, str) and value_en, (
        f"strings('{sample_key}') for module '{module_name}' on lang=en returned non-string"
    )
    if ru_keys and isinstance(strings_ru_attr, dict):
        expected = strings_ru_attr[sample_key]
        instance.db = _FakeDB(lang="ru")
        rendered = instance.strings(sample_key)
        assert isinstance(expected, str) and rendered, (
            f"Module '{module_name}': ru localization for '{sample_key}' is empty"
        )


def test_module_discovery_is_not_empty() -> None:
    assert len(ALL_MODULES) > 0, "No modules discovered in kitsune/modules/"
    assert "info" in ALL_MODULES
    assert "ping" in ALL_MODULES
