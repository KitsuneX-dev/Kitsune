import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock


def _make_module():
    from kitsune.core.loader import KitsuneModule
    client = MagicMock()
    db = MagicMock()
    mod = KitsuneModule(client, db)
    mod.name = "sample"
    return mod, client, db


def test_public_types_facade_exports():
    import kitsune.types as t
    for name in ("KitsuneModule", "Module", "command", "watcher", "loop",
                 "OWNER", "SUDO", "PointerList", "PointerDict", "ModuleInfo"):
        assert hasattr(t, name), f"kitsune.types missing {name}"
    assert t.Module is t.KitsuneModule


def test_lookup_finds_module_by_name():
    mod, client, db = _make_module()
    other = MagicMock()
    loader = MagicMock()
    loader.get_module = lambda n: other if n == "target" else None
    client._kitsune_loader = loader
    assert mod.lookup("target") is other


def test_lookup_returns_none_without_loader():
    mod, client, db = _make_module()
    client._kitsune_loader = None
    assert mod.lookup("whatever") is None


def test_get_prefix_from_dispatcher():
    mod, client, db = _make_module()
    client._kitsune_loader = None
    client._kitsune_dispatcher = SimpleNamespace(_prefix="!")
    assert mod.get_prefix() == "!"


@pytest.mark.asyncio
async def test_invoke_unknown_command_raises():
    mod, client, db = _make_module()
    client._kitsune_dispatcher = SimpleNamespace(_commands={})
    with pytest.raises(ValueError):
        await mod.invoke("nope", peer=123)


@pytest.mark.asyncio
async def test_animate_edits_frames():
    mod, client, db = _make_module()
    client._kitsune_loader = None
    client._kitsune_dispatcher = SimpleNamespace(_prefix=".")
    client._kitsune_inline = None
    msg = MagicMock()
    msg.edit = AsyncMock(return_value=msg)
    msg.out = True
    msg.via_bot_id = None
    msg.fwd_from = None
    frames = ["a", "b", "c"]
    result = await mod.animate(msg, frames, 0.001)
    assert result is not None
    assert msg.edit.await_count == len(frames)
