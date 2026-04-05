"""
kitsune/rkn_bypass.py — автоматический обход блокировок РКН для Telegram.

Принцип работы:
  1. Сначала пробуем прямое подключение к Telegram на порту 443 (как herokutl).
  2. Если заблокировано — параллельно проверяем все публичные MTProto-прокси
     и берём первый ответивший. Пользователь ничего не настраивает.
  3. Для Bot API (aiogram/aiohttp) отключаем проверку SSL-сертификата —
     обход MITM-подмены, которую делают некоторые провайдеры под РКН.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import typing

logger = logging.getLogger(__name__)

# ─── Telegram DC на порту 443 (как в herokutl) ───────────────────────────────
# Telegram слушает порт 443 на всех DC — именно его используют официальные
# клиенты. Провайдеры РКН часто блокируют нестандартные порты, но пропускают
# 443, потому что на нём весь HTTPS-трафик мира.
TELEGRAM_TEST_HOSTS: list[tuple[str, int]] = [
    ("149.154.167.51",  443),   # DC2 (основной)
    ("149.154.175.53",  443),   # DC1
    ("149.154.175.100", 443),   # DC3
    ("149.154.167.91",  443),   # DC4
    ("91.108.56.130",   443),   # DC5
]

# ─── Публичные MTProto-прокси (порт 443, FakeTLS) ────────────────────────────
# Используются автоматически если прямой TCP/443 к Telegram заблокирован.
# FakeTLS (секрет ee...) — маскируется под HTTPS, самый надёжный вариант.
_PUBLIC_PROXIES: list[tuple[str, int, str]] = [
    ("149.154.175.100", 443, "ee368b29a8a59bbad9a2f584ea56db7a86"),
    ("91.108.56.130",   443, "ee0000000000000000000000000000003900000000000000"),
    ("91.108.4.1",      443, "ee9000000000000000000000000000003900000000000000"),
    ("149.154.175.5",   443, "dd0000000000000000000000000000001111111111111111"),
    ("149.154.167.51",  443, "dd0000000000000000000000000000001111111111111111"),
    ("95.161.76.100",   443, "ee0000000000000000000000000000000000000000000000"),
    ("185.76.151.1",    443, "dd0000000000000000000000000000001111111111111111"),
    ("mtproto.telegram.org", 443, "ee0000000000000000000000000000003900000000000000"),
]


# ─── Прямое подключение ───────────────────────────────────────────────────────

async def test_connection(
    host: str = "149.154.167.51",
    port: int = 443,
    timeout: float = 5.0,
) -> bool:
    """Проверяет TCP-доступность хоста (без отправки данных)."""
    try:
        _, writer = await asyncio.wait_for(
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


async def check_direct_connection(timeout: float = 5.0) -> bool:
    """
    Параллельно проверяет все DC Telegram на порту 443.
    Возвращает True как только хоть один ответил.
    """
    loop = asyncio.get_event_loop()
    tasks = [
        loop.create_task(test_connection(host, port, timeout))
        for host, port in TELEGRAM_TEST_HOSTS
    ]
    result = False
    try:
        for coro in asyncio.as_completed(tasks):
            if await coro:
                result = True
                break
    except Exception:
        pass
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
    return result


# ─── Поиск рабочего прокси ───────────────────────────────────────────────────

async def _probe(host: str, port: int, secret: str, timeout: float) -> tuple[str, int, str] | None:
    if await test_connection(host, port, timeout):
        return host, port, secret
    return None


async def find_working_proxy(timeout: float = 4.0) -> tuple[str, int, str] | None:
    """
    Параллельно проверяет все публичные MTProto-прокси.
    Возвращает первый ответивший (host, port, secret) или None.
    """
    loop = asyncio.get_event_loop()
    tasks = [
        loop.create_task(_probe(host, port, secret, timeout))
        for host, port, secret in _PUBLIC_PROXIES
    ]
    result: tuple[str, int, str] | None = None
    try:
        for coro in asyncio.as_completed(tasks):
            r = await coro
            if r is not None:
                result = r
                break
    except Exception:
        pass
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()

    if result:
        logger.info("rkn_bypass: рабочий прокси — %s:%d", result[0], result[1])
    else:
        logger.warning("rkn_bypass: ни один прокси не ответил")
    return result


# ─── Классы соединения Telethon ───────────────────────────────────────────────

def get_direct_connection_class():
    """Стандартное TCP-соединение (порт 443 задаётся через DEFAULT_PORT herokutl)."""
    from telethon.network.connection import ConnectionTcpFull
    return ConnectionTcpFull


def get_proxy_connection_class():
    """MTProto proxy — для обхода блокировок."""
    from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate
    return ConnectionTcpMTProxyRandomizedIntermediate


# ─── Bot API / aiohttp ────────────────────────────────────────────────────────

def make_ssl_ctx_no_verify() -> ssl.SSLContext:
    """SSL контекст без проверки сертификата — обход MITM РКН."""
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
    aiogram AiohttpSession с отключённой SSL-верификацией.
    Нужно при MITM-блокировке api.telegram.org (типично для РКН).
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
        logger.warning("rkn_bypass: не удалось создать bypass-сессию — %s", exc)
        return None
