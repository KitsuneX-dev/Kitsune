from __future__ import annotations
import asyncio
import contextlib
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = Path.home() / ".kitsune"

_HYDRO_LOCK_FILE = DATA_DIR / ".hydrogram.lock"
_hydro_lock_fd: int | None = None

_HYDRO_MIN_SESSION_BYTES = 4096


def _acquire_hydro_lock() -> bool:
    global _hydro_lock_fd
    try:
        import fcntl
    except ImportError:
        return True
    try:
        fd = os.open(str(_HYDRO_LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        _hydro_lock_fd = fd
        return True
    except Exception:
        return True


def _release_hydro_lock() -> None:
    global _hydro_lock_fd
    if _hydro_lock_fd is None:
        return
    try:
        import fcntl
        fcntl.flock(_hydro_lock_fd, fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        os.close(_hydro_lock_fd)
    except Exception:
        pass
    _hydro_lock_fd = None
    with contextlib.suppress(Exception):
        _HYDRO_LOCK_FILE.unlink(missing_ok=True)


def _purge_bad_hydro_session(session_file: Path, reason: str) -> None:
    try:
        for suffix in ("", "-journal", ".wal", ".shm"):
            p = Path(str(session_file) + suffix)
            with contextlib.suppress(Exception):
                if p.exists():
                    p.unlink()
        logger.info(
            "main: удалил битую Hydrogram-сессию %s (причина: %s)",
            session_file.name, reason,
        )
    except Exception:
        logger.debug("main: _purge_bad_hydro_session failed", exc_info=True)


def build_proxy(cfg: dict[str, Any]) -> tuple[Any, Any]:
    from telethon.network.connection import ConnectionTcpFull
    from ..rkn_bypass import ensure_python_socks as _ensure_python_socks

    proxy_cfg = cfg.get("proxy") or {}
    proxy = None
    connection = ConnectionTcpFull
    if not (isinstance(proxy_cfg, dict) and proxy_cfg.get("host") and proxy_cfg.get("port")):
        return proxy, connection
    ptype = str(proxy_cfg.get("type", "MTPROTO")).upper()
    host = str(proxy_cfg["host"])
    port = int(proxy_cfg["port"])
    if not _ensure_python_socks():
        logger.error(
            "main: python-socks недоступен — прокси %s://%s:%d будет пропущен.",
            ptype, host, port,
        )
        return proxy, connection
    if ptype == "MTPROTO":
        secret = proxy_cfg.get("secret", "00000000000000000000000000000000")
        from ..rkn_bypass import get_mtproto_connection_class, normalize_secret
        secret = normalize_secret(str(secret))
        proxy = (host, port, secret)
        connection = get_mtproto_connection_class(secret)
        logger.info("main: MTProto proxy → %s:%s (%s)", host, port, connection.__name__)
        return proxy, connection
    if ptype in ("SOCKS5", "SOCKS4", "HTTP", "HTTPS"):
        try:
            import socks as _socks
            _type_map = {
                "SOCKS5": _socks.SOCKS5,
                "SOCKS4": _socks.SOCKS4,
                "HTTP": _socks.HTTP,
                "HTTPS": _socks.HTTP,
            }
            proxy = (
                _type_map.get(ptype, _socks.SOCKS5),
                host, port, True,
                proxy_cfg.get("username") or None,
                proxy_cfg.get("password") or None,
            )
            logger.info("main: %s proxy → %s:%s", ptype, host, port)
        except ImportError:
            logger.warning(
                "main: PySocks не установлен (pip install PySocks) — SOCKS-прокси отключён"
            )
        return proxy, connection
    logger.warning("main: неизвестный тип прокси '%s' — игнорирую", ptype)
    return proxy, connection


async def verify_proxy(cfg: dict[str, Any]) -> bool:
    proxy_cfg = cfg.get("proxy") or {}
    if not (isinstance(proxy_cfg, dict) and proxy_cfg.get("host") and proxy_cfg.get("port")):
        return True
    from ..rkn_bypass import (
        test_connection as _proxy_tcp_check,
        mtproxy_handshake_check as _proxy_hs_check,
    )
    _phost = proxy_cfg.get("host")
    _pport = int(proxy_cfg.get("port") or 443)
    _psecret = str(proxy_cfg.get("secret") or "")
    logger.info(
        "main: проверяю прокси %s:%d (TCP+MTProto handshake параллельно)…",
        _phost, _pport,
    )
    _tcp_task = asyncio.create_task(
        _proxy_tcp_check(_phost, _pport, timeout=3.0),
        name="proxy-tcp-check",
    )
    _hs_task = asyncio.create_task(
        _proxy_hs_check(_phost, _pport, _psecret, timeout=5.0),
        name="proxy-hs-check",
    )
    _hs_ok = False
    _tcp_alive = False
    try:
        await asyncio.wait(
            {_tcp_task, _hs_task},
            timeout=5.0,
            return_when=asyncio.ALL_COMPLETED,
        )
    except Exception:
        logger.debug("main: proxy checks: asyncio.wait failed", exc_info=True)
    if _hs_task.done() and not _hs_task.cancelled():
        try:
            _hs_ok = bool(_hs_task.result())
        except Exception:
            _hs_ok = False
    if _tcp_task.done() and not _tcp_task.cancelled():
        try:
            _tcp_alive = bool(_tcp_task.result())
        except Exception:
            _tcp_alive = False
    for _t in (_tcp_task, _hs_task):
        if not _t.done():
            _t.cancel()
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await _t
    if _hs_ok:
        logger.info(
            "main: handshake OK — поднимаю основное соединение через %s:%d",
            _phost, _pport,
        )
        return True
    if _tcp_alive:
        logger.warning(
            "main: прокси %s:%d отвечает на TCP, но MTProto handshake провален. Иду на fallback.",
            _phost, _pport,
        )
        return False
    logger.warning(
        "main: прокси %s:%d не прошёл проверки (TCP/handshake) за 5s — пропускаю и иду на fallback",
        _phost, _pport,
    )
    return False


async def connect_with_rkn_bypass(
    client: Any,
    cfg: dict[str, Any],
    api_id: int,
    api_hash: str,
    session_path: Path,
    save_config_fn,
) -> Any:
    from ..tl_cache import KitsuneTelegramClient
    from ..rkn_bypass import (
        ensure_python_socks as _ensure_python_socks,
        find_working_proxy,
        get_mtproto_connection_class,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=30.0)
        logger.info("main: client.connect() OK")
        return client
    except (TimeoutError, OSError, ConnectionError, asyncio.TimeoutError) as exc:
        logger.warning(
            "main: connection failed (%s: %s), trying RKN bypass…",
            type(exc).__name__, exc,
        )
        with contextlib.suppress(Exception):
            await client.disconnect()
        if not _ensure_python_socks():
            print(
                "\n❌ Не удалось подключиться к Telegram, а RKNBypass требует python-socks.\n"
                "   Установи вручную: pip install 'python-socks[asyncio]'\n"
            )
            sys.exit(1)
        try:
            proxy_info = await find_working_proxy(deep_check=True)
        except Exception as _exc:
            logger.exception("main: find_working_proxy() failed: %s", _exc)
            proxy_info = None
        if not proxy_info:
            print(
                "\n❌ Не удалось подключиться к Telegram.\n"
                "   Текущий прокси из config.toml не отвечает на MTProto handshake,\n"
                "   а публичные fallback-прокси тоже не сработали.\n\n"
                "   Попробуй настроить прокси вручную в config.toml:\n\n"
                "      [proxy]\n"
                "      type = \"MTPROTO\"\n"
                "      host = \"149.154.175.100\"\n"
                "      port = 443\n"
                "      secret = \"ee9000000000000000000000000000003900000000000000\"\n\n"
                "   Или возьми свежий прокси из @MTProxyT / @proxyme и подставь его:\n"
                "      .setproxy <host> <port> <secret>\n\n"
                f"   Детали: {exc}\n"
            )
            sys.exit(1)
        host, port, secret = proxy_info
        logger.info("main: using MTProto proxy %s:%d for RKN bypass", host, port)
        conn_cls = get_mtproto_connection_class(secret)
        new_client = KitsuneTelegramClient(
            str(session_path),
            api_id=api_id,
            api_hash=api_hash,
            connection_retries=10,
            retry_delay=3,
            auto_reconnect=True,
            flood_sleep_threshold=60,
            device_model="Kitsune Userbot",
            system_version="1.0",
            app_version="1.0.0",
            lang_code="ru",
            proxy=(host, port, secret),
            connection=conn_cls,
        )
        try:
            cfg["proxy"] = {
                "type": "MTPROTO",
                "host": host,
                "port": int(port),
                "secret": secret,
            }
            save_config_fn(cfg)
            logger.info("main: рабочий MTProto-прокси сохранён в config.toml")
        except Exception:
            logger.exception("main: не удалось сохранить прокси в config.toml")
        try:
            await asyncio.wait_for(new_client.connect(), timeout=30.0)
            logger.info("main: RKN-bypass client.connect() OK")
        except (TimeoutError, OSError, ConnectionError, asyncio.TimeoutError) as exc2:
            logger.error(
                "main: RKN-bypass прокси %s:%d тоже не отвечает (%s)",
                host, port, exc2,
            )
            print(
                "\n❌ Найденный RKN-bypass прокси оказался нерабочим.\n"
                "   Попробуй .findproxy после старта или укажи прокси вручную.\n"
            )
            sys.exit(1)
        return new_client


def build_telethon_client(
    session_path: Path,
    api_id: int,
    api_hash: str,
    proxy: Any,
    connection: Any,
) -> Any:
    from ..tl_cache import KitsuneTelegramClient
    extra = {"proxy": proxy, "connection": connection} if proxy else {}
    return KitsuneTelegramClient(
        str(session_path),
        api_id=api_id,
        api_hash=api_hash,
        connection_retries=3,
        retry_delay=2,
        auto_reconnect=True,
        flood_sleep_threshold=60,
        device_model="Kitsune Userbot",
        system_version="1.0",
        app_version="1.0.0",
        lang_code="ru",
        **extra,
    )


async def start_hydrogram(
    api_id: int,
    api_hash: str,
    session_name: str,
    load_config_fn,
    save_config_fn,
) -> Any | None:
    hydro_session_file = DATA_DIR / f"{Path(session_name).name}_hydro.session"
    if not hydro_session_file.exists():
        logger.info(
            "main: Hydrogram session file отсутствует (%s) — "
            "вторичный клиент не запускается (это не ошибка).",
            hydro_session_file,
        )
        try:
            from .reliability import flags as _deg_flags
            _deg_flags.mark_hydrogram_failed("session file missing")
        except Exception:
            pass
        return None
    try:
        _hsize = hydro_session_file.stat().st_size
    except OSError:
        _hsize = 0
    if _hsize < _HYDRO_MIN_SESSION_BYTES:
        _purge_bad_hydro_session(
            hydro_session_file,
            reason=f"файл слишком мал ({_hsize}b < {_HYDRO_MIN_SESSION_BYTES}b)",
        )
        logger.info(
            "main: Hydrogram пропущен — сессия была недоавторизована и удалена",
        )
        try:
            from .reliability import flags as _deg_flags
            _deg_flags.mark_hydrogram_failed("session was a stub")
        except Exception:
            pass
        return None
    if not _acquire_hydro_lock():
        logger.warning(
            "main: another Kitsune instance already holds Hydrogram lock — skipping to avoid session-id war"
        )
        try:
            from .reliability import flags as _deg_flags
            _deg_flags.mark_hydrogram_failed("another instance holds the session lock")
        except Exception:
            pass
        return None
    try:
        from hydrogram import Client as HydroClient
        from hydrogram.errors import AuthKeyUnregistered
    except ImportError:
        logger.info("main: hydrogram not installed, skipping secondary client")
        try:
            from .reliability import flags as _deg_flags
            _deg_flags.mark_hydrogram_failed("hydrogram package not installed")
        except Exception:
            pass
        _release_hydro_lock()
        return None
    hydro = None
    try:
        kwargs: dict = dict(
            name=str(DATA_DIR / f"{Path(session_name).name}_hydro"),
            api_id=api_id,
            api_hash=api_hash,
            workdir=str(DATA_DIR),
            no_updates=True,
            takeout=False,
        )
        try:
            import inspect
            sig = inspect.signature(HydroClient.__init__)
            if "sleep_threshold" in sig.parameters:
                kwargs["sleep_threshold"] = 60
            if "max_concurrent_transmissions" in sig.parameters:
                kwargs["max_concurrent_transmissions"] = 1
            if "device_model" in sig.parameters:
                kwargs["device_model"] = "Kitsune Userbot (media)"
            if "app_version" in sig.parameters:
                kwargs["app_version"] = "1.0.0"
            if "system_version" in sig.parameters:
                kwargs["system_version"] = "1.0"
            if "lang_code" in sig.parameters:
                kwargs["lang_code"] = "ru"
        except Exception:
            pass
        hydro = HydroClient(**kwargs)
        try:
            await asyncio.wait_for(hydro.start(), timeout=45.0)
        except asyncio.TimeoutError:
            logger.warning("main: Hydrogram start() timed out after 45s, skipping")
            with contextlib.suppress(Exception):
                await hydro.stop()
            try:
                from .reliability import flags as _deg_flags
                _deg_flags.mark_hydrogram_failed("startup timeout")
            except Exception:
                pass
            _release_hydro_lock()
            return None
        logger.info("main: Hydrogram client started (no_updates=True, lock acquired)")
        try:
            from .reliability import flags as _deg_flags
            _deg_flags.clear_hydrogram_failed()
        except Exception:
            pass
        return hydro
    except AuthKeyUnregistered:
        with contextlib.suppress(Exception):
            if hydro_session_file.exists():
                _purge_bad_hydro_session(
                    hydro_session_file, reason="AuthKeyUnregistered",
                )
        logger.info(
            "main: Hydrogram-сессия была инвалидной (AuthKeyUnregistered) — "
            "удалил файл, запускаю веб-мастер для повторной регистрации",
        )
        try:
            from .reliability import flags as _deg_flags
            _deg_flags.mark_hydrogram_failed("AuthKeyUnregistered")
        except Exception:
            pass
        if hydro is not None:
            with contextlib.suppress(Exception):
                await hydro.stop()
        _release_hydro_lock()
        try:
            cfg_now = load_config_fn()
            web_port = int(cfg_now.get("web_port", 8080))
        except Exception:
            web_port = 8080
        from .session import hydrogram_web_reauth
        try:
            reauth_ok = await hydrogram_web_reauth(
                save_config_fn=save_config_fn,
                get_config_fn=load_config_fn,
                web_port=web_port,
            )
        except Exception:
            logger.exception(
                "main: ошибка во время веб-регистрации Hydrogram — продолжаю без вторичного клиента",
            )
            reauth_ok = False
        if not reauth_ok:
            logger.info(
                "main: повторная регистрация Hydrogram не завершена — продолжаю без вторичного клиента",
            )
            return None
        try:
            from .reliability import flags as _deg_flags
            _deg_flags.clear_hydrogram_failed()
        except Exception:
            pass
        return await start_hydrogram(api_id, api_hash, session_name, load_config_fn, save_config_fn)
    except Exception as _exc:
        logger.exception("main: Hydrogram startup failed, continuing without it")
        try:
            from .reliability import flags as _deg_flags
            _deg_flags.mark_hydrogram_failed(f"startup: {type(_exc).__name__}")
        except Exception:
            pass
        _release_hydro_lock()
        return None


async def safe_force_reconnect(client: Any) -> bool:
    sender = getattr(client, "_sender", None)
    if sender is not None:
        for attr in ("_send_loop_handle", "_recv_loop_handle"):
            handle = getattr(sender, attr, None)
            if handle is None or handle.done():
                continue
            with contextlib.suppress(Exception):
                handle.cancel()
        for attr in ("_send_loop_handle", "_recv_loop_handle"):
            handle = getattr(sender, attr, None)
            if handle is None:
                continue
            with contextlib.suppress(Exception, asyncio.CancelledError, RuntimeError):
                await asyncio.wait_for(asyncio.shield(handle), timeout=2.0)
    with contextlib.suppress(Exception, RuntimeError):
        await client.disconnect()
    disc = getattr(sender, "_disconnected", None) if sender is not None else None
    if disc is not None:
        with contextlib.suppress(Exception, asyncio.CancelledError, RuntimeError):
            await asyncio.wait_for(asyncio.shield(disc), timeout=3.0)
    await asyncio.sleep(0.2)
    try:
        from .reliability import retry_with_backoff, RetryPolicy, flags as _deg_flags
    except Exception:
        try:
            await asyncio.wait_for(client.connect(), timeout=30.0)
            return True
        except Exception as exc:
            logger.debug(
                "keepalive: forced reconnect failed (%s: %s)",
                type(exc).__name__, exc,
            )
            return False
    _deg_flags.mark_vpn_down("keepalive: hard reconnect cycle")

    async def _do_connect() -> bool:
        await asyncio.wait_for(client.connect(), timeout=30.0)
        return True

    try:
        await retry_with_backoff(
            _do_connect,
            policy=RetryPolicy(
                base_delay=1.0,
                max_delay=16.0,
                multiplier=2.0,
                jitter=0.25,
                max_attempts=5,
            ),
            name="telegram_reconnect",
            expected_exceptions=(
                TimeoutError, asyncio.TimeoutError,
                ConnectionError, OSError,
            ),
        )
        _deg_flags.clear_vpn_down()
        return True
    except Exception as exc:
        logger.debug(
            "keepalive: forced reconnect failed after retries (%s: %s)",
            type(exc).__name__, exc,
        )
        return False


def is_link_alive(client: Any) -> bool:
    try:
        if not client.is_connected():
            return False
    except Exception:
        return False
    sender = getattr(client, "_sender", None)
    if sender is None:
        return False
    conn = getattr(sender, "_connection", None)
    if conn is None:
        return False
    disc = getattr(sender, "_disconnected", None)
    if disc is not None:
        try:
            if disc.done():
                return False
        except Exception:
            pass
    return True


async def keepalive(client: Any) -> None:
    HARD_RECONNECT_AFTER_S = 300
    PING_INTERVAL_S = 60
    fail_streak_started: float | None = None
    attempts: int = 0
    try:
        from .reliability import flags as _deg_flags
    except Exception:
        _deg_flags = None
    while True:
        try:
            await asyncio.sleep(PING_INTERVAL_S)
        except asyncio.CancelledError:
            break
        try:
            if not is_link_alive(client):
                raise ConnectionError("client disconnected")
            if fail_streak_started is not None:
                logger.info(
                    "keepalive: соединение восстановлено (после %d попыт(ок))",
                    attempts,
                )
                if _deg_flags is not None:
                    try:
                        _deg_flags.clear_vpn_down()
                    except Exception:
                        pass
            fail_streak_started = None
            attempts = 0
        except asyncio.CancelledError:
            break
        except Exception as exc:
            import time as _time
            now = _time.monotonic()
            if fail_streak_started is None:
                fail_streak_started = now
            attempts += 1
            elapsed = now - fail_streak_started
            logger.debug(
                "keepalive: link down (%s: %s) — попытка %d, серия %.0fs",
                type(exc).__name__, exc, attempts, elapsed,
            )
            if elapsed < HARD_RECONNECT_AFTER_S:
                continue
            logger.warning(
                "keepalive: %d неудачных проверок за ~%.0fs — жёсткий reconnect",
                attempts, elapsed,
            )
            ok = await safe_force_reconnect(client)
            if ok:
                logger.info(
                    "keepalive: hard reconnect успешен (после %d попыт(ок))",
                    attempts,
                )
                fail_streak_started = None
                attempts = 0
            else:
                fail_streak_started = now
