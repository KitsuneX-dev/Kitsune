import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# --------------------------------------------------------------------------- #
# Проблема 1, пункт 1: маппинг импорта `google` → pip-пакет `google-genai`.
# --------------------------------------------------------------------------- #

def test_import_to_pip_maps_google_to_new_sdk():
    from kitsune.core.loader import _IMPORT_TO_PIP
    assert _IMPORT_TO_PIP["google"] == "google-genai"
    assert _IMPORT_TO_PIP["google"] != "google-generativeai"


@pytest.mark.asyncio
async def test_pip_install_google_uses_new_sdk_name(monkeypatch):
    from kitsune.core import loader as ld
    captured = {}

    async def fake_run(args, timeout=None):
        captured["args"] = list(args)
        return True, ""

    monkeypatch.setattr(ld, "_run_cmd", fake_run)
    ok = await ld._pip_install("google")
    assert ok is True
    assert "google-genai" in captured["args"]
    assert "google-generativeai" not in captured["args"]


@pytest.mark.asyncio
async def test_pip_install_google_genai_is_namespace_pkg(monkeypatch):
    """google-genai должен ставиться как namespace-пакет (с --upgrade),
    при этом старый google-generativeai остаётся в списке ради совместимости."""
    from kitsune.core import loader as ld
    captured = {}

    async def fake_run(args, timeout=None):
        captured["args"] = list(args)
        return True, ""

    monkeypatch.setattr(ld, "_run_cmd", fake_run)
    await ld._pip_install("google")
    assert "--upgrade" in captured["args"]


# --------------------------------------------------------------------------- #
# Хелпер для сборки диспетчера с моками.
# --------------------------------------------------------------------------- #

def _make_dispatcher():
    from kitsune.core.dispatcher import CommandDispatcher
    client = MagicMock()
    db = MagicMock()
    security = MagicMock()
    return CommandDispatcher(client, db, security, prefix=".")


# --------------------------------------------------------------------------- #
# Проблема 2, пункт 3: снятие watcher'а по владельцу-модулю,
# в т.ч. для несвязанной функции без __self__.
# --------------------------------------------------------------------------- #

def test_unregister_watcher_by_owner_bound_method():
    disp = _make_dispatcher()

    class FakeModule:
        def watch(self, event):
            pass

    mod = FakeModule()
    disp.register_watcher(mod.watch, None, module=mod)
    assert len(disp._watchers) == 1
    disp.unregister_watchers_for(mod)
    assert len(disp._watchers) == 0


def test_unregister_watcher_by_owner_unbound_function():
    """Watcher, зарегистрированный как обычная функция/замыкание (без
    __self__), всё равно должен сниматься по явно указанному владельцу."""
    disp = _make_dispatcher()

    class FakeModule:
        pass

    mod = FakeModule()

    def standalone_watcher(event):
        pass

    assert getattr(standalone_watcher, "__self__", None) is None
    disp.register_watcher(standalone_watcher, None, module=mod)
    assert len(disp._watchers) == 1

    disp.unregister_watchers_for(mod)
    assert len(disp._watchers) == 0


def test_unregister_watcher_keeps_other_modules():
    disp = _make_dispatcher()

    class ModA:
        pass

    class ModB:
        pass

    a, b = ModA(), ModB()

    def wa(event):
        pass

    def wb(event):
        pass

    disp.register_watcher(wa, None, module=a)
    disp.register_watcher(wb, None, module=b)
    assert len(disp._watchers) == 2

    disp.unregister_watchers_for(a)
    assert len(disp._watchers) == 1
    remaining_owner = disp._watchers[0][3]
    assert remaining_owner is b


def test_unregister_watcher_falls_back_to_self():
    """Обратная совместимость: register_watcher без явного module по-прежнему
    определяет владельца через __self__ и снимается по нему."""
    disp = _make_dispatcher()

    class FakeModule:
        def watch(self, event):
            pass

    mod = FakeModule()
    disp.register_watcher(mod.watch)
    assert len(disp._watchers) == 1
    disp.unregister_watchers_for(mod)
    assert len(disp._watchers) == 0


# --------------------------------------------------------------------------- #
# Интеграционные тесты выгрузки: sys.modules и inline-хендлеры.
# --------------------------------------------------------------------------- #

class _FakeInline:
    """Минимальный инлайн-менеджер, повторяющий контракт inline/core.py."""

    def __init__(self):
        self._inline_handlers = []

    def register_inline_handler(self, func):
        only_own = bool(getattr(func, "_inline_only_own", False))
        entry = (func, only_own)
        if entry not in self._inline_handlers:
            self._inline_handlers.append(entry)

    def unregister_inline_handler(self, func):
        def _same(h):
            if h is func:
                return True
            h_self = getattr(h, "__self__", None)
            f_self = getattr(func, "__self__", None)
            if h_self is not None and h_self is f_self:
                return getattr(h, "__func__", None) is getattr(func, "__func__", None)
            return False

        self._inline_handlers = [
            (h, o) for h, o in self._inline_handlers if not _same(h)
        ]


def _make_loader(inline=None):
    from kitsune.core.loader import Loader
    client = MagicMock()
    client.tg_id = 1
    client.inline = inline
    client._kitsune_dispatcher = None
    db = MagicMock()
    db.get.return_value = None
    dispatcher = MagicMock()
    dispatcher._commands = {}
    return Loader(client, db, dispatcher)


@pytest.mark.asyncio
async def test_unload_purges_sys_modules(tmp_path):
    loader = _make_loader()
    mod_file = tmp_path / "purge_me_mod.py"
    mod_file.write_text(textwrap.dedent("""
        from kitsune.core.loader import KitsuneModule, command
        class PurgeMod(KitsuneModule):
            name = "purgemod"
            @command("purgecmd")
            async def c(self, event):
                pass
    """).strip())

    mod = await loader.load_from_file(mod_file)
    module_name = mod._py_module_name
    assert module_name == "kitsune.modules.purge_me_mod"
    assert module_name in sys.modules

    ok = await loader.unload_module("purgemod")
    assert ok is True
    assert module_name not in sys.modules


@pytest.mark.asyncio
async def test_unload_purges_submodules(tmp_path, monkeypatch):
    loader = _make_loader()
    mod_file = tmp_path / "parent_mod.py"
    mod_file.write_text(textwrap.dedent("""
        from kitsune.core.loader import KitsuneModule
        class ParentMod(KitsuneModule):
            name = "parentmod"
    """).strip())

    mod = await loader.load_from_file(mod_file)
    module_name = mod._py_module_name
    sub_name = module_name + ".submod"
    sys.modules[sub_name] = MagicMock()

    await loader.unload_module("parentmod")
    assert module_name not in sys.modules
    assert sub_name not in sys.modules


def test_inline_manager_unregister_matches_rebound_method():
    """unregister_inline_handler в inline/core.py должен снимать хендлер, даже
    если передан не тот же самый bound-method объект (getmembers создаёт новый)."""
    from kitsune.inline import core as inline_core

    mgr = inline_core.InlineManager.__new__(inline_core.InlineManager)
    mgr._inline_handlers = []

    class Mod:
        def handle(self, q):
            pass

    m = Mod()
    mgr.register_inline_handler(m.handle)
    assert len(mgr._inline_handlers) == 1
    rebound = m.handle
    assert rebound is not mgr._inline_handlers[0][0]
    mgr.unregister_inline_handler(rebound)
    assert len(mgr._inline_handlers) == 0


@pytest.mark.asyncio
async def test_unload_unregisters_inline_handlers(tmp_path):
    inline = _FakeInline()
    loader = _make_loader(inline=inline)
    mod_file = tmp_path / "inline_mod.py"
    mod_file.write_text(textwrap.dedent("""
        from kitsune.core.loader import KitsuneModule, inline_handler
        class InlineMod(KitsuneModule):
            name = "inlinemod"
            @inline_handler()
            async def handle(self, query):
                pass
    """).strip())

    await loader.load_from_file(mod_file)
    assert len(inline._inline_handlers) == 1

    await loader.unload_module("inlinemod")
    assert len(inline._inline_handlers) == 0


# --------------------------------------------------------------------------- #
# Проблема 1, пункт 2: venv-осознанное окружение для .sh / терминала.
# --------------------------------------------------------------------------- #

def test_venv_aware_env_puts_sys_executable_dir_first_in_path():
    from kitsune.modules.terminal import _venv_aware_env
    env = _venv_aware_env()
    bin_dir = os.path.dirname(os.path.abspath(sys.executable))
    first = env["PATH"].split(os.pathsep)[0]
    assert first == bin_dir


def test_venv_aware_env_sets_virtual_env_when_pyvenv_cfg_present(monkeypatch, tmp_path):
    from kitsune.modules import terminal
    venv_root = tmp_path / "venv"
    bin_dir = venv_root / "bin"
    bin_dir.mkdir(parents=True)
    (venv_root / "pyvenv.cfg").write_text("home = /usr\n")
    fake_python = bin_dir / "python"
    fake_python.write_text("")

    monkeypatch.setattr(terminal.sys, "executable", str(fake_python))
    monkeypatch.setenv("PYTHONHOME", "/should/be/removed")

    env = terminal._venv_aware_env()
    assert env["VIRTUAL_ENV"] == str(venv_root)
    assert "PYTHONHOME" not in env
    assert env["PATH"].split(os.pathsep)[0] == str(bin_dir)


def test_venv_aware_env_no_virtual_env_without_pyvenv_cfg(monkeypatch, tmp_path):
    from kitsune.modules import terminal
    plain_root = tmp_path / "usr"
    bin_dir = plain_root / "bin"
    bin_dir.mkdir(parents=True)
    fake_python = bin_dir / "python"
    fake_python.write_text("")

    monkeypatch.setattr(terminal.sys, "executable", str(fake_python))
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)

    env = terminal._venv_aware_env()
    assert "VIRTUAL_ENV" not in env
    assert env["PATH"].split(os.pathsep)[0] == str(bin_dir)


def test_venv_aware_env_preserves_base_vars():
    from kitsune.modules.terminal import _venv_aware_env
    env = _venv_aware_env()
    assert env["TERM"] == "xterm-256color"
    assert env["DEBIAN_FRONTEND"] == "noninteractive"
