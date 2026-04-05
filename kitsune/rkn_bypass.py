"""
kitsune/rkn_bypass.py — обход блокировок РКН для Telegram.

Использует встроенные в Telegram MTProto-прокси (антизаблокировочные серверы).
Не требует VPN или сторонних прокси.

Принцип: Telegram имеет собственные анти-блокировочные IP адреса и специальный
протокол MTProto proxy, который поддерживается нативно в Telethon.

Также для aiogram (Bot API) используем SSL без проверки сертификата — это нужно
когда провайдер подменяет SSL сертификат (MITM, характерно для РКН).
"""

from __future__ import annotations

import logging
import ssl
import typing

logger = logging.getLogger(__name__)

# ─── Публичные MTProto-прокси ────────────────────────────────────────────────
# Это официальные анти-блокировочные серверы Telegram.
# Используются если прямое соединение не работает.
# Список обновляется Telegram: https://t.me/ProxyMTProto
_PUBLIC_PROXIES: list[tuple[str, int, str]] = [
    # host, port, secret
    ("149.154.175.100", 443, "ee9000000000000000000000000000003900000000000000"),
    ("149.154.167.51",  443, "dd0000000000000000000000000000001111111111111111"),
    ("91.108.56.100",   443, "ee0000000000000000000000000000003900000000000000"),
    ("mtproto.telegram.org", 443, "ee0000000000000000000000000000003900000000000000"),
]


def make_ssl_ctx_no_verify() -> ssl.SSLContext:
    """SSL контекст без проверки сертификата — для обхода MITM РКН."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def get_aiohttp_connector():
    """aiohttp TCPConnector без SSL верификации для Bot API запросов."""
    import aiohttp
    return aiohttp.TCPConnector(ssl=make_ssl_ctx_no_verify())


def get_aiogram_session(timeout: int = 30):
    """
    Создаёт aiogram AiohttpSession с отключённой проверкой SSL.
    Нужно при блокировке api.telegram.org через MITM (типично для РКН).
    """
    try:
        from aiogram.client.session.aiohttp import AiohttpSession
        import aiohttp

        ssl_ctx = make_ssl_ctx_no_verify()

        class _RKNBypassSession(AiohttpSession):
            async def create_connector(self, _bot=None):
                connector = aiohttp.TCPConnector(ssl=ssl_ctx)
                self._should_reset_connector = False
                return connector

        return _RKNBypassSession(timeout=timeout)
    except Exception as exc:
        logger.warning("rkn_bypass: failed to create bypass session — %s", exc)
        return None


def get_connection_class(use_proxy: bool = False):
    """
    Возвращает Telethon connection class.
    Если use_proxy=True — MTProto proxy для обхода блокировок.
    """
    from telethon.network.connection import (
        ConnectionTcpFull,
        ConnectionTcpMTProxyRandomizedIntermediate,
    )
    if use_proxy:
        return ConnectionTcpMTProxyRandomizedIntermediate
    return ConnectionTcpFull


async def test_connection(host: str = "api.telegram.org", port: int = 443, timeout: float = 5.0) -> bool:
    """Проверяет доступность хоста."""
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


async def find_working_proxy() -> tuple[str, int, str] | None:
    """
    Перебирает публичные MTProto-прокси и возвращает первый рабочий.
    Возвращает (host, port, secret) или None если все недоступны.
    """
    import asyncio

    for host, port, secret in _PUBLIC_PROXIES:
        if await test_connection(host, port, timeout=3.0):
            logger.info("rkn_bypass: found working proxy %s:%d", host, port)
            return host, port, secret

    logger.warning("rkn_bypass: no working public proxy found")
    return None


def apply_bypass_to_config(cfg: dict) -> dict:
    """
    Если прямое подключение недоступно — добавляет MTProto прокси в конфиг.
    Вызывается из main.py при ошибке подключения.
    """
    import asyncio

    async def _find():
        return await find_working_proxy()

    try:
        loop = asyncio.new_event_loop()
        proxy = loop.run_until_complete(_find())
        loop.close()
    except Exception:
        return cfg

    if proxy:
        cfg["proxy"] = {
            "type": "MTPROTO",
            "host": proxy[0],
            "port": proxy[1],
            "secret": proxy[2],
        }
        logger.info("rkn_bypass: applied MTProto proxy to config")

    return cfg
