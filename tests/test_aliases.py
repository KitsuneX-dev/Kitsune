import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock

import pytest

from kitsune.core.dispatcher import CommandDispatcher
from kitsune.core.loader import KitsuneModule


def _make_dispatcher():
    client = MagicMock()
    client.add_event_handler = MagicMock()
    db = MagicMock()
    sec = MagicMock()
    d = CommandDispatcher(client, db, sec, prefix=".")
    client._kitsune_dispatcher = d
    return d, client, db


def test_add_and_resolve_alias():
    d, _, _ = _make_dispatcher()
    d.register_command("dlm", lambda: None, 0)
    assert d.add_alias("длм", "dlm") is True
    assert d.resolve_alias("длм") == ("dlm", "")
    assert d.resolve_alias("нет") is None


def test_alias_rejects_unknown_and_selfclash():
    d, _, _ = _make_dispatcher()
    d.register_command("dlm", lambda: None, 0)
    assert d.add_alias("x", "nonexistent") is False
    assert d.add_alias("dlm", "dlm") is False


def test_alias_with_baked_args():
    d, _, _ = _make_dispatcher()
    d.register_command("weather", lambda: None, 0)
    assert d.add_alias("погода", "weather", "Москва") is True
    assert d.resolve_alias("погода") == ("weather", "Москва")


def test_get_and_load_roundtrip():
    d, _, _ = _make_dispatcher()
    d.register_command("dlm", lambda: None, 0)
    d.register_command("weather", lambda: None, 0)
    d.add_alias("длм", "dlm")
    d.add_alias("погода", "weather", "Москва")
    saved = d.get_aliases()
    assert saved == {"длм": "dlm", "погода": "weather Москва"}

    d2, _, _ = _make_dispatcher()
    d2.register_command("dlm", lambda: None, 0)
    d2.register_command("weather", lambda: None, 0)
    d2.load_aliases(saved)
    assert d2.get_aliases() == saved


def test_remove_alias():
    d, _, _ = _make_dispatcher()
    d.register_command("dlm", lambda: None, 0)
    d.add_alias("длм", "dlm")
    assert d.remove_alias("длм") is True
    assert d.remove_alias("длм") is False
    assert d.resolve_alias("длм") is None


def test_unregister_command_drops_aliases():
    d, _, _ = _make_dispatcher()
    d.register_command("weather", lambda: None, 0)
    d.add_alias("погода", "weather", "Москва")
    d.unregister_command("weather")
    assert "погода" not in d.get_aliases()


def test_rewrite_text_survives_readonly_property():
    msg = MagicMock()
    type(msg).text = property(
        lambda s: (_ for _ in ()).throw(AttributeError("no setter"))
    )
    CommandDispatcher._rewrite_command_text(msg, ".weather Москва питер")
    assert msg._kitsune_alias_text == ".weather Москва питер"


def test_disable_enable_command():
    d, _, _ = _make_dispatcher()
    d.register_command("dlm", lambda: None, 0)
    assert d.is_command_disabled("dlm") is False
    assert d.disable_command("dlm") is True
    assert d.is_command_disabled("DLM") is True
    assert d.get_disabled_commands() == ["dlm"]
    assert d.enable_command("dlm") is True
    assert d.is_command_disabled("dlm") is False
    assert d.enable_command("dlm") is False


def test_load_disabled_commands_roundtrip():
    d, _, _ = _make_dispatcher()
    d.register_command("dlm", lambda: None, 0)
    d.register_command("weather", lambda: None, 0)
    d.load_disabled_commands(["dlm", "WEATHER", "", None])
    assert d.get_disabled_commands() == ["dlm", "weather"]


def test_disabled_alias_target_still_blocked_by_flag():
    d, _, _ = _make_dispatcher()
    d.register_command("weather", lambda: None, 0)
    d.add_alias("погода", "weather")
    d.disable_command("weather")
    real, _ = d.resolve_alias("погода")
    assert real == "weather"
    assert d.is_command_disabled(real) is True


def test_get_args_prefers_alias_text():
    d, client, db = _make_dispatcher()
    d.register_command("weather", lambda: None, 0)
    d.add_alias("погода", "weather", "Москва")
    real, baked = d.resolve_alias("погода")
    merged = " ".join(p for p in (baked, "питер") if p)
    new_text = "." + real + (f" {merged}" if merged else "")
    msg = MagicMock()
    CommandDispatcher._rewrite_command_text(msg, new_text)
    mod = KitsuneModule(client, db)
    ev = MagicMock()
    ev.message = msg
    assert mod.get_args(ev) == "Москва питер"
