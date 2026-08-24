
from __future__ import annotations

import ast
import inspect
import os
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from conftest import FakeDB

aiohttp = pytest.importorskip("aiohttp")
pytest.importorskip("aiohttp.web")


def test_tokens_equal_uses_compare_digest_not_plain_eq():
    from kitsune.web import auth

    src = textwrap.dedent(inspect.getsource(auth.tokens_equal))
    tree = ast.parse(src)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "compare_digest"
    ]
    assert calls, "tokens_equal должна сравнивать токены через hmac.compare_digest"
    compares = [node for node in ast.walk(tree) if isinstance(node, ast.Compare)]
    for cmp_node in compares:
        assert not any(isinstance(op, ast.Eq) for op in cmp_node.ops), (
            "в tokens_equal не должно быть небезопасного сравнения через =="
        )


def test_tokens_equal_behaviour():
    from kitsune.web.auth import tokens_equal

    token = "s3cret-token-value"
    assert tokens_equal(token, token) is True
    assert tokens_equal(token, token + "x") is False
    assert tokens_equal(token, token[:-1]) is False
    assert tokens_equal(token, "") is False
    assert tokens_equal("", token) is False
    assert tokens_equal(None, token) is False
    assert tokens_equal(token, None) is False
    assert tokens_equal(None, None) is False


def test_tokens_equal_does_not_compare_by_length():
    from kitsune.web.auth import tokens_equal

    assert tokens_equal("a" * 32, "a" * 32) is True
    assert tokens_equal("a" * 32, "b" * 32) is False
    assert tokens_equal("a" * 32, "a" * 31 + "b") is False


@pytest.fixture()
async def web_server(monkeypatch, tmp_path, fake_client):
    from kitsune.web.core import WebCore

    db = FakeDB()
    core = WebCore(fake_client, db)

    async def _no_announce(host, port):
        return None

    monkeypatch.setattr(core, "_announce_token", _no_announce)

    await core.start(host="127.0.0.1", port=0)
    sockets = core._site._server.sockets
    port = sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", core._token
    finally:
        await core.stop()


async def test_route_without_token_returns_401(web_server):
    url, _token = web_server
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{url}/api/status") as resp:
            assert resp.status == 401
            assert "unauthorized" in (await resp.text()).lower()


async def test_route_with_wrong_token_returns_401(web_server):
    url, token = web_server
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{url}/api/status",
            headers={"Authorization": f"Bearer {token}wrong"},
        ) as resp:
            assert resp.status == 401


async def test_route_with_valid_token_returns_200(web_server):
    url, token = web_server
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{url}/api/status",
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            assert resp.status == 200
            payload = await resp.json()
            assert payload["ok"] is True


async def test_route_with_valid_token_in_query_sets_cookie(web_server):
    url, token = web_server
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{url}/api/status?token={token}") as resp:
            assert resp.status == 200
            from kitsune.web.auth import COOKIE_NAME
            assert COOKIE_NAME in resp.cookies
            cookie = resp.cookies[COOKIE_NAME]
            assert cookie.value == token
            assert cookie["httponly"]


async def test_health_route_is_public(web_server):
    url, _token = web_server
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{url}/health") as resp:
            assert resp.status != 401
