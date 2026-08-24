from __future__ import annotations
import logging
import re

from .ssl_ctx import make_ssl_ctx
from .mtproto import mtproxy_handshake_check, test_connection

logger = logging.getLogger(__name__)

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

async def _fetch_from_tg_channel(url: str) -> list[tuple[str, int, str]]:
    try:
        import aiohttp
        ssl_ctx = make_ssl_ctx(verify=False)
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
        ssl_ctx = make_ssl_ctx(verify=False)
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

__all__ = [
    "find_proxy_from_web",
    "find_working_proxy",
    "apply_bypass_to_config",
]
