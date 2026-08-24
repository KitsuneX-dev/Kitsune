
from __future__ import annotations

import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

aiohttp = pytest.importorskip("aiohttp")
pytest.importorskip("telethon")


def _setup_module():
    from kitsune.web import setup as setup_mod
    return setup_mod


def test_start_binds_loopback_by_default():
    setup_mod = _setup_module()
    sig = inspect.signature(setup_mod.SetupServer.start)
    assert sig.parameters["host"].default == "127.0.0.1", (
        "мастер настройки не должен биндиться наружу по умолчанию"
    )
    assert sig.parameters["port"].default == 8080


@pytest.fixture()
async def wizard(monkeypatch, tmp_path):
    setup_mod = _setup_module()

    saved: dict = {}

    def _save(cfg):
        saved.update(cfg or {})

    def _get():
        return dict(saved)

    server = setup_mod.SetupServer(_save, _get, data_dir_override=tmp_path)

    monkeypatch.setattr(setup_mod.webbrowser, "open", lambda *a, **k: True)

    await server.start(port=0)
    try:
        yield server
    finally:
        await server._runner.cleanup()


def _server_url(server) -> str:
    host, port = server._runner.addresses[0][:2]
    return f"http://{host}:{port}"


async def test_actual_socket_is_loopback(wizard):
    host = wizard._runner.addresses[0][0]
    assert host in ("127.0.0.1", "::1"), f"мастер слушает {host} — доступен из сети"


async def test_setup_token_is_generated_and_strong(wizard):
    token = wizard._setup_token
    assert isinstance(token, str) and token
    assert len(token) >= 32, f"слишком короткий setup-токен: {len(token)}"


async def test_setup_tokens_differ_between_instances(monkeypatch, tmp_path):
    setup_mod = _setup_module()
    monkeypatch.setattr(setup_mod.webbrowser, "open", lambda *a, **k: True)

    tokens = []
    for _ in range(2):
        srv = setup_mod.SetupServer(lambda c: None, lambda: {}, data_dir_override=tmp_path)
        await srv.start(port=0)
        tokens.append(srv._setup_token)
        await srv._runner.cleanup()
    assert tokens[0] != tokens[1]


async def test_index_without_token_returns_401(wizard):
    url = _server_url(wizard)
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{url}/") as resp:
            assert resp.status == 401


async def test_api_without_token_returns_401(wizard):
    url = _server_url(wizard)
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{url}/api/sendcode", json={"stage": "phone"}) as resp:
            assert resp.status == 401


async def test_index_with_token_returns_200(wizard):
    url = _server_url(wizard)
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{url}/?token={wizard._setup_token}") as resp:
            assert resp.status == 200
            assert resp.content_type == "text/html"


async def test_index_with_wrong_token_returns_401(wizard):
    url = _server_url(wizard)
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{url}/?token=definitely-not-the-token") as resp:
            assert resp.status == 401
