from __future__ import annotations

import logging
import re
import ssl
import sys
import typing

logger = logging.getLogger(__name__)


def ensure_python_socks(auto_install: bool = True) -> bool:
    """
    Проверяет наличие python-socks[asyncio]; при отсутствии пытается установить в рантайме.

    Telethon >=1.36 использует именно python-socks (а НЕ PySocks) для всех типов прокси,
    включая MTProto. Без этой библиотеки параметр ``proxy`` МОЛЧА игнорируется — видим
    только UserWarning, и бот пытается подключиться напрямую (что в РФ под блокировкой
    РКН не работает).
    """
    try:
        import python_socks  # noqa: F401
        return True
    except ImportError:
        pass

    if not auto_install:
        return False

    logger.warning(
        "rkn_bypass: python-socks не установлен — прокси в Telethon НЕ работают. "
        "Пытаюсь установить автоматически…"
    )
    try:
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--disable-pip-version-check", "--no-warn-script-location",
             "python-socks[asyncio]>=2.4.4"]
        )
        import importlib
        importlib.invalidate_caches()
        import python_socks  # noqa: F401
        logger.info("rkn_bypass: python-socks[asyncio] успешно установлен в рантайме")
        return True
    except Exception as exc:
        logger.error(
            "rkn_bypass: не удалось установить python-socks: %s. "
            "Установи вручную: pip install 'python-socks[asyncio]'", exc,
        )
        return False


def _patch_telethon_mtproxy() -> None:
    """
    Патч на баг Telethon с MTProto-прокси:

        File ".../telethon/network/connection/tcpmtproxy.py", line 77, in readexactly
            return self._decrypt.encrypt(await self._reader.readexactly(n))
        File ".../asyncio/streams.py", line 694, in readexactly
            raise ValueError('readexactly size can not be less than zero')

    Когда MTProxy-handshake заканчивается мусором (мёртвый/несовместимый прокси,
    разрыв в середине FakeTLS), обфусцированный декодер парсит "длину" следующего
    пакета как отрицательное int — и потом сам же вызывает ``readexactly(<0)``.
    asyncio роняет ValueError, который Telethon НЕ ловит → весь _recv_loop крашится,
    но MTProtoSender при этом не очищает состояние и при следующем reconnect видит
    ``self._connection = None`` → вторичная ошибка ``AttributeError: 'NoneType'.connect``.

    Решение: обернуть ``readexactly`` обфусцированного reader'а так, чтобы при
    некорректном ``n`` мы сразу бросали ``ConnectionError``. Telethon корректно
    обрабатывает ConnectionError в _recv_loop как обрыв и инициирует штатный
    reconnect через ``auto_reconnect``.

    ВАЖНО: патч применяется на ВСЕХ версиях Python (раньше был ограничен 3.13+ —
    это и было причиной того, что под Python 3.10 баг проявлялся). Имя класса
    тоже определяем динамически (в разных версиях Telethon оно отличается:
    ``MTProxyIO`` / ``ObfuscatedIO`` / приватный ``_MTProxyReader``).
    """
    try:
        from telethon.network.connection import tcpmtproxy as _m
    except Exception as exc:
        logger.debug("rkn_bypass: telethon.tcpmtproxy недоступен — %s", exc)
        return

    # 1) Находим класс, в котором ОПРЕДЕЛЁН (а не унаследован) метод readexactly.
    target_cls = None
    for _name in dir(_m):
        obj = getattr(_m, _name, None)
        if not isinstance(obj, type):
            continue
        if "readexactly" in obj.__dict__:
            target_cls = obj
            break

    if target_cls is None:
        logger.debug(
            "rkn_bypass: класс с readexactly не найден в tcpmtproxy "
            "(возможно, эта версия Telethon уже не страдает багом)"
        )
        return

    if getattr(target_cls.readexactly, "_kitsune_size_guard", False):
        return  # уже пропатчено

    original = target_cls.readexactly

    async def readexactly_safe(self, n):
        # asyncio.StreamReader.readexactly валится с ValueError при n<0.
        # n==0 формально валиден (вернёт b''), но в контексте MTProxy это
        # тоже почти всегда означает рассинхронизацию обфусцированного
        # потока — лучше честный обрыв, чем тихая дыра в стриме.
        if n is None or n < 0:
            raise ConnectionError(
                f"MTProxy: получен невалидный размер пакета ({n!r}). "
                "Прокси, вероятно, мёртв или не поддерживает FakeTLS — обрываю."
            )
        if n == 0:
            return b""
        return await original(self, n)

    readexactly_safe._kitsune_size_guard = True
    target_cls.readexactly = readexactly_safe
    logger.info(
        "rkn_bypass: Telethon MTProxy reader пропатчен (size guard) — class=%s",
        target_cls.__name__,
    )


_patch_telethon_mtproxy()


def normalize_secret(secret: str) -> str:
    import base64

    s = secret.strip()

    is_hex = all(c in '0123456789abcdefABCDEF' for c in s)
    if is_hex and len(s) % 2 == 0:
        return s.lower()

    if is_hex and len(s) % 2 == 1:
        logger.warning(
            "normalize_secret: секрет имеет нечётную длину (%d символов). "
            "Используй секрет из tg://proxy ссылки (кнопка «Поделиться» в Telegram).",
            len(s),
        )
        return s

    try:
        padded = s + '=' * (-len(s) % 4)
        decoded = base64.b64decode(padded.encode(), altchars=b'-_')
        return decoded.hex()
    except Exception:
        pass

    return s

_PUBLIC_PROXIES: list[tuple[str, int, str]] = [
    ("149.154.175.100", 443, "ee9000000000000000000000000000003900000000000000"),
    ("149.154.167.51",  443, "dd0000000000000000000000000000001111111111111111"),
    ("91.108.56.100",   443, "ee0000000000000000000000000000003900000000000000"),
    ("mtproto.telegram.org", 443, "ee0000000000000000000000000000003900000000000000"),
]

_TG_PROXY_CHANNELS: list[str] = [
    "https://t.me/s/mtp4tg",
    "https://t.me/s/proxyme",
    "https://t.me/s/MTProxyT",
    "https://t.me/s/tg_proxy_mtproto",
]

_MTPRO_XYZ_URL = "https://mtpro.xyz/api/?type=mtproto"

_SECRET_PAT = r'([0-9a-zA-Z+/=_-]{16,})'

_RE_TG_PROXY = re.compile(
    r'tg://proxy\?server=([^&"\'<>\s]+)&port=(\d+)&secret=' + _SECRET_PAT,
    re.IGNORECASE,
)
_RE_TG_PROXY_ALT = re.compile(
    r'https://t\.me/proxy\?server=([^&"\'<>\s]+)&port=(\d+)&secret=' + _SECRET_PAT,
    re.IGNORECASE,
)

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

async def _fetch_from_tg_channel(url: str) -> list[tuple[str, int, str]]:
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

async def find_working_proxy(
    extra_proxies: list[tuple[str, int, str]] | None = None,
) -> tuple[str, int, str] | None:
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
