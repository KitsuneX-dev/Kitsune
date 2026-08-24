from __future__ import annotations

from .telethon_patch import (
    ensure_python_socks,
    ensure_aiohttp_socks,
    patch_telethon_mtproxy,
    _patch_telethon_mtproxy,
    normalize_secret,
)
from .ssl_ctx import (
    make_ssl_ctx,
    make_ssl_ctx_no_verify,
    get_aiohttp_connector,
    get_socks_proxy_url,
    get_aiohttp_connector_with_proxy,
    test_socks_proxy,
    get_aiogram_session,
    make_aiogram_bot,
    _build_socks_url_from_cfg,
    _get_socks_connector_cls,
    _build_socks_connector,
    _fmt_exc,
)
from .mtproto import (
    get_mtproto_connection_class,
    get_connection_class,
    test_connection,
    mtproxy_handshake_check,
)
from .http_pool import (
    get_shared_session,
    close_shared_session,
)
from .proxy_sources import (
    find_proxy_from_web,
    find_working_proxy,
    apply_bypass_to_config,
    _fetch_from_tg_channel,
    _fetch_from_mtpro_xyz,
    _PUBLIC_PROXIES,
    _TG_PROXY_CHANNELS,
    _MTPRO_XYZ_URL,
    _SECRET_PAT,
    _RE_TG_PROXY,
    _RE_TG_PROXY_ALT,
)

__all__ = [
    "ensure_python_socks",
    "ensure_aiohttp_socks",
    "patch_telethon_mtproxy",
    "normalize_secret",
    "make_ssl_ctx",
    "make_ssl_ctx_no_verify",
    "get_aiohttp_connector",
    "get_socks_proxy_url",
    "get_aiohttp_connector_with_proxy",
    "test_socks_proxy",
    "get_aiogram_session",
    "make_aiogram_bot",
    "get_mtproto_connection_class",
    "get_connection_class",
    "test_connection",
    "mtproxy_handshake_check",
    "find_proxy_from_web",
    "find_working_proxy",
    "apply_bypass_to_config",
    "get_shared_session",
    "close_shared_session",
]
