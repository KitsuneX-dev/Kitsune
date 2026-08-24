from __future__ import annotations

import logging

import aiohttp

logger = logging.getLogger(__name__)

_LIMIT = 100
_LIMIT_PER_HOST = 10
_KEEPALIVE_TIMEOUT = 30

_shared_session: aiohttp.ClientSession | None = None


def get_shared_session() -> aiohttp.ClientSession:
    global _shared_session
    if _shared_session is None or _shared_session.closed:
        connector = aiohttp.TCPConnector(
            limit=_LIMIT,
            limit_per_host=_LIMIT_PER_HOST,
            keepalive_timeout=_KEEPALIVE_TIMEOUT,
            enable_cleanup_closed=True,
        )
        _shared_session = aiohttp.ClientSession(connector=connector)
        logger.debug(
            "http_pool: создана общая ClientSession (limit=%d, per_host=%d)",
            _LIMIT,
            _LIMIT_PER_HOST,
        )
    return _shared_session


async def close_shared_session() -> None:
    global _shared_session
    if _shared_session is not None and not _shared_session.closed:
        try:
            await _shared_session.close()
        except Exception:
            logger.debug("http_pool: ошибка закрытия общей сессии", exc_info=True)
    _shared_session = None


__all__ = ["get_shared_session", "close_shared_session"]
