import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock


from conftest import FakeDB


def _make_module(db):
    from kitsune.core.loader import KitsuneModule
    mod = KitsuneModule(MagicMock(), db)
    mod.name = "ws2sample"
    return mod


def test_module_set_sync_style_persists_immediately():
    db = FakeDB()
    mod = _make_module(db)
    mod.set("foo", 123)
    assert db.get(type(mod).__name__, "foo") == 123
    assert db.set_sync_calls == 1


@pytest.mark.asyncio
async def test_module_set_await_style_persists_and_returns():
    db = FakeDB()
    mod = _make_module(db)
    result = await mod.set("bar", "value")
    assert db.get(type(mod).__name__, "bar") == "value"
    assert bool(result) is True


def test_module_set_result_is_truthy_without_await():
    db = FakeDB()
    mod = _make_module(db)
    res = mod.set("k", 1)
    assert bool(res) is True


@pytest.mark.asyncio
async def test_module_set_fallback_without_set_sync():

    class AsyncOnlyDB:
        def __init__(self):
            self.store = {}

        def get(self, owner, key, default=None):
            return self.store.get(owner, {}).get(key, default)

        async def set(self, owner, key, value):
            self.store.setdefault(owner, {})[key] = value
            return True

    db = AsyncOnlyDB()
    mod = _make_module(db)
    res = mod.set("z", 9)
    await res
    assert db.get(type(mod).__name__, "z") == 9


@pytest.mark.asyncio
async def test_pointer_remove_uses_delete():
    from kitsune.pointers import Pointer
    db = FakeDB()
    db.store.setdefault("owner", {})["k"] = 1
    ptr = Pointer(db, "owner", "k")
    await ptr.remove()
    assert ("owner", "k") in db.deleted


@pytest.mark.asyncio
async def test_pointer_remove_falls_back_to_remove_alias():
    from kitsune.pointers import Pointer

    class OnlyRemove:
        def __init__(self):
            self.removed = []

        def get(self, o, k, d=None):
            return d

        async def remove(self, owner, key):
            self.removed.append((owner, key))
            return True

    db = OnlyRemove()
    ptr = Pointer(db, "o", "k")
    await ptr.remove()
    assert ("o", "k") in db.removed


@pytest.mark.asyncio
async def test_database_manager_has_remove_alias():
    from kitsune.database.manager import DatabaseManager
    assert hasattr(DatabaseManager, "remove")
