"""
kitsune/secure/customtl.py

Переопределяет два класса herokutl для работы через unix-сокет proxy-демона:

  MTProtoState  — отключает шифрование на стороне клиента.
                  Шифрование берёт на себя proxy-демон (как в Heroku).
                  Используется ТОЛЬКО в Docker/server-деплое с patcher.py.

  ConnectionTcpFull — добавляет set_unix_socket() и переопределяет _connect()
                      для подключения через локальный unix-сокет.

⚠️  Эти классы НЕ используются при обычном запуске.
    Они активируются только через secure/patcher.py когда поднят proxy-демон.
"""

import asyncio
import logging
import time

from herokutl.errors import InvalidBufferError, SecurityError
from herokutl.extensions import BinaryReader
from herokutl.network import ConnectionTcpFull as _ConnectionTcpFullBase
from herokutl.network.mtprotostate import MTProtoState as _MTProtoStateBase
from herokutl.tl.core import TLMessage
from herokutl.tl.types import BadMsgNotification, BadServerSalt

logger = logging.getLogger(__name__)

# Допустимые дельты по времени MTProto-сообщений (в секундах)
_MSG_TOO_NEW_DELTA = 30
_MSG_TOO_OLD_DELTA = 300


class MTProtoState(_MTProtoStateBase):
    """
    MTProtoState без шифрования исходящих пакетов.

    encrypt_message_data() возвращает данные как есть —
    реальное шифрование делает proxy-демон на другом конце unix-сокета.

    decrypt_message_data() разбирает сырой MTProto-пакет вручную,
    проверяя только временны́е метки и дублирующиеся msg_id.
    """

    def encrypt_message_data(self, data: bytes) -> bytes:
        logger.debug("MTProtoState: пропускаем шифрование (proxy-демон шифрует сам)")
        return data

    def decrypt_message_data(self, body: bytes):
        now = time.time() + self.time_offset

        if len(body) < 8:
            raise InvalidBufferError(body)

        logger.debug("MTProtoState: сырой пакет %d байт", len(body))

        reader = BinaryReader(body)
        remote_msg_id = reader.read_long()

        if remote_msg_id % 2 != 1:
            raise SecurityError("Сервер прислал чётный msg_id")

        if (
            remote_msg_id <= self._highest_remote_id
            and remote_msg_id in self._recent_remote_ids
        ):
            logger.warning("Сервер повторно прислал msg_id %d — игнорируем", remote_msg_id)
            self._count_ignored()
            return None

        remote_sequence = reader.read_int()
        reader.read_int()  # message_data_length (не нужен, читаем далее через tgread_object)
        obj = reader.tgread_object()

        if obj.CONSTRUCTOR_ID not in (
            BadServerSalt.CONSTRUCTOR_ID,
            BadMsgNotification.CONSTRUCTOR_ID,
        ):
            remote_msg_time = remote_msg_id >> 32
            delta = now - remote_msg_time

            if delta > _MSG_TOO_OLD_DELTA:
                logger.warning("Слишком старый msg_id %d — игнорируем", remote_msg_id)
                self._count_ignored()
                return None

            if -delta > _MSG_TOO_NEW_DELTA:
                logger.warning("Слишком новый msg_id %d — игнорируем", remote_msg_id)
                self._count_ignored()
                return None

        self._recent_remote_ids.append(remote_msg_id)
        self._highest_remote_id = remote_msg_id
        self._ignore_count = 0

        return TLMessage(remote_msg_id, remote_sequence, obj)


class ConnectionTcpFull(_ConnectionTcpFullBase):
    """
    TCP-Full соединение с поддержкой unix-сокета.

    set_unix_socket(path) — сохраняет путь к сокету.
    _connect()            — подключается через asyncio.open_unix_connection
                            вместо обычного TCP.
    """

    def set_unix_socket(self, unix_socket_path: str) -> None:
        self._unix_socket_path: str = unix_socket_path
        logger.debug("ConnectionTcpFull: unix-сокет → %s", unix_socket_path)

    async def _connect(self, timeout=None, ssl=None) -> None:
        path = getattr(self, "_unix_socket_path", None)
        if path is None:
            # Путь не задан — обычное TCP-соединение
            await super()._connect(timeout=timeout, ssl=ssl)
            return

        logger.debug("ConnectionTcpFull: соединяемся через unix-сокет %s", path)

        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_unix_connection(path=path, ssl=None),
            timeout=timeout,
        )

        self._codec = self.packet_codec(self)
        self._init_conn()
        await self._writer.drain()
