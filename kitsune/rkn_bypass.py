from __future__ import annotations

import logging
import re
import ssl
import typing

logger = logging.getLogger(__name__)


def normalize_secret(secret: str) -> str:
    """
    Нормализует секрет MTProto-прокси для совместимости с Telethon.

    Принимает:
    - hex чётной длины:      a1b2c3... (32–48 символов)
    - base64url без padding: секрет из tg://proxy?...&secret=XXXX ссылки

    ⚠️  Hex нечётной длины исправить нельзя без искажения ключа.
        Используй секрет из tg://proxy ссылки («Поделиться» в настройках прокси).
    """
    import base64

    s = secret.strip()

    # Валидный hex чётной длины — всё хорошо
    is_hex = all(c in '0123456789abcdefABCDEF' for c in s)
    if is_hex and len(s) % 2 == 0:
        return s.lower()

    # Hex нечётной длины — это ОШИБКА, не пытаемся угадать недостающий байт
    if is_hex and len(s) % 2 == 1:
        logger.warning(
            "normalize_secret: секрет имеет нечётную длину (%d символов). "
            "Используй секрет из tg://proxy ссылки (кнопка «Поделиться» в Telegram).",
            len(s),
        )
        return s  # отдаём как есть, Telethon выдаст понятную ошибку

    # base64url (секрет из tg://proxy ссылки) → hex
    try:
        padded = s + '=' * (-len(s) % 4)
        decoded = base64.b64decode(padded.encode(), altchars=b'-_')
        return decoded.hex()
    except Exception:
        pass

    # Отдаём как есть
    return s


# ─────────────────────── встроенный список прокси ───────────────────────────

_PUBLIC_PROXIES: list[tuple[str, int, str]] = [
    ("149.154.175.100", 443, "ee9000000000000000000000000000003900000000000000"),
    ("149.154.167.51",  443, "dd0000000000000000000000000000001111111111111111"),
    ("91.108.56.100",   443, "ee0000000000000000000000000000003900000000000000"),
    ("mtproto.telegram.org", 443, "ee0000000000000000000000000000003900000000000000"),
]

# Публичные источники MTProto-прокси
_TG_PROXY_CHANNELS: list[str] = [
    "https://t.me/s/mtp4tg",          # основной — много рабочих прокси
    "https://t.me/s/proxyme",
    "https://t.me/s/MTProxyT",
    "https://t.me/s/tg_proxy_mtproto",
]

_MTPRO_XYZ_URL = "https://mtpro.xyz/api/?type=mtproto"

# Секрет MTProto может быть hex, hex с префиксом dd/ee, или base64
_SECRET_PAT = r'([0-9a-zA-Z+/=_-]{16,})'

_RE_TG_PROXY = re.compile(
    r'tg://proxy\?server=([^&"\'<>\s]+)&port=(\d+)&secret=' + _SECRET_PAT,
    re.IGNORECASE,
)
_RE_TG_PROXY_ALT = re.compile(
    r'https://t\.me/proxy\?server=([^&"\'<>\s]+)&port=(\d+)&secret=' + _SECRET_PAT,
    re.IGNORECASE,
)

# ─────────────────────── SSL-хелперы ────────────────────────────────────────

def make_ssl_ctx_no_verify() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def get_aiohttp_connector():
    import aiohttp
    return aiohttp.TCPConnector(ssl=make_ssl_ctx_no_verify())

def get_aiogram_session(timeout: int = 30):
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
    from telethon.network.connection import (
        ConnectionTcpFull,
        ConnectionTcpMTProxyRandomizedIntermediate,
    )
    if use_proxy:
        return ConnectionTcpMTProxyRandomizedIntermediate
    return ConnectionTcpFull

# ─────────────────────── проверка соединения ────────────────────────────────

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

# ─────────────────────── веб-поиск прокси ───────────────────────────────────

async def _fetch_from_tg_channel(url: str) -> list[tuple[str, int, str]]:
    """Парсит tg://proxy?... ссылки с публичной страницы Telegram-канала."""
    try:
        import aiohttp
        ssl_ctx = make_ssl_ctx_no_verify()
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=ssl_ctx)
        ) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return []
                text = await resp.text(errors="replace")

        found: list[tuple[str, int, str]] = []
        for pattern in (_RE_TG_PROXY, _RE_TG_PROXY_ALT):
            for m in pattern.finditer(text):
                try:
                    found.append((m.group(1).strip(), int(m.group(2)), m.group(3).strip()))
                except ValueError:
                    pass
        return found
    except Exception as exc:
        logger.debug("rkn_bypass: channel %s — %s", url, exc)
        return []

async def _fetch_from_mtpro_xyz() -> list[tuple[str, int, str]]:
    """JSON-список прокси с mtpro.xyz."""
    try:
        import aiohttp
        ssl_ctx = make_ssl_ctx_no_verify()
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=ssl_ctx)
        ) as session:
            async with session.get(
                _MTPRO_XYZ_URL, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json(content_type=None)
        result: list[tuple[str, int, str]] = []
        if isinstance(data, list):
            for item in data:
                host   = item.get("host") or item.get("ip") or ""
                port   = item.get("port", 443)
                secret = item.get("secret") or item.get("pass", "")
                if host and secret:
                    try:
                        result.append((host, int(port), secret))
                    except (ValueError, TypeError):
                        pass
        return result
    except Exception as exc:
        logger.debug("rkn_bypass: mtpro.xyz — %s", exc)
        return []

async def find_proxy_from_web() -> list[tuple[str, int, str]]:
    """
    Активно ищет MTProto-прокси в интернете:
    сначала из Telegram-каналов, потом из JSON-API.
    Возвращает все найденные (без проверки доступности).
    """
    import asyncio

    tasks = [_fetch_from_tg_channel(u) for u in _TG_PROXY_CHANNELS]
    tasks.append(_fetch_from_mtpro_xyz())

    results = await asyncio.gather(*tasks, return_exceptions=True)

    proxies: list[tuple[str, int, str]] = []
    seen: set[tuple[str, int]] = set()
    for r in results:
        if isinstance(r, list):
            for item in r:
                key = (item[0], item[1])
                if key not in seen:
                    seen.add(key)
                    proxies.append(item)

    logger.info("rkn_bypass: найдено %d прокси из веб-источников", len(proxies))
    return proxies

# ─────────────────────── основной поиск ─────────────────────────────────────

async def find_working_proxy(
    extra_proxies: list[tuple[str, int, str]] | None = None,
) -> tuple[str, int, str] | None:
    """
    Ищет первый рабочий прокси.
    Порядок: встроенные → extra_proxies (из веб, если переданы).
    """
    candidates = list(_PUBLIC_PROXIES)
    if extra_proxies:
        seen = {(h, p) for h, p, _ in candidates}
        for item in extra_proxies:
            if (item[0], item[1]) not in seen:
                candidates.append(item)
                seen.add((item[0], item[1]))

    for host, port, secret in candidates:
        if await test_connection(host, port, timeout=3.0):
            logger.info("rkn_bypass: рабочий прокси %s:%d", host, port)
            return host, port, secret

    logger.warning("rkn_bypass: рабочий прокси не найден")
    return None

# ─────────────────────── применение к конфигу ───────────────────────────────

def apply_bypass_to_config(cfg: dict) -> dict:
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
        logger.info("rkn_bypass: прокси применён к конфигу")

    return cfg
