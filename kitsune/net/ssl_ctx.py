from __future__ import annotations
import asyncio
import logging
import ssl
from typing import Any

from .telethon_patch import ensure_aiohttp_socks

logger = logging.getLogger(__name__)

def make_ssl_ctx(verify: bool = True) -> ssl.SSLContext:
    if not verify:
        logger.warning(
            "rkn_bypass: SSL-верификация ОТКЛЮЧЕНА (insecure) — "
            "допустимо только для парсинга публичных списков прокси",
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    return ctx
def make_ssl_ctx_no_verify() -> ssl.SSLContext:
    import warnings
    warnings.warn(
        "make_ssl_ctx_no_verify() устарела — используй make_ssl_ctx(verify=False) "
        "и только для публичных списков прокси",
        DeprecationWarning,
        stacklevel=2,
    )
    return make_ssl_ctx(verify=False)
def get_aiohttp_connector():
    import aiohttp
    return aiohttp.TCPConnector(ssl=make_ssl_ctx())
def _build_socks_url_from_cfg() -> str | None:
    try:
        from ..main import _load_raw_config
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
        ssl_ctx = make_ssl_ctx()
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
    ssl_ctx = make_ssl_ctx()
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
        connector = _build_socks_connector(make_ssl_ctx())
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
        ssl_ctx = make_ssl_ctx()
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
    kwargs: dict[str, Any] = dict(token=str(token), default=DefaultBotProperties(parse_mode=pm))
    if session is not None:
        kwargs["session"] = session
    return Bot(**kwargs)

__all__ = [
    "make_ssl_ctx",
    "make_ssl_ctx_no_verify",
    "get_aiohttp_connector",
    "get_socks_proxy_url",
    "get_aiohttp_connector_with_proxy",
    "test_socks_proxy",
    "get_aiogram_session",
    "make_aiogram_bot",
]
