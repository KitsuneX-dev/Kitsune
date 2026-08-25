from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import kitsune._internal as internal


REPO_ROOT = Path(__file__).resolve().parent.parent
KITSUNE_DIR = REPO_ROOT / "kitsune"


@pytest.fixture(autouse=True)
def _reset_restart_flag():
    internal._RESTART_DONE = False
    yield
    internal._RESTART_DONE = False


def _make_env(order: list[str]):

    class _DB:
        async def force_save(self):
            order.append("force_save")
            return True

        async def shutdown(self):
            order.append("db_shutdown")

    class _Hydro:
        async def stop(self):
            order.append("hydrogram_disconnect")

    class _Web:
        async def stop(self):
            order.append("web_stop")

    class _Accounts:
        async def shutdown_all(self):
            order.append("accounts_shutdown")

    client = MagicMock()
    client.hydrogram = _Hydro()
    client.session = None

    async def _disconnect():
        order.append("telethon_disconnect")

    client.disconnect = _disconnect
    db = _DB()
    client._kitsune_db = db
    client._kitsune_web = _Web()
    client._kitsune_accounts = _Accounts()
    return client, db


async def test_shutdown_sequence_order(monkeypatch):
    order: list[str] = []
    client, db = _make_env(order)

    import kitsune.core.lifecycle as lifecycle

    async def _fake_cancel():
        order.append("cancel_tasks")

    monkeypatch.setattr(lifecycle, "_cancel_background_tasks", _fake_cancel)
    monkeypatch.setattr(lifecycle, "stop_watchdog", lambda: order.append("stop_watchdog"))
    monkeypatch.setattr(
        "kitsune.session_enc.encrypt_session_file", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "kitsune.core.connection._release_hydro_lock", lambda *a, **k: None
    )

    await internal.graceful_restart(client, db)

    assert order.index("force_save") == 0
    assert order.index("web_stop") < order.index("telethon_disconnect")
    assert order.index("accounts_shutdown") < order.index("hydrogram_disconnect")
    assert order.index("hydrogram_disconnect") < order.index("telethon_disconnect")
    assert order.index("cancel_tasks") < order.index("db_shutdown")
    assert order.index("db_shutdown") < order.index("telethon_disconnect")
    assert "stop_watchdog" in order


async def test_both_clients_disconnected(monkeypatch):
    order: list[str] = []
    client, db = _make_env(order)

    import kitsune.core.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "_cancel_background_tasks", AsyncMock())
    monkeypatch.setattr(lifecycle, "stop_watchdog", lambda: None)
    monkeypatch.setattr("kitsune.session_enc.encrypt_session_file", lambda *a, **k: None)
    monkeypatch.setattr("kitsune.core.connection._release_hydro_lock", lambda *a, **k: None)

    await internal.graceful_restart(client, db)

    assert "telethon_disconnect" in order
    assert "hydrogram_disconnect" in order


async def test_extra_tasks_cancelled(monkeypatch):
    order: list[str] = []
    client, db = _make_env(order)

    import kitsune.core.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "_cancel_background_tasks", AsyncMock())
    monkeypatch.setattr(lifecycle, "stop_watchdog", lambda: None)
    monkeypatch.setattr("kitsune.session_enc.encrypt_session_file", lambda *a, **k: None)
    monkeypatch.setattr("kitsune.core.connection._release_hydro_lock", lambda *a, **k: None)

    async def _forever():
        await asyncio.sleep(3600)

    task = asyncio.ensure_future(_forever())
    await asyncio.sleep(0)

    await internal.graceful_restart(client, db, extra_tasks=[task])

    assert task.cancelled() or task.done()


async def test_callable_without_arguments(monkeypatch):
    called = {"cancel": False}

    import kitsune.core.lifecycle as lifecycle

    async def _fake_cancel():
        called["cancel"] = True

    monkeypatch.setattr(lifecycle, "_cancel_background_tasks", _fake_cancel)

    await internal.graceful_restart()

    assert called["cancel"] is True


async def test_idempotent(monkeypatch):
    order: list[str] = []
    client, db = _make_env(order)

    import kitsune.core.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "_cancel_background_tasks", AsyncMock())
    monkeypatch.setattr(lifecycle, "stop_watchdog", lambda: None)
    monkeypatch.setattr("kitsune.session_enc.encrypt_session_file", lambda *a, **k: None)
    monkeypatch.setattr("kitsune.core.connection._release_hydro_lock", lambda *a, **k: None)

    await internal.graceful_restart(client, db)
    first = list(order)
    await internal.graceful_restart(client, db)

    assert order == first


async def test_failing_component_does_not_block_restart(monkeypatch):
    order: list[str] = []
    client, db = _make_env(order)

    async def _bad_stop():
        raise RuntimeError("порт уже закрыт")

    client._kitsune_web.stop = _bad_stop

    import kitsune.core.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "_cancel_background_tasks", AsyncMock())
    monkeypatch.setattr(lifecycle, "stop_watchdog", lambda: None)
    monkeypatch.setattr("kitsune.session_enc.encrypt_session_file", lambda *a, **k: None)
    monkeypatch.setattr("kitsune.core.connection._release_hydro_lock", lambda *a, **k: None)

    await internal.graceful_restart(client, db)

    assert "telethon_disconnect" in order
    assert "db_shutdown" in order


_RESTART_MODULES = (
    Path("modules/updater.py"),
    Path("modules/notifier/update_checker.py"),
)


def _exec_restart_sites() -> list[tuple[Path, int, list[str]]]:
    sites: list[tuple[Path, int, list[str]]] = []
    for rel in _RESTART_MODULES:
        path = KITSUNE_DIR / rel
        lines = path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines):
            if re.search(r"^\s*exec_restart\(", line):
                sites.append((path, idx, lines))
    return sites


def _execl_occurrences() -> list[str]:
    hits: list[str] = []
    for path in sorted(KITSUNE_DIR.rglob("*.py")):
        for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if re.search(r"os\.execl\w*\(", line):
                hits.append(f"{path}:{idx + 1}")
    return hits


def _enclosing_function(path: Path, lineno: int) -> tuple[int, int]:
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    best: tuple[int, int] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, "end_lineno", None) or node.lineno
        if node.lineno <= lineno <= end:
            if best is None or node.lineno > best[0]:
                best = (node.lineno, end)
    assert best is not None, f"{path}:{lineno} — exec_restart вне функции"
    return best


def test_all_execl_sites_are_guarded():
    assert _execl_occurrences() == [], (
        f"os.execl* остался в kitsune/: {_execl_occurrences()}"
    )

    sites = _exec_restart_sites()
    assert len(sites) == 6, f"ожидалось 6 точек exec_restart, найдено {len(sites)}"

    unguarded: list[str] = []
    for path, idx, lines in sites:
        start, _end = _enclosing_function(path, idx + 1)
        body_before = "\n".join(lines[start - 1: idx])
        if (
            "graceful_restart" not in body_before
            and "_graceful_restart_blocking" not in body_before
        ):
            unguarded.append(f"{path}:{idx + 1}")

    assert unguarded == [], f"exec_restart без graceful_restart: {unguarded}"


def test_internal_restart_calls_shutdown_wrapper():
    source = (KITSUNE_DIR / "_internal.py").read_text(encoding="utf-8")
    body = source.split("def restart(")[1]
    assert body.index("_graceful_restart_blocking") < body.index("exec_restart(")


def test_signature_defaults_only():
    import inspect

    sig = inspect.signature(internal.graceful_restart)
    for param in sig.parameters.values():
        assert param.default is not inspect.Parameter.empty, param.name
