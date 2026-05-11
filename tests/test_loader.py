                                                                                
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pytest_asyncio
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock


                                                                        
                      
                                                                        

def test_scan_ast_allows_safe_code():
    from kitsune.core.loader import _scan_ast
    safe = textwrap.dedent("""
        import asyncio
        import json
        import re
        from kitsune.core.loader import KitsuneModule, command
        class TestMod(KitsuneModule):
            name = "test"
            @command()
            async def hello_cmd(self, event):
                await event.reply("hi")
    """)
    _scan_ast(safe)                                
def test_scan_ast_blocks_subprocess():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("import subprocess")
def test_scan_ast_blocks_subprocess_from():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("from subprocess import run")
def test_scan_ast_blocks_pty():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("import pty")
def test_scan_ast_blocks_ctypes():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("import ctypes")
def test_scan_ast_blocks_pickle():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("import pickle")
def test_scan_ast_blocks_socket():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("import socket")
def test_scan_ast_blocks_os_system():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("import os\nos.system('ls')")
def test_scan_ast_blocks_os_popen():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("import os\nos.popen('whoami')")
def test_scan_ast_blocks_os_fork():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("import os\nos.fork()")
def test_scan_ast_blocks_dunder_import_static():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("__import__('subprocess')")
def test_scan_ast_blocks_dynamic_dunder_import():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("name = 'os'\n__import__(name)")
def test_scan_ast_blocks_eval_with_dangerous_token():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("eval('__import__(\"os\")')")
def test_scan_ast_blocks_dynamic_eval():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("user_input = 'x'\neval(user_input)")
def test_scan_ast_blocks_dynamic_exec():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("code = 'print(1)'\nexec(code)")
def test_scan_ast_blocks_getattr_dangerous():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("import os\ngetattr(os, 'system')('ls')")
def test_scan_ast_blocks_dunder_builtins_attr():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("x = ().__class__.__builtins__")
def test_scan_ast_blocks_builtins_subscript():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("x = __builtins__['eval']")
def test_scan_ast_collects_all_errors():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    bad = textwrap.dedent("""
        import subprocess
        import socket
        import os
        os.system('x')
    """)
    with pytest.raises(ASTSecurityError) as exc:
        _scan_ast(bad)
    msg = str(exc.value)
    assert "subprocess" in msg
    assert "socket" in msg
    assert "system" in msg
def test_scan_ast_syntax_error():
    from kitsune.core.loader import _scan_ast, ModuleLoadError
    with pytest.raises(ModuleLoadError, match="Syntax"):
        _scan_ast("def broken(:\n    pass")
def test_scan_ast_allows_safe_os_attrs():
    from kitsune.core.loader import _scan_ast
    _scan_ast("import os\np = os.path.join('a', 'b')\nx = os.environ.get('X')")
def test_scan_ast_allows_eval_with_safe_const():
    from kitsune.core.loader import _scan_ast
    _scan_ast("x = eval('1 + 1')")
def test_extract_missing_package_from_name_attr():
    from kitsune.core.loader import _extract_missing_package
    err = ImportError("No module named 'foo'")
    err.name = "foo.bar"
    assert _extract_missing_package(err) == "foo"
def test_extract_missing_package_from_message():
    from kitsune.core.loader import _extract_missing_package
    err = ImportError("No module named 'somepkg'")
    err.name = None
    assert _extract_missing_package(err) == "somepkg"
def test_extract_missing_package_returns_none_when_unknown():
    from kitsune.core.loader import _extract_missing_package
    err = ImportError("totally different message")
    err.name = None
    assert _extract_missing_package(err) is None
def test_module_param_count_two_args():
    from kitsune.core.loader import _module_param_count, KitsuneModule
    class M(KitsuneModule):
        def __init__(self, client, db):
            super().__init__(client, db)
    assert _module_param_count(M) == 2
def test_module_param_count_no_args():
    from kitsune.core.loader import _module_param_count
    class M:
        def __init__(self):
            pass
    assert _module_param_count(M) == 0
def test_module_param_count_caches():
    from kitsune.core.loader import _module_param_count, _INIT_SIGNATURE_CACHE
    class M:
        def __init__(self, x, y, z):
            pass
    _module_param_count(M)
    assert M in _INIT_SIGNATURE_CACHE
def test_config_value_default():
    from kitsune.core.loader import ConfigValue
    cv = ConfigValue("k", default=10, doc="ten")
    assert cv.value == 10
    assert cv.default == 10
    assert cv.doc == "ten"
def test_config_value_set_no_validator():
    from kitsune.core.loader import ConfigValue
    cv = ConfigValue("k", default=1)
    cv.set(42)
    assert cv.value == 42
def test_module_config_basic():
    from kitsune.core.loader import ConfigValue, ModuleConfig
    cfg = ModuleConfig(
        ConfigValue("a", 1, doc="A"),
        ConfigValue("b", "hello"),
    )
    assert cfg["a"] == 1
    assert cfg["b"] == "hello"
    assert "a" in cfg
    assert "x" not in cfg
    cfg["a"] = 99
    assert cfg["a"] == 99
    assert set(cfg.keys()) == {"a", "b"}
    assert dict(cfg.items()) == {"a": 99, "b": "hello"}
    assert cfg.get_default("a") == 1
    assert cfg.get_doc("a") == "A"
def test_command_decorator_marks_method():
    from kitsune.core.loader import command
    @command(name="hello", required=5, aliases=["hi", "hey"])
    async def fn(self, event):
        pass
    assert fn._is_command is True
    assert fn._command_name == "hello"
    assert fn._required == 5
    assert fn._aliases == ["hi", "hey"]
def test_command_decorator_default_name_strips_cmd():
    from kitsune.core.loader import command
    @command()
    async def hello_cmd(self, event):
        pass
    assert hello_cmd._command_name == "hello"
def test_watcher_decorator():
    from kitsune.core.loader import watcher
    def my_filter(e):
        return True
    @watcher(my_filter, custom_tag="x")
    async def w(self, event):
        pass
    assert w._is_watcher is True
    assert w._watcher_filter is my_filter
    assert w.custom_tag == "x"
def test_kitsune_module_default_attrs():
    from kitsune.core.loader import KitsuneModule
    m = KitsuneModule(client=None, db=None)
    assert m.name == ""
    assert m.tg_id == 0
    assert m.config is None
    assert m.client is None
    assert m.db is None
def test_kitsune_module_strings_returns_key_when_missing():
    from kitsune.core.loader import KitsuneModule
    m = KitsuneModule(client=None, db=None)
    assert m.strings("nonexistent") == "nonexistent"
def test_kitsune_module_strings_uses_strings_ru():
    from kitsune.core.loader import KitsuneModule
    class M(KitsuneModule):
        strings_ru = {"hello": "Привет"}
    db = MagicMock()
    db.get.return_value = "ru"
    m = M(client=None, db=db)
    assert m.strings("hello") == "Привет"
def test_kitsune_module_strings_format_kwargs():
    from kitsune.core.loader import KitsuneModule
    class M(KitsuneModule):
        strings_ru = {"greet": "Привет, {name}!"}
    db = MagicMock()
    db.get.return_value = "ru"
    m = M(client=None, db=db)
    assert m.strings("greet", name="Кицунэ") == "Привет, Кицунэ!"
def _make_dispatcher():
    d = MagicMock()
    d._commands = {}
    d._prefix = "."
    d.register_command = MagicMock()
    d.unregister_command = MagicMock()
    d.register_watcher = MagicMock()
    d.unregister_watchers_for = MagicMock()
    return d
def _make_client():
    c = MagicMock()
    c.tg_id = 12345
    c.inline = None
    c._kitsune_dispatcher = None
    return c
def _make_db():
    db = MagicMock()
    db.get = MagicMock(return_value=None)
    return db
@pytest.mark.asyncio
async def test_loader_loads_valid_module(tmp_path, monkeypatch):
    from kitsune.core.loader import Loader
    mod_file = tmp_path / "mymod.py"
    mod_file.write_text(textwrap.dedent("""
        from kitsune.core.loader import KitsuneModule, command
        class MyMod(KitsuneModule):
            name = "MyMod"
            description = "Test module"
            version = "1.0"
            @command()
            async def hello_cmd(self, event):
                pass
    """).strip())
    client = _make_client()
    db = _make_db()
    dispatcher = _make_dispatcher()
    loader = Loader(client, db, dispatcher)
    mod = await loader.load_from_file(mod_file)
    assert mod.name == "MyMod"
    assert "mymod" in loader._modules
    assert dispatcher.register_command.called
@pytest.mark.asyncio
async def test_loader_blocks_dangerous_module(tmp_path):
    from kitsune.core.loader import Loader, ASTSecurityError
    mod_file = tmp_path / "evil.py"
    mod_file.write_text("import subprocess\nsubprocess.run(['ls'])")
    loader = Loader(_make_client(), _make_db(), _make_dispatcher())
    with pytest.raises(ASTSecurityError):
        await loader.load_from_file(mod_file)
@pytest.mark.asyncio
async def test_loader_no_module_class_error(tmp_path):
    from kitsune.core.loader import Loader, ModuleLoadError
    mod_file = tmp_path / "empty.py"
    mod_file.write_text("# no module class here\nx = 42\n")
    loader = Loader(_make_client(), _make_db(), _make_dispatcher())
    with pytest.raises(ModuleLoadError, match="No KitsuneModule subclass"):
        await loader.load_from_file(mod_file)
@pytest.mark.asyncio
async def test_loader_missing_dependency_detected(tmp_path):
    from kitsune.core.loader import Loader, ModuleLoadError
    mod_file = tmp_path / "needs_dep.py"
    mod_file.write_text(textwrap.dedent("""
        from kitsune.core.loader import KitsuneModule
        class DepMod(KitsuneModule):
            name = "DepMod"
            requires = ["NonExistentDep"]
    """).strip())
    loader = Loader(_make_client(), _make_db(), _make_dispatcher())
    with pytest.raises(ModuleLoadError, match="Missing dependencies"):
        await loader.load_from_file(mod_file)
@pytest.mark.asyncio
async def test_loader_unload_module(tmp_path):
    from kitsune.core.loader import Loader
    mod_file = tmp_path / "tomb.py"
    mod_file.write_text(textwrap.dedent("""
        from kitsune.core.loader import KitsuneModule
        class TombMod(KitsuneModule):
            name = "TombMod"
    """).strip())
    loader = Loader(_make_client(), _make_db(), _make_dispatcher())
    mod = await loader.load_from_file(mod_file)
    assert "tombmod" in loader._modules
    ok = await loader.unload_module("TombMod")
    assert ok is True
    assert "tombmod" not in loader._modules
@pytest.mark.asyncio
async def test_loader_unload_unknown_returns_false():
    from kitsune.core.loader import Loader
    loader = Loader(_make_client(), _make_db(), _make_dispatcher())
    assert (await loader.unload_module("ghost")) is False
@pytest.mark.asyncio
async def test_loader_get_module(tmp_path):
    from kitsune.core.loader import Loader
    mod_file = tmp_path / "getmod.py"
    mod_file.write_text(textwrap.dedent("""
        from kitsune.core.loader import KitsuneModule
        class GetMod(KitsuneModule):
            name = "GetMod"
    """).strip())
    loader = Loader(_make_client(), _make_db(), _make_dispatcher())
    await loader.load_from_file(mod_file)
    m = loader.get_module("GetMod")
    assert m is not None
    assert m.name == "GetMod"
    assert loader.get_module("ghost") is None
@pytest.mark.asyncio
async def test_loader_get_modules_returns_copy(tmp_path):
    from kitsune.core.loader import Loader
    mod_file = tmp_path / "cpmod.py"
    mod_file.write_text(textwrap.dedent("""
        from kitsune.core.loader import KitsuneModule
        class CpMod(KitsuneModule):
            name = "CpMod"
    """).strip())
    loader = Loader(_make_client(), _make_db(), _make_dispatcher())
    await loader.load_from_file(mod_file)
    snap = loader.get_modules()
    snap["fake"] = "x"
    assert "fake" not in loader._modules
@pytest.mark.asyncio
async def test_loader_reload_module(tmp_path):
    from kitsune.core.loader import Loader
    mod_file = tmp_path / "rl.py"
    mod_file.write_text(textwrap.dedent("""
        from kitsune.core.loader import KitsuneModule
        class RL(KitsuneModule):
            name = "RL"
            version = "1.0"
    """).strip())
    loader = Loader(_make_client(), _make_db(), _make_dispatcher())
    m1 = await loader.load_from_file(mod_file)
    first_id = id(m1)
    reloaded = await loader.reload_module("RL")
    assert id(reloaded) != first_id
    assert reloaded.name == "RL"
    assert "rl" in loader._modules
@pytest.mark.asyncio
async def test_loader_reload_unknown_raises():
    from kitsune.core.loader import Loader, ModuleLoadError
    loader = Loader(_make_client(), _make_db(), _make_dispatcher())
    with pytest.raises(ModuleLoadError, match="not loaded"):
        await loader.reload_module("ghost")
def test_loader_get_prefix_default():
    from kitsune.core.loader import Loader
    db = _make_db()
    db.get.side_effect = lambda owner, key, default: default
    loader = Loader(_make_client(), db, _make_dispatcher())
    assert loader.get_prefix() == "."
    assert loader.get_prefix("dragon") == ","
