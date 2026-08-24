
from __future__ import annotations

import collections
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kitsune import mtproto_replay


def _loggers():
    return collections.defaultdict(lambda: logging.getLogger("test.replay"))


def _make_client(state):

    class _Sender:
        pass

    sender = _Sender()
    sender._state = state
    sender._loggers = _loggers()

    class _Client:
        pass

    client = _Client()
    client._sender = sender
    return client, sender


@pytest.fixture
def force_fallback(monkeypatch):
    pytest.importorskip("telethon")
    monkeypatch.setattr(mtproto_replay, "_native_protection_present", lambda: False)


def _plain_state():
    from telethon.network.mtprotostate import MTProtoState

    return MTProtoState(None, _loggers())


def test_second_call_reuses_state_after_real_upgrade(force_fallback):
    Hardened = mtproto_replay._build_hardened_state()

    plain = _plain_state()
    client, sender = _make_client(plain)
    assert not isinstance(plain, Hardened)

    assert mtproto_replay.ensure_replay_protection(client) == "hardened"
    upgraded = sender._state
    assert isinstance(upgraded, Hardened)
    assert upgraded is not plain

    assert mtproto_replay.ensure_replay_protection(client) == "hardened"
    assert sender._state is upgraded

    assert mtproto_replay.ensure_replay_protection(client) == "hardened"
    assert sender._state is upgraded


def test_repeated_calls_preserve_replay_history(force_fallback):
    plain = _plain_state()
    client, sender = _make_client(plain)

    assert mtproto_replay.ensure_replay_protection(client) == "hardened"
    state = sender._state

    state._recent_remote_ids.extend([11, 13, 15])
    state._highest_remote_id = 15
    state._ignore_count = 2

    assert mtproto_replay.ensure_replay_protection(client) == "hardened"

    assert sender._state is state
    assert list(sender._state._recent_remote_ids) == [11, 13, 15]
    assert sender._state._highest_remote_id == 15
    assert sender._state._ignore_count == 2


def test_upgrade_carries_over_session_state(force_fallback):
    plain = _plain_state()
    plain.salt = 0x1234ABCD
    plain.time_offset = 7
    plain._sequence = 42
    plain._last_msg_id = 999
    plain._recent_remote_ids.extend([3, 5])
    plain._highest_remote_id = 5
    original_id = plain.id

    client, sender = _make_client(plain)
    assert mtproto_replay.ensure_replay_protection(client) == "hardened"

    new_state = sender._state
    assert new_state.salt == 0x1234ABCD
    assert new_state.time_offset == 7
    assert new_state.id == original_id
    assert new_state._sequence == 42
    assert new_state._last_msg_id == 999
    assert list(new_state._recent_remote_ids) == [3, 5]
    assert new_state._highest_remote_id == 5


def test_native_path_never_touches_sender_state():
    pytest.importorskip("telethon")
    if not mtproto_replay._native_protection_present():
        pytest.skip("telethon без нативной replay-защиты")

    plain = _plain_state()
    client, sender = _make_client(plain)

    for _ in range(3):
        assert mtproto_replay.ensure_replay_protection(client) == "native"
    assert sender._state is plain


def test_failed_build_leaves_state_intact(force_fallback, monkeypatch):

    def _boom():
        raise RuntimeError("no telethon internals")

    monkeypatch.setattr(mtproto_replay, "_build_hardened_state", _boom)

    plain = _plain_state()
    client, sender = _make_client(plain)

    assert mtproto_replay.ensure_replay_protection(client) == "error"
    assert sender._state is plain
    assert mtproto_replay.ensure_replay_protection(client) == "error"
    assert sender._state is plain


def test_upgrade_logs_warning_only_once(force_fallback, caplog):
    plain = _plain_state()
    client, _sender = _make_client(plain)

    with caplog.at_level(logging.WARNING, logger=mtproto_replay.__name__):
        mtproto_replay.ensure_replay_protection(client)
        mtproto_replay.ensure_replay_protection(client)
        mtproto_replay.ensure_replay_protection(client)

    installs = [
        r for r in caplog.records if "установлен" in r.getMessage()
    ]
    assert len(installs) == 1
