
from __future__ import annotations

import functools
import logging
import time
import typing

logger = logging.getLogger(__name__)

MSG_TOO_NEW_DELTA = 30
MSG_TOO_OLD_DELTA = 300
MAX_RECENT_MSG_IDS = 500

_NATIVE_MARKERS = ("_recent_remote_ids", "_highest_remote_id")


def _native_protection_present() -> bool:
    try:
        from telethon.network.mtprotostate import MTProtoState
    except Exception:
        return False
    src = ""
    try:
        import inspect

        src = inspect.getsource(MTProtoState.decrypt_message_data)
    except Exception:
        src = ""
    return all(marker in src for marker in _NATIVE_MARKERS)


@functools.lru_cache(maxsize=1)
def _build_hardened_state():
    from collections import deque

    from telethon.crypto import AES
    from telethon.errors import InvalidBufferError, SecurityError
    from telethon.extensions import BinaryReader
    from telethon.network.mtprotostate import MTProtoState as _Base
    from telethon.tl.core import TLMessage
    from telethon.tl.types import BadMsgNotification, BadServerSalt

    import hashlib
    import struct

    class HardenedMTProtoState(_Base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if not hasattr(self, "_recent_remote_ids"):
                self._recent_remote_ids = deque(maxlen=MAX_RECENT_MSG_IDS)
            if not hasattr(self, "_highest_remote_id"):
                self._highest_remote_id = 0
            if not hasattr(self, "_ignore_count"):
                self._ignore_count = 0

        def _count_ignored(self) -> None:
            counter = getattr(_Base, "_count_ignored", None)
            if callable(counter):
                try:
                    return counter(self)
                except Exception:
                    pass
            self._ignore_count = getattr(self, "_ignore_count", 0) + 1

        def decrypt_message_data(self, body):
            now = time.time()

            if len(body) < 8:
                raise InvalidBufferError(body)

            key_id = struct.unpack("<Q", body[:8])[0]
            if key_id != self.auth_key.key_id:
                raise SecurityError("Server replied with an invalid auth key")

            msg_key = body[8:24]
            aes_key, aes_iv = self._calc_key(self.auth_key.key, msg_key, False)
            body = AES.decrypt_ige(body[24:], aes_key, aes_iv)

            our_key = hashlib.sha256(self.auth_key.key[96:96 + 32] + body)
            if msg_key != our_key.digest()[8:24]:
                raise SecurityError(
                    "Received msg_key doesn't match with expected one"
                )

            reader = BinaryReader(body)
            reader.read_long()
            if reader.read_long() != self.id:
                raise SecurityError(
                    "Server replied with a wrong session ID (see FAQ for details)"
                )

            remote_msg_id = reader.read_long()

            if remote_msg_id % 2 != 1:
                raise SecurityError("Server sent an even msg_id")

            if (
                remote_msg_id <= self._highest_remote_id
                and remote_msg_id in self._recent_remote_ids
            ):
                self._log.warning(
                    "Server resent the older message %d, ignoring", remote_msg_id
                )
                self._count_ignored()
                return None

            remote_sequence = reader.read_int()
            reader.read_int()
            obj = reader.tgread_object()

            if obj.CONSTRUCTOR_ID not in (
                BadServerSalt.CONSTRUCTOR_ID,
                BadMsgNotification.CONSTRUCTOR_ID,
            ):
                remote_msg_time = remote_msg_id >> 32
                time_delta = (now + self.time_offset) - remote_msg_time

                if time_delta > MSG_TOO_OLD_DELTA:
                    self._log.warning(
                        "Server sent a very old message with ID %d, ignoring",
                        remote_msg_id,
                    )
                    self._count_ignored()
                    return None

                if -time_delta > MSG_TOO_NEW_DELTA:
                    self._log.warning(
                        "Server sent a very new message with ID %d, ignoring",
                        remote_msg_id,
                    )
                    self._count_ignored()
                    return None

            self._recent_remote_ids.append(remote_msg_id)
            self._highest_remote_id = remote_msg_id
            self._ignore_count = 0

            return TLMessage(remote_msg_id, remote_sequence, obj)

    return HardenedMTProtoState


def ensure_replay_protection(client: typing.Any) -> str:
    if _native_protection_present():
        logger.debug("mtproto_replay: нативная защита telethon активна")
        return "native"

    sender = getattr(client, "_sender", None)
    state = getattr(sender, "_state", None) if sender is not None else None
    if state is None:
        logger.debug("mtproto_replay: sender/state недоступны, пропускаю")
        return "skipped"

    try:
        Hardened = _build_hardened_state()
    except Exception:
        logger.warning(
            "mtproto_replay: не удалось собрать fallback MTProtoState", exc_info=True
        )
        return "error"

    if isinstance(state, Hardened):
        return "hardened"

    try:
        new_state = Hardened(state.auth_key, sender._loggers)
        for attr in (
            "time_offset",
            "salt",
            "id",
            "_sequence",
            "_last_msg_id",
            "_recent_remote_ids",
            "_highest_remote_id",
            "_ignore_count",
        ):
            if hasattr(state, attr):
                setattr(new_state, attr, getattr(state, attr))
        sender._state = new_state
        logger.warning(
            "mtproto_replay: нативная защита не обнаружена — установлен "
            "совместимый MTProtoState с ручной replay-защитой"
        )
        return "hardened"
    except Exception:
        logger.warning(
            "mtproto_replay: не удалось установить fallback state", exc_info=True
        )
        return "error"
