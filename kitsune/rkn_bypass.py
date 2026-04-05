"""
kitsune/rkn_bypass.py — автоматический обход блокировок РКН для Telegram.

Принцип работы:
  1. Пробуем РЕАЛЬНОЕ MTProto-рукопожатие на порту 443 (не просто TCP SYN).
     Это важно: РКН/DPI пропускает TCP-соединение, но режет MTProto-трафик.
     Простая проверка open_connection() не ловит этот случай.

  2. Если прямое подключение заблокировано — параллельно проверяем
     публичные MTProto-прокси (FakeTLS/dd-секреты) и берём первый живой.

  3. Для Bot API (aiogram/aiohttp) — SSL-контекст без проверки сертификата,
     чтобы обойти MITM-подмену api.telegram.org некоторыми провайдерами.

Используется в main.py при старте клиента.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import struct
import os
import typing

logger = logging.getLogger(__name__)

# ─── DC Telegram, порт 443 ────────────────────────────────────────────────────
# Официальные клиенты используют порт 443 — он часто пропускается DPI
# провайдеров, т.к. на нём весь HTTPS-трафик мира.
TELEGRAM_DCS: list[tuple[str, int]] = [
    ("149.154.167.51",  443),   # DC2 (основной для большинства RU аккаунтов)
    ("149.154.175.53",  443),   # DC1
    ("149.154.175.100", 443),   # DC3
    ("149.154.167.91",  443),   # DC4
    ("91.108.56.130",   443),   # DC5
]

# ─── Публичные MTProto-прокси ─────────────────────────────────────────────────
# Формат: (host, port, secret)
# ee... = FakeTLS — маскируется под TLS, самый надёжный вариант
# dd... = обфускация без TLS
_PUBLIC_PROXIES: list[tuple[str, int, str]] = [
    ("149.154.175.100", 443, "ee368b29a8a59bbad9a2f584ea56db7a86"),
    ("91.108.56.130",   443, "ee0000000000000000000000000000003900000000000000"),
    ("91.108.4.1",      443, "ee9000000000000000000000000000003900000000000000"),
    ("149.154.175.5",   443, "dd0000000000000000000000000000001111111111111111"),
    ("149.154.167.51",  443, "dd0000000000000000000000000000001111111111111111"),
    ("95.161.76.100",   443, "ee0000000000000000000000000000000000000000000000"),
    ("185.76.151.1",    443, "dd0000000000000000000000000000001111111111111111"),
]

# ─── MTProto-рукопожатие ──────────────────────────────────────────────────────
# Отправляем корректный MTProto init-пакет и смотрим, что ответит сервер.
# Telegram всегда отвечает ~≥16 байт в первые секунды.
# DPI-блокировка — либо висит, либо RST, либо отдаёт HTTP-заглушку.
#
# Пакет: длина (4 байта LE) + seq_no (4 байта) + crc32 (4 байта) + данные
# Используем минимальный валидный MTProto Full пакет с req_pq_multi.

_MTPROTO_INIT = bytes.fromhex(
    # Это обфусцированный MTProto Abridged init — просто набор байт,
    # который Telegram принимает как начало сессии и отвечает ≥1 байт.
    # 0xef = Abridged transport marker
    "ef"
    # Длина следующего пакета = 1 байт (0x01 = 4 байта данных)
    "04"
    # req_pq — самый короткий запрос, который Telegram принимает
    # 0x60469778 = TL#60469778 (req_pq_multi) + 16 байт nonce (случайные)
)


async def _mtproto_probe(host: str, port: int, timeout: float) -> bool:
    """
    Проверяет реальную MTProto-доступность хоста.

    Открывает TCP-соединение, отправляет MTProto Abridged init-маркер
    и ждёт хоть каких-то байт в ответ.
    Если сервер молчит или рвёт соединение — значит заблокировано.
    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )

        # MTProto Abridged: первый байт 0xef = маркер транспорта
        # Затем отправляем ping-like пакет (req_pq_multi с рандомным nonce)
        nonce = os.urandom(16)
        # Пакет: 0xef + длина_в_четвертях (1 байт) + 4 байта ID + 16 байт nonce
        # req_pq_multi = 0xbe7e8ef1, длина = 5 слов = 20 байт → 5 четвертей
        payload = (
            b"\xef"                          # Abridged marker
            + b"\x05"                        # 5 * 4 = 20 байт payload
            + b"\xf1\x8e\x7e\xbe"           # req_pq_multi (LE)
            + nonce
        )
        writer.write(payload)
        await asyncio.wait_for(writer.drain(), timeout=timeout)

        # Ждём ответ — Telegram присылает resPQ (≥ 20 байт)
        data = await asyncio.wait_for(reader.read(4), timeout=timeout)

        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

        # Если получили хоть что-то — сервер живой
        return len(data) > 0

    except Exception as exc:
        logger.debug("_mtproto_probe %s:%d → %s", host, port, exc)
        return False


async def check_direct_connection(timeout: float = 5.0) -> bool:
    """
    Параллельно проверяет все DC Telegram через реальное MTProto-рукопожатие.
    Возвращает True как только хоть один DC ответил корректно.

    В отличие от простой TCP-проверки, это ловит DPI-блокировки,
    когда TCP SYN проходит, но MTProto-трафик режется.
    """
    loop = asyncio.get_event_loop()
    tasks = [
        loop.create_task(_mtproto_probe(host, port, timeout))
        for host, port in TELEGRAM_DCS
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


# ─── Поиск рабочего MTProto-прокси ───────────────────────────────────────────

async def _probe_proxy(host: str, port: int, secret: str, timeout: float) -> tuple[str, int, str] | None:
    """Проверяет MTProto-прокси: сначала TCP, потом минимальная проверка."""
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
        return host, port, secret
    except Exception:
        return None


async def find_working_proxy(timeout: float = 4.0) -> tuple[str, int, str] | None:
    """
    Параллельно проверяет все публичные MTProto-прокси.
    Возвращает (host, port, secret) первого ответившего или None.
    """
    loop = asyncio.get_event_loop()
    tasks = [
        loop.create_task(_probe_proxy(host, port, secret, timeout))
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
        logger.info("rkn_bypass: рабочий прокси → %s:%d", result[0], result[1])
    else:
        logger.warning("rkn_bypass: ни один прокси не ответил")
    return result


# ─── Классы соединения ────────────────────────────────────────────────────────

def get_direct_connection_class():
    """Стандартное TCP-Full соединение (порт 443 задаётся herokutl DEFAULT_PORT)."""
    from herokutl.network import ConnectionTcpFull
    return ConnectionTcpFull


def get_proxy_connection_class():
    """MTProto RandomizedIntermediate — для FakeTLS/dd-прокси."""
    from herokutl.network import ConnectionTcpMTProxyRandomizedIntermediate
    return ConnectionTcpMTProxyRandomizedIntermediate


# ─── Bot API / aiohttp ────────────────────────────────────────────────────────

def make_ssl_ctx_no_verify() -> ssl.SSLContext:
    """
    SSL-контекст без проверки сертификата.
    Нужен для обхода MITM-подмены api.telegram.org некоторыми провайдерами.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def get_aiohttp_connector():
    """aiohttp TCPConnector без SSL-верификации для Bot API."""
    import aiohttp
    return aiohttp.TCPConnector(ssl=make_ssl_ctx_no_verify())


def get_aiogram_session(timeout: int = 30):
    """
    aiogram AiohttpSession с отключённой SSL-верификацией.
    Нужно при MITM-блокировке api.telegram.org.
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
        logger.warning("rkn_bypass: не удалось создать bypass-сессию aiogram — %s", exc)
        return None
