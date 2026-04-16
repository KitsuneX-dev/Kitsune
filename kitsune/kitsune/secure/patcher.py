
import functools
import logging
import re
from pathlib import Path

from herokutl.sessions import SQLiteSession

from ..tl_cache import KitsuneTelegramClient
from .customtl import ConnectionTcpFull, MTProtoState

logger = logging.getLogger(__name__)

def patch(client: KitsuneTelegramClient, session: SQLiteSession) -> None:
    numbers = re.findall(r"\d+", getattr(session, "filename", "0"))
    session_id = numbers[-1] if numbers else "0"

    import herokutl.network.mtprotostate as _ms_module
    loggers = dict(client._sender._loggers)
    if _ms_module.__name__ not in loggers:
        import logging
        loggers[_ms_module.__name__] = logging.getLogger(_ms_module.__name__)
    client._sender._state = MTProtoState(session.auth_key, loggers)

    client._connection = ConnectionTcpFull

    socket_path = (
        Path(__file__).parent.parent.parent / f"kitsune-{session_id}-proxy.sock"
    )

    client.connect = functools.partial(
        client.connect,
        unix_socket_path=str(socket_path),
    )

    logger.warning(
        "secure/patcher: клиент пропатчен → unix-сокет %s", socket_path
    )
