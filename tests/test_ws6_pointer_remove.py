
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from conftest import FakeDB


def _pointers():
    from kitsune import pointers
    return pointers


async def test_base_pointer_remove_does_not_raise(fake_db):
    p = _pointers()
    fake_db.set_sync("owner", "key", "value")
    ptr = p.Pointer(fake_db, "owner", "key")

    await ptr.remove()

    assert ("owner", "key") in fake_db.deleted
    assert ptr.get() is None


async def test_bool_pointer_remove_does_not_raise(fake_db):
    p = _pointers()
    ptr = p.BoolPointer(fake_db, "owner", "flag", default=False)
    await ptr.set(True)
    assert ptr.get() is True

    await ptr.remove()

    assert ("owner", "flag") in fake_db.deleted
    assert ptr.get() is False


async def test_int_pointer_remove_does_not_raise(fake_db):
    p = _pointers()
    ptr = p.IntPointer(fake_db, "owner", "counter", default=0)
    await ptr.increment(5)
    assert ptr.get() == 5

    await ptr.remove()

    assert ("owner", "counter") in fake_db.deleted
    assert ptr.get() == 0


async def test_list_pointer_remove_item_does_not_raise(fake_db):
    p = _pointers()
    ptr = p.ListPointer(fake_db, "owner", "items")
    await ptr.append("a")
    await ptr.append("b")

    assert await ptr.remove("a") is True
    assert ptr.get() == ["b"]
    assert await ptr.remove("missing") is False
    assert ptr.get() == ["b"]


async def test_list_pointer_remove_signature_differs_from_base():
    import inspect

    p = _pointers()
    base_params = list(inspect.signature(p.Pointer.remove).parameters)
    list_params = list(inspect.signature(p.ListPointer.remove).parameters)
    assert base_params == ["self"]
    assert list_params == ["self", "item"]


async def test_pointer_remove_falls_back_to_remove_method():
    p = _pointers()

    class OnlyRemoveDB:
        def __init__(self):
            self.removed: list[tuple[str, str]] = []

        def get(self, owner, key, default=None):
            return default

        async def remove(self, owner, key):
            self.removed.append((owner, key))
            return True

    db = OnlyRemoveDB()
    ptr = p.Pointer(db, "o", "k")
    await ptr.remove()
    assert ("o", "k") in db.removed


async def test_pointer_remove_raises_attribute_error_only_without_backend():
    p = _pointers()

    class NoDeleteDB:
        def get(self, owner, key, default=None):
            return default

    ptr = p.Pointer(NoDeleteDB(), "o", "k")
    with pytest.raises(AttributeError, match="delete/remove"):
        await ptr.remove()


def test_pointer_list_remove_is_synchronous_and_persists(fake_db):
    p = _pointers()
    fake_db.set_sync("mod", "lst", ["x", "y"])
    plist = p.PointerList(fake_db, "mod", "lst")

    plist.remove("x")

    assert list(plist) == ["y"]
    assert fake_db.get("mod", "lst") == ["y"]


def test_serializing_middleware_list_remove_does_not_raise(fake_db):
    import collections

    p = _pointers()
    Item = collections.namedtuple("Item", ["a", "b"])

    plist = p.PointerList(fake_db, "mod", "nt")
    wrapper = p.NamedTupleMiddlewareList(plist, Item)
    wrapper.append(Item(1, 2))
    wrapper.append(Item(3, 4))

    wrapper.remove(Item(1, 2))

    assert [tuple(i) for i in wrapper] == [(3, 4)]
