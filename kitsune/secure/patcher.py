"""
kitsune/secure/patcher.py

Патчит KitsuneTelegramClient для работы через unix-сокет proxy-демона.

Как это работает:
  1. Заменяет _sender._state на MTProtoState без шифрования —
     всё шифрование делает proxy-демон на другом конце сокета.
  2. Заменяет _connection на ConnectionTcpFull с unix-сокетом.
  3. Оборачивает client.connect() чтобы он автоматически передавал
     путь к сокету.

Вызывать только при Docker/server-деплое, когда proxy-демон запущен.
При обычном запуске (прямой TCP или MTProto-прокси) patcher НЕ нужен.
"""

import functools
import logging
import re
from pathlib import Path

from herokutl.sessions import SQLiteSession

from ..tl_cache import KitsuneTelegramClient
from .customtl import ConnectionTcpFull, MTProtoState

logger = logging.getLogger(__name__)


def patch(client: KitsuneTelegramClient, session: SQLiteSession) -> None:
    """
    Патчит клиент для работы через unix-сокет.

    :param client:  Экземпляр KitsuneTelegramClient
    :param session: SQLiteSession с именем файла вида *<number>*
                    (число используется как ID сокета)
    """
    # Вытаскиваем числовой ID сессии из имени файла (напр. "kitsune1.session" → "1")
    numbers = re.findall(r"\d+", getattr(session, "filename", "0"))
    session_id = numbers[-1] if numbers else "0"

    # 1. Подменяем MTProtoState (отключаем шифрование на стороне клиента)
    #    MTProtoState.__init__ ожидает loggers[__name__] где __name__ =
    #    'herokutl.network.mtprotostate' — формируем совместимый словарь.
    import herokutl.network.mtprotostate as _ms_module
    loggers = dict(client._sender._loggers)
    if _ms_module.__name__ not in loggers:
        import logging
        loggers[_ms_module.__name__] = logging.getLogger(_ms_module.__name__)
    client._sender._state = MTProtoState(session.auth_key, loggers)

    # 2. Подменяем класс соединения на тот, что умеет unix-сокеты
    client._connection = ConnectionTcpFull

    # 3. Вычисляем путь к unix-сокету proxy-демона
    #    Сокет создаётся proxy-демоном рядом с корнем проекта
    socket_path = (
        Path(__file__).parent.parent.parent / f"kitsune-{session_id}-proxy.sock"
    )

    # 4. Оборачиваем connect() так, чтобы он всегда передавал unix_socket_path
    client.connect = functools.partial(
        client.connect,
        unix_socket_path=str(socket_path),
    )

    logger.warning(
        "secure/patcher: клиент пропатчен → unix-сокет %s", socket_path
    )
