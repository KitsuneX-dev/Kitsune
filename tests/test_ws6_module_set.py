
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from conftest import FakeDB


def _make_module(db, name: str = "ws6sample"):
    from kitsune.core.loader import KitsuneModule

    module = KitsuneModule(MagicMock(), db)
    module.name = name
    return module


def test_set_without_await_writes_to_db(fake_db):
    module = _make_module(fake_db)
    owner = type(module).__name__

    module.set("plain_key", "plain_value")

    assert fake_db.get(owner, "plain_key") == "plain_value"
    assert fake_db.set_sync_calls == 1


async def test_set_with_await_writes_to_db(fake_db):
    module = _make_module(fake_db)
    owner = type(module).__name__

    result = await module.set("awaited_key", {"nested": [1, 2, 3]})

    assert fake_db.get(owner, "awaited_key") == {"nested": [1, 2, 3]}
    assert bool(result) is True


def test_set_result_is_truthy_without_await(fake_db):
    module = _make_module(fake_db)
    assert bool(module.set("k", 1)) is True


async def test_module_get_reads_back_what_set_wrote(fake_db):
    module = _make_module(fake_db)

    module.set("roundtrip", 42)
    assert module.get("roundtrip") == 42

    await module.set("roundtrip", 43)
    assert module.get("roundtrip") == 43


async def test_set_writes_under_class_name_owner(fake_db):
    from kitsune.core.loader import KitsuneModule

    class WS6NamedModule(KitsuneModule):
        name = "ws6named"

    module = WS6NamedModule(MagicMock(), fake_db)
    await module.set("scoped", "v")

    assert fake_db.store["WS6NamedModule"]["scoped"] == "v"


def test_set_uses_force_set_when_no_set_sync():

    class ForceSetOnlyDB:
        def __init__(self):
            self.store: dict = {}
            self.force_set_calls = 0

        def get(self, owner, key, default=None):
            return self.store.get(owner, {}).get(key, default)

        def force_set(self, owner, key, value):
            self.force_set_calls += 1
            self.store.setdefault(owner, {})[key] = value
            return True

        async def set(self, owner, key, value):
            raise AssertionError("должен был сработать синхронный force_set")

    db = ForceSetOnlyDB()
    module = _make_module(db)

    module.set("fs", "value")

    assert db.force_set_calls == 1
    assert db.get(type(module).__name__, "fs") == "value"


async def test_set_on_async_only_backend_persists_after_await():

    class AsyncOnlyDB:
        def __init__(self):
            self.store: dict = {}

        def get(self, owner, key, default=None):
            return self.store.get(owner, {}).get(key, default)

        async def set(self, owner, key, value):
            self.store.setdefault(owner, {})[key] = value
            return True

    db = AsyncOnlyDB()
    module = _make_module(db)
    owner = type(module).__name__

    result = module.set("async_key", "async_value")
    await result
    assert db.get(owner, "async_key") == "async_value"


async def test_set_on_async_only_backend_persists_without_explicit_await():

    class AsyncOnlyDB:
        def __init__(self):
            self.store: dict = {}

        def get(self, owner, key, default=None):
            return self.store.get(owner, {}).get(key, default)

        async def set(self, owner, key, value):
            self.store.setdefault(owner, {})[key] = value
            return True

    db = AsyncOnlyDB()
    module = _make_module(db)
    owner = type(module).__name__

    module.set("bare_key", "bare_value")
    await asyncio.sleep(0)
    assert db.get(owner, "bare_key") == "bare_value"
