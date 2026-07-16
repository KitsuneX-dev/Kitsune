import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import pytest
import pytest_asyncio
import textwrap
from pathlib import Path
from unittest.mock import patch


def test_builtin_modules_dir_is_lazy():
    from kitsune.core import loader as ld
    ld._BUILTIN_MODULES_DIR_CACHED = None
    p = ld._get_builtin_modules_dir()
    assert isinstance(p, Path)
    assert p.exists()
    assert p.name == "modules"
    p2 = ld._get_builtin_modules_dir()
    assert p is p2


def test_builtin_modules_dir_proxy_supports_path_api():
    from kitsune.core.loader import _BUILTIN_MODULES_DIR
    assert _BUILTIN_MODULES_DIR.exists()
    assert _BUILTIN_MODULES_DIR.is_dir()
    sub = _BUILTIN_MODULES_DIR / "config.py"
    assert isinstance(sub, Path)
    listed = list(_BUILTIN_MODULES_DIR.glob("*.py"))
    assert len(listed) > 0
    assert os.fspath(_BUILTIN_MODULES_DIR) == str(_BUILTIN_MODULES_DIR)


def test_builtin_modules_dir_meipass_fallback(monkeypatch, tmp_path):
    from kitsune.core import loader as ld
    fake_meipass = tmp_path / "frozen"
    (fake_meipass / "kitsune" / "modules").mkdir(parents=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    ld._BUILTIN_MODULES_DIR_CACHED = None
    p = ld._get_builtin_modules_dir()
    assert p == fake_meipass / "kitsune" / "modules"
    ld._BUILTIN_MODULES_DIR_CACHED = None
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)


def test_build_pip_base_cmd_default(monkeypatch):
    from kitsune.core.loader import _build_pip_base_cmd
    monkeypatch.delenv("KITSUNE_PIP_CMD", raising=False)
    cmd = _build_pip_base_cmd()
    assert cmd == [sys.executable, "-m", "pip"]


def test_build_pip_base_cmd_override(monkeypatch):
    from kitsune.core.loader import _build_pip_base_cmd
    monkeypatch.setenv("KITSUNE_PIP_CMD", "/opt/venv/bin/pip --no-color")
    cmd = _build_pip_base_cmd()
    assert cmd == ["/opt/venv/bin/pip", "--no-color"]


def test_build_pip_base_cmd_override_with_quotes(monkeypatch):
    from kitsune.core.loader import _build_pip_base_cmd
    monkeypatch.setenv("KITSUNE_PIP_CMD", "'/path with spaces/pip' install")
    cmd = _build_pip_base_cmd()
    assert cmd == ["/path with spaces/pip", "install"]


def test_build_pip_base_cmd_invalid_override_falls_back(monkeypatch):
    from kitsune.core.loader import _build_pip_base_cmd
    monkeypatch.setenv("KITSUNE_PIP_CMD", "broken 'quoted")
    cmd = _build_pip_base_cmd()
    assert cmd == [sys.executable, "-m", "pip"]


def test_build_pip_base_cmd_empty_override(monkeypatch):
    from kitsune.core.loader import _build_pip_base_cmd
    monkeypatch.setenv("KITSUNE_PIP_CMD", "   ")
    cmd = _build_pip_base_cmd()
    assert cmd == [sys.executable, "-m", "pip"]


def test_scan_ast_blocks_globals_subscript_os():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError) as exc:
        _scan_ast("globals()['os'].system('ls')")
    assert "globals" in str(exc.value) or "subscript" in str(exc.value).lower()


def test_scan_ast_blocks_locals_subscript_os():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("locals()['os']")


def test_scan_ast_blocks_vars_subscript_builtins():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("vars()['__builtins__']")


def test_scan_ast_blocks_dynamic_globals_subscript():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("k = 'os'\nx = globals()[k]")


def test_scan_ast_allows_safe_globals_subscript():
    from kitsune.core.loader import _scan_ast
    _scan_ast("x = globals()['my_var']")


def test_scan_ast_blocks_globals_subscript_subprocess():
    from kitsune.core.loader import _scan_ast, ASTSecurityError
    with pytest.raises(ASTSecurityError):
        _scan_ast("globals()['subprocess']")


def test_ast_cache_lru_eviction():
    from kitsune.core import loader as ld
    ld._ast_cache_clear()
    for i in range(ld._AST_CACHE_MAX_SIZE + 50):
        src = f"x = {i}\n"
        ld._scan_ast_with_cache(src)
    assert len(ld._ast_cache) == ld._AST_CACHE_MAX_SIZE


def test_ast_cache_move_to_end_on_hit():
    from kitsune.core import loader as ld
    ld._ast_cache_clear()
    sources = [f"y = {i}\n" for i in range(5)]
    for s in sources:
        ld._scan_ast_with_cache(s)
    keys_before = list(ld._ast_cache.keys())
    ld._scan_ast_with_cache(sources[0])
    keys_after = list(ld._ast_cache.keys())
    assert keys_after[-1] == keys_before[0]


def test_ast_cache_clear():
    from kitsune.core import loader as ld
    ld._scan_ast_with_cache("z = 1\n")
    assert len(ld._ast_cache) >= 1
    ld._ast_cache_clear()
    assert len(ld._ast_cache) == 0


@pytest.mark.asyncio
async def test_run_cmd_timeout_kills_process():
    from kitsune.core.loader import _run_cmd
    ok, stderr = await _run_cmd(["sleep", "10"], timeout=0.3)
    assert ok is False
    assert "timed out" in stderr.lower()


@pytest.mark.asyncio
async def test_run_cmd_no_timeout_completes():
    from kitsune.core.loader import _run_cmd
    ok, stderr = await _run_cmd(["true"])
    assert ok is True


@pytest.mark.asyncio
async def test_run_cmd_failure_returns_stderr():
    from kitsune.core.loader import _run_cmd
    ok, stderr = await _run_cmd(["false"])
    assert ok is False


@pytest.mark.asyncio
async def test_pip_install_records_stderr_on_failure(monkeypatch):
    from kitsune.core import loader as ld
    ld._LAST_PIP_STDERR.clear()

    async def fake_run(args, timeout=None):
        return False, "ERROR: Could not find a version of fake_xyz_pkg_404"

    monkeypatch.setattr(ld, "_run_cmd", fake_run)
    ok = await ld._pip_install("fake_xyz_pkg_404")
    assert ok is False
    tail = ld.get_last_pip_stderr("fake_xyz_pkg_404")
    assert "Could not find" in tail


@pytest.mark.asyncio
async def test_pip_install_clears_stderr_on_success(monkeypatch):
    from kitsune.core import loader as ld
    ld._LAST_PIP_STDERR["already_seen_pkg"] = "old error"

    async def fake_run(args, timeout=None):
        return True, ""

    monkeypatch.setattr(ld, "_run_cmd", fake_run)
    ok = await ld._pip_install("already_seen_pkg")
    assert ok is True
    assert ld.get_last_pip_stderr("already_seen_pkg") == ""


@pytest.mark.asyncio
async def test_pip_install_stderr_truncated_to_tail(monkeypatch):
    from kitsune.core import loader as ld
    ld._LAST_PIP_STDERR.clear()
    huge = "x" * 5000 + " FINAL_MARKER"

    async def fake_run(args, timeout=None):
        return False, huge

    monkeypatch.setattr(ld, "_run_cmd", fake_run)
    await ld._pip_install("long_err_pkg")
    tail = ld.get_last_pip_stderr("long_err_pkg")
    assert len(tail) <= ld._PIP_STDERR_TAIL
    assert "FINAL_MARKER" in tail


@pytest.mark.asyncio
async def test_pip_install_uses_kitsune_pip_cmd(monkeypatch):
    from kitsune.core import loader as ld
    monkeypatch.setenv("KITSUNE_PIP_CMD", "/custom/pip")
    captured = {}

    async def fake_run(args, timeout=None):
        captured["args"] = list(args)
        return True, ""

    monkeypatch.setattr(ld, "_run_cmd", fake_run)
    await ld._pip_install("requests")
    assert captured["args"][0] == "/custom/pip"
    assert "install" in captured["args"]
    assert "requests" in captured["args"]


@pytest.mark.asyncio
async def test_pip_install_passes_timeout(monkeypatch):
    from kitsune.core import loader as ld
    captured = {}

    async def fake_run(args, timeout=None):
        captured["timeout"] = timeout
        return True, ""

    monkeypatch.setattr(ld, "_run_cmd", fake_run)
    await ld._pip_install("any_pkg")
    assert captured["timeout"] == ld._PIP_INSTALL_TIMEOUT


def test_db_owner_loader_constant_shared():
    from kitsune._internal import DB_OWNER_LOADER
    from kitsune.modules.loader_mod import _DB_OWNER
    assert DB_OWNER_LOADER == _DB_OWNER == "kitsune.loader"


@pytest.mark.asyncio
async def test_loader_includes_pip_stderr_in_error(tmp_path, monkeypatch):
    from kitsune.core import loader as ld
    from kitsune.core.loader import Loader, ModuleLoadError
    from unittest.mock import MagicMock

    mod_file = tmp_path / "needs_unknown.py"
    mod_file.write_text(textwrap.dedent("""
        import some_unknown_pkg_xyzzy_999
        from kitsune.core.loader import KitsuneModule
        class M(KitsuneModule):
            name = "M"
    """).strip())

    async def fake_install(package):
        ld._LAST_PIP_STDERR[package] = "ERROR: could not resolve some_unknown_pkg_xyzzy_999"
        return False

    monkeypatch.setattr(ld, "_pip_install", fake_install)

    client = MagicMock()
    client.tg_id = 1
    client.inline = None
    client._kitsune_dispatcher = None
    db = MagicMock()
    db.get.return_value = None
    dispatcher = MagicMock()
    dispatcher._commands = {}
    dispatcher._prefix = "."

    loader = Loader(client, db, dispatcher)
    with pytest.raises(ModuleLoadError) as exc:
        await loader.load_from_file(mod_file)
    msg = str(exc.value)
    assert "could not resolve" in msg or "pip stderr" in msg
