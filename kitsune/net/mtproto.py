from __future__ import annotations
import logging

from .telethon_patch import normalize_secret

logger = logging.getLogger(__name__)

def get_mtproto_connection_class(secret: str | None = None):
    from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate
    try:
        from ..mtproto_faketls import (
            ConnectionTcpMTProxyFakeTLS,
            is_faketls_secret,
        )
        if is_faketls_secret(secret):
            return ConnectionTcpMTProxyFakeTLS
    except Exception as exc:
        logger.debug("rkn_bypass: FakeTLS helper unavailable — %s", exc)
    return ConnectionTcpMTProxyRandomizedIntermediate
def get_connection_class(use_proxy: bool = False, secret: str | None = None):
    from telethon.network.connection import ConnectionTcpFull
    if use_proxy:
        return get_mtproto_connection_class(secret)
    return ConnectionTcpFull
async def test_connection(
    host: str = "api.telegram.org",
    port: int = 443,
    timeout: float = 5.0,
) -> bool:
    import asyncio
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False
async def mtproxy_handshake_check(
    host: str,
    port: int,
    secret: str,
    timeout: float = 8.0,
) -> bool:
    import asyncio
    try:
        from telethon import TelegramClient
    except Exception:
        return await test_connection(host, port, timeout=timeout)
    secret = normalize_secret(secret)
    try:
        from telethon.sessions import MemorySession
        client = TelegramClient(
            MemorySession(),
            api_id=1,
            api_hash="0" * 32,
            connection=get_mtproto_connection_class(secret),
            proxy=(host, port, secret),
            connection_retries=1,
            retry_delay=1,
            auto_reconnect=False,
            timeout=timeout,
        )
        try:
            await asyncio.wait_for(client.connect(), timeout=timeout)
            ok = client.is_connected()
            return bool(ok)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
    except ConnectionError:
        return False
    except Exception as exc:
        logger.debug(
            "mtproxy_handshake_check: %s:%d failed — %s",
            host, port, type(exc).__name__,
        )
        return False

__all__ = [
    "get_mtproto_connection_class",
    "get_connection_class",
    "test_connection",
    "mtproxy_handshake_check",
]
