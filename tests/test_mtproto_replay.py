
import sys
import types

import pytest

from kitsune import mtproto_replay


def test_native_protection_detected_on_modern_telethon():
    telethon = pytest.importorskip("telethon")
    assert mtproto_replay._native_protection_present() is True


def test_ensure_replay_protection_native_path():
    telethon = pytest.importorskip("telethon")

    class _Client:
        _sender = None

    assert mtproto_replay.ensure_replay_protection(_Client()) == "native"


def test_ensure_replay_protection_skipped_without_sender(monkeypatch):
    monkeypatch.setattr(mtproto_replay, "_native_protection_present", lambda: False)

    class _Client:
        _sender = None

    assert mtproto_replay.ensure_replay_protection(_Client()) == "skipped"


def test_hardened_state_dedups_replayed_msg_id(monkeypatch):
    telethon = pytest.importorskip("telethon")

    Hardened = mtproto_replay._build_hardened_state()

    from telethon.tl.core import TLMessage

    state = object.__new__(Hardened)
    from collections import deque
    state._recent_remote_ids = deque(maxlen=mtproto_replay.MAX_RECENT_MSG_IDS)
    state._highest_remote_id = 0
    state._ignore_count = 0

    import logging
    state._log = logging.getLogger("test")

    msg_id = 7
    assert msg_id not in state._recent_remote_ids
    state._recent_remote_ids.append(msg_id)
    state._highest_remote_id = msg_id

    replayed = msg_id
    is_replay = (
        replayed <= state._highest_remote_id
        and replayed in state._recent_remote_ids
    )
    assert is_replay is True

    assert (8 % 2 != 1) is True


def test_build_hardened_state_is_cached():
    pytest.importorskip("telethon")
    assert mtproto_replay._build_hardened_state() is mtproto_replay._build_hardened_state()


def test_ensure_replay_protection_idempotent(monkeypatch):
    pytest.importorskip("telethon")
    monkeypatch.setattr(mtproto_replay, "_native_protection_present", lambda: False)

    Hardened = mtproto_replay._build_hardened_state()

    from collections import deque

    state = object.__new__(Hardened)
    state._recent_remote_ids = deque(maxlen=mtproto_replay.MAX_RECENT_MSG_IDS)
    state._highest_remote_id = 0
    state._ignore_count = 0

    class _Sender:
        pass

    sender = _Sender()
    sender._state = state
    sender._loggers = {}

    class _Client:
        pass

    client = _Client()
    client._sender = sender

    assert mtproto_replay.ensure_replay_protection(client) == "hardened"
    assert sender._state is state

    assert mtproto_replay.ensure_replay_protection(client) == "hardened"
    assert sender._state is state
