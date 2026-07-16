from __future__ import annotations
import asyncio
import logging
import re
import ssl
import sys
import typing

logger = logging.getLogger(__name__)

def ensure_python_socks(auto_install: bool = True) -> bool:
    try:
        import python_socks              
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
        import python_socks              
        logger.info("rkn_bypass: python-socks[asyncio] успешно установлен в рантайме")
        return True
    except Exception as exc:
        logger.error(
            "rkn_bypass: не удалось установить python-socks: %s. "
            "Установи вручную: pip install 'python-socks[asyncio]'", exc,
        )
        return False
def ensure_aiohttp_socks(auto_install: bool = True) -> bool:
    try:
        import aiohttp_socks              
        return True
    except ImportError:
        pass
    if not auto_install:
        return False
    logger.warning(
        "rkn_bypass: aiohttp-socks не установлен — aiogram-бот пойдёт НАПРЯМУЮ "
        "на api.telegram.org (под РКН не работает). Пытаюсь установить автоматически…"
    )
    try:
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--disable-pip-version-check", "--no-warn-script-location",
             "aiohttp-socks>=0.9.0"]
        )
        import importlib
        importlib.invalidate_caches()
        import aiohttp_socks              
        logger.info("rkn_bypass: aiohttp-socks успешно установлен в рантайме")
        return True
    except Exception as exc:
        logger.error(
            "rkn_bypass: не удалось установить aiohttp-socks: %s. "
            "Установи вручную: pip install 'aiohttp-socks>=0.9.0'", exc,
        )
        return False
def _patch_telethon_mtproxy() -> None:
    try:
        from telethon.network.connection import tcpmtproxy as _m
    except Exception as exc:
        logger.debug("rkn_bypass: telethon.tcpmtproxy недоступен — %s", exc)
        return
    target_cls = None
    for _name in dir(_m):
        obj = getattr(_m, _name, None)
        if not isinstance(obj, type):
            continue
        if "readexactly" in obj.__dict__:
            target_cls = obj
            break
    if target_cls is None:
        logger.debug("rkn_bypass: класс с readexactly не найден в tcpmtproxy")
        return
    if getattr(target_cls.readexactly, "_kitsune_size_guard", False):
        return                                                    
    original = target_cls.readexactly
    async def readexactly_safe(self, n):
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
        "rkn_bypass: fallback MTProxy patch applied (class=%s)",
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
def _build_socks_url_from_cfg() -> str | None:
    try:
        from .main import _load_raw_config
        cfg = _load_raw_config() or {}
    except Exception:
        return None
    sp = cfg.get("proxy_socks") or {}
    if not isinstance(sp, dict):
        return None
    host = sp.get("host")
    port = sp.get("port")
    if not host or not port:
        return None
    try:
        port_i = int(port)
        if not (0 < port_i < 65536):
            logger.warning("rkn_bypass: некорректный порт SOCKS5: %r", port)
            return None
    except (TypeError, ValueError):
        logger.warning("rkn_bypass: порт SOCKS5 не число: %r", port)
        return None
    user = sp.get("username") or sp.get("user")
    pwd  = sp.get("password") or sp.get("pass")
    if user and pwd:
        from urllib.parse import quote
        auth = f"{quote(str(user), safe='')}:{quote(str(pwd), safe='')}@"
    else:
        if user or pwd:
            logger.warning(
                "rkn_bypass: для SOCKS5 указан только %s — auth отключён",
                "username" if user else "password",
            )
        auth = ""
    scheme = str(sp.get("type", "socks5")).lower()
    if scheme not in ("socks5", "socks4", "http", "https"):
        scheme = "socks5"
    return f"{scheme}://{auth}{host}:{port_i}"
def get_socks_proxy_url() -> str | None:
    return _build_socks_url_from_cfg()
def _get_socks_connector_cls():
    try:
        from aiohttp_socks import ProxyConnector                
        return ProxyConnector
    except ImportError:
        if ensure_aiohttp_socks():
            try:
                from aiohttp_socks import ProxyConnector                
                return ProxyConnector
            except ImportError:
                pass
        return None
def _build_socks_connector(ssl_ctx: ssl.SSLContext | None = None):
    cls = _get_socks_connector_cls()
    if cls is None:
        return None
    proxy_url = _build_socks_url_from_cfg()
    if not proxy_url:
        return None
    if ssl_ctx is None:
        ssl_ctx = make_ssl_ctx_no_verify()
    try:
        return cls.from_url(proxy_url, ssl=ssl_ctx, rdns=True)
    except TypeError:
        try:
            return cls.from_url(proxy_url, ssl=ssl_ctx)
        except Exception as exc:
            logger.warning(
                "rkn_bypass: ProxyConnector.from_url(%s) упал: %s",
                proxy_url, exc,
            )
            return None
    except Exception as exc:
        logger.warning(
            "rkn_bypass: ProxyConnector.from_url(%s) упал: %s",
            proxy_url, exc,
        )
        return None
def get_aiohttp_connector_with_proxy():
    import aiohttp
    ssl_ctx = make_ssl_ctx_no_verify()
    proxy_url = _build_socks_url_from_cfg()
    if proxy_url:
        connector = _build_socks_connector(ssl_ctx)
        if connector is not None:
            return connector
        logger.warning(
            "rkn_bypass: SOCKS5 настроен (%s), но aiohttp_socks недоступен — "
            "fallback на прямой TCP. Установи: pip install 'aiohttp-socks>=0.9.0'",
            proxy_url,
        )
    return aiohttp.TCPConnector(ssl=ssl_ctx)
def _fmt_exc(exc: BaseException, timeout: float | None = None) -> str:
    name = type(exc).__name__
    msg = str(exc).strip(". ")
    if not msg:
        if isinstance(exc, asyncio.TimeoutError) and timeout is not None:
            msg = f"timeout {timeout:.1f}s"
        else:
            msg = "no message"
    return f"{name}: {msg}"
async def test_socks_proxy(timeout: float = 15.0) -> tuple[bool, str]:
    proxy_url = _build_socks_url_from_cfg()
    if not proxy_url:
        return False, "SOCKS5 не настроен (.setsocks <host> <port>)."
    if _get_socks_connector_cls() is None:
        return False, (
            "aiohttp_socks не установлен. Установи: "
            "pip install 'aiohttp-socks>=0.9.0'"
        )
    import aiohttp
    try:
        connector = _build_socks_connector(make_ssl_ctx_no_verify())
        if connector is None:
            return False, "не удалось собрать SOCKS5-коннектор (см. лог)."
        async with aiohttp.ClientSession(connector=connector) as sess:
            async with sess.get(
                "https://api.telegram.org",
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=False,
            ) as resp:
                return True, f"SOCKS5 OK (HTTP {resp.status}) → {proxy_url}"
    except Exception as exc:
        return False, f"{_fmt_exc(exc, timeout)} (HTTPS via SOCKS5 → api.telegram.org)"
def get_aiogram_session(timeout: int = 30):
    try:
        from aiogram.client.session.aiohttp import AiohttpSession
        import aiohttp
        ssl_ctx = make_ssl_ctx_no_verify()
        proxy_url = _build_socks_url_from_cfg()
        socks_connector_cls = None
        if proxy_url:
            socks_connector_cls = _get_socks_connector_cls()
            if socks_connector_cls is None:
                logger.warning(
                    "rkn_bypass: SOCKS5 настроен (%s), но aiohttp_socks "
                    "не установлен. aiogram-бот пойдёт НАПРЯМУЮ — под РКН "
                    "это сломает backup/inline. Установи: "
                    "pip install 'aiohttp-socks>=0.9.0'",
                    proxy_url,
                )
        class _RKNBypassSession(AiohttpSession):
            async def create_connector(self, _bot=None):
                if socks_connector_cls is not None and proxy_url:
                    try:
                        connector = socks_connector_cls.from_url(
                            proxy_url, ssl=ssl_ctx, rdns=True,
                        )
                    except TypeError:
                        connector = socks_connector_cls.from_url(
                            proxy_url, ssl=ssl_ctx,
                        )
                    logger.debug("rkn_bypass: aiogram session uses SOCKS5 → %s", proxy_url)
                else:
                    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
                self._should_reset_connector = False
                return connector
        return _RKNBypassSession(timeout=timeout)
    except Exception as exc:
        logger.warning("rkn_bypass: failed to create bypass session — %s", exc)
        return None
def make_aiogram_bot(token: str, *, parse_mode: str = "HTML", timeout: int = 30):
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    if _build_socks_url_from_cfg():
        ensure_aiohttp_socks()
    pm = ParseMode.HTML if str(parse_mode).upper() == "HTML" else ParseMode.MARKDOWN
    session = get_aiogram_session(timeout=timeout)
    kwargs = dict(token=str(token), default=DefaultBotProperties(parse_mode=pm))
    if session is not None:
        kwargs["session"] = session
    return Bot(**kwargs)
def get_mtproto_connection_class(secret: str | None = None):
    from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate
    try:
        from .mtproto_faketls import (
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
    deep_check: bool = True,
) -> tuple[str, int, str] | None:
    candidates = list(_PUBLIC_PROXIES)
    if extra_proxies:
        seen = {(h, p) for h, p, _ in candidates}
        for item in extra_proxies:
            if (item[0], item[1]) not in seen:
                candidates.append(item)
                seen.add((item[0], item[1]))
    for host, port, secret in candidates:
        if not await test_connection(host, port, timeout=3.0):
            continue
        if deep_check:
            ok = await mtproxy_handshake_check(host, port, secret, timeout=8.0)
            if not ok:
                logger.debug(
                    "rkn_bypass: %s:%d — TCP OK, но handshake провален",
                    host, port,
                )
                continue
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
