"""
Kitsune Userbot — Main entry point.

Improvements vs Hikka main.py:
- Config via TOML (readable, supports comments) + pydantic validation
- Clean async startup sequence with proper error handling
- Dual-stack: Telethon primary + optional Hydrogram secondary
- No eval() of config keys — explicit typed access
- Environment detection using utils.ENV
- Graceful shutdown on SIGINT/SIGTERM
"""

# © Yushi (@Mikasu32), 2024-2026
# Kitsune Userbot — License: AGPLv3

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR = (
    "/data"
    if "DOCKER" in os.environ
    else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)
BASE_PATH   = Path(BASE_DIR)
CONFIG_PATH = BASE_PATH / "config.toml"
DATA_DIR    = Path.home() / ".kitsune"
DATA_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


# ── Config helpers ────────────────────────────────────────────────────────────

def _load_raw_config() -> dict[str, Any]:
    """Load config.toml; fall back to config.json (migration) or empty dict."""
    if CONFIG_PATH.exists():
        try:
            import toml
            return toml.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("main: failed to parse config.toml")
    # Legacy JSON migration
    legacy = BASE_PATH / "config.json"
    if legacy.exists():
        with contextlib.suppress(Exception):
            data = json.loads(legacy.read_text(encoding="utf-8"))
            logger.info("main: migrating config.json → config.toml")
            _save_config(data)
            return data
    return {}


def _save_config(data: dict[str, Any]) -> None:
    try:
        import toml
        CONFIG_PATH.write_text(toml.dumps(data), encoding="utf-8")
    except Exception:
        logger.exception("main: failed to save config.toml")


def get_config_key(key: str, default: Any = None) -> Any:
    return _load_raw_config().get(key, default)


def set_config_key(key: str, value: Any) -> None:
    data = _load_raw_config()
    data[key] = value
    _save_config(data)


# ── Auth helpers ──────────────────────────────────────────────────────────────

async def _interactive_login(client: Any) -> None:
    """Walk the user through Telethon interactive login."""
    from telethon.errors import (
        ApiIdInvalidError,
        AuthKeyDuplicatedError,
        FloodWaitError,
        PasswordHashInvalidError,
        PhoneNumberInvalidError,
        SessionPasswordNeededError,
    )

    phone = input("📱 Phone number (international format): ").strip()

    try:
        await client.send_code_request(phone)
    except FloodWaitError as exc:
        print(f"⏳ Flood wait: {exc.seconds}s. Please try again later.")
        sys.exit(1)
    except PhoneNumberInvalidError:
        print("❌ Invalid phone number.")
        sys.exit(1)

    code = input("🔑 Telegram code: ").strip()
    try:
        await client.sign_in(phone, code)
    except SessionPasswordNeededError:
        from getpass import getpass
        pwd = getpass("🔐 Two-factor password: ")
        try:
            await client.sign_in(password=pwd)
        except PasswordHashInvalidError:
            print("❌ Wrong password.")
            sys.exit(1)
    except ApiIdInvalidError:
        print("❌ Invalid API ID / API Hash. Check your config.")
        sys.exit(1)
    except AuthKeyDuplicatedError:
        print("❌ Session duplicated. Delete session file and retry.")
        sys.exit(1)


# ── Hydrogram secondary client ────────────────────────────────────────────────

async def _start_hydrogram(api_id: int, api_hash: str, session_name: str) -> Any | None:
    """Optionally start a Hydrogram client for modules that prefer its API."""
    try:
        from hydrogram import Client as HydroClient
        from hydrogram.errors import AuthKeyUnregistered
    except ImportError:
        logger.info("main: hydrogram not installed, skipping secondary client")
        return None

    try:
        hydro = HydroClient(
            name=f"{session_name}_hydro",
            api_id=api_id,
            api_hash=api_hash,
            workdir=str(DATA_DIR),
            no_updates=False,
        )
        await hydro.start()
        logger.info("main: Hydrogram client started")
        return hydro
    except AuthKeyUnregistered:
        logger.warning("main: Hydrogram session invalid, skipping")
        return None
    except Exception:
        logger.exception("main: Hydrogram startup failed, continuing without it")
        return None


# ── Main startup ──────────────────────────────────────────────────────────────

async def _startup(args: argparse.Namespace) -> None:
    from . import log, utils
    from .tl_cache import KitsuneTelegramClient
    from .database import DatabaseManager
    from .core.security import SecurityManager
    from .core.dispatcher import CommandDispatcher
    from .core.loader import Loader
    from .translations import Translator

    log.init()

    # ── Config ────────────────────────────────────────────────────────────────
    cfg = _load_raw_config()
    api_id:   int = int(cfg.get("api_id") or os.environ.get("API_ID", 0))
    api_hash: str = str(cfg.get("api_hash") or os.environ.get("API_HASH", ""))
    prefix:   str = str(cfg.get("prefix", "."))

    # ── Telethon client ───────────────────────────────────────────────────────
    session_path = DATA_DIR / "kitsune"

    # ── Proxy — parsed once, used everywhere (Hikka-style _get_proxy()) ─────
    from telethon.network.connection import (
        ConnectionTcpFull,
        ConnectionTcpMTProxyRandomizedIntermediate,
    )
    proxy_cfg  = cfg.get("proxy") or {}
    proxy      = None
    connection = ConnectionTcpFull
    if proxy_cfg.get("host") and proxy_cfg.get("port"):
        ptype = str(proxy_cfg.get("type", "MTPROTO")).upper()
        if ptype == "MTPROTO":
            secret     = proxy_cfg.get("secret", "00000000000000000000000000000000")
            proxy      = (str(proxy_cfg["host"]), int(proxy_cfg["port"]), secret)
            connection = ConnectionTcpMTProxyRandomizedIntermediate
            logger.info("main: MTProto proxy → %s:%s", proxy_cfg["host"], proxy_cfg["port"])
        else:
            logger.warning("main: non-MTProto proxy in config — ignored (use MTProto)")

    # If api_id/api_hash missing OR session file doesn't exist → run web setup
    session_file = Path(str(session_path) + ".session")
    need_setup = (not api_id or not api_hash or not session_file.exists())

    if need_setup:
        from .web.setup import SetupServer
        web_port = int(cfg.get("web_port", 8080))
        setup = SetupServer(save_config_fn=_save_config, get_config_fn=_load_raw_config)
        await setup.start(host="0.0.0.0", port=web_port)
        await setup.wait_done()
        client = setup.get_client()
        cfg      = _load_raw_config()
        api_id   = int(cfg.get("api_id", 0))
        api_hash = str(cfg.get("api_hash", ""))
        prefix   = str(cfg.get("prefix", "."))
        client.flood_sleep_threshold = 60
        client.system_version = "1.0"
    else:
        extra = {"proxy": proxy, "connection": connection} if proxy else {}

        client = KitsuneTelegramClient(
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
            **extra,
        )

        try:
            await client.connect()
        except (TimeoutError, OSError, ConnectionError) as exc:
            print(
                "\n❌ Не удалось подключиться к Telegram.\n"
                "   Попробуй настроить прокси в config.toml:\n\n"
                "      [proxy]\n"
                "      type = \"SOCKS5\"\n"
                "      host = \"127.0.0.1\"\n"
                "      port = 1080\n\n"
                f"   Детали: {exc}\n"
            )
            sys.exit(1)

        if not await client.is_user_authorized():
            # Session exists but unauthorized — re-run web setup
            logger.info("main: session invalid, launching web setup")
            from .web.setup import SetupServer
            web_port = int(cfg.get("web_port", 8080))
            setup = SetupServer(save_config_fn=_save_config, get_config_fn=_load_raw_config)
            await setup.start(host="0.0.0.0", port=web_port)
            await setup.wait_done()
            client = setup.get_client()

    me = await client.get_me()
    client.tg_id = me.id
    client.tg_me = me
    logger.info("main: logged in as %s (id=%d)", me.first_name, me.id)

    # ── Hydrogram secondary ───────────────────────────────────────────────────
    if not args.no_hydrogram:
        hydro = await _start_hydrogram(api_id, api_hash, str(session_path))
        client.hydrogram = hydro

    # ── Database ──────────────────────────────────────────────────────────────
    db = DatabaseManager(client)
    await db.init()

    # ── Security ──────────────────────────────────────────────────────────────
    security = SecurityManager(client, db)
    await security.init()

    # ── Dispatcher ────────────────────────────────────────────────────────────
    dispatcher = CommandDispatcher(client, db, security, prefix=prefix)
    dispatcher.set_owner(me.id)

    # ── Loader ────────────────────────────────────────────────────────────────
    loader = Loader(client, db, dispatcher)
    client._kitsune_loader = loader
    await loader.load_all_builtin()
    await loader.load_all_user()

    # ── Translator ────────────────────────────────────────────────────────────
    translator = Translator(db)
    lang = db.get("kitsune.core", "lang", "ru")
    translator.set_language(lang)

    # ── Web interface (optional) ───────────────────────────────────────────────
    if not args.no_web:
        try:
            from .web.core import WebCore
            web = WebCore(client, db)
            asyncio.ensure_future(web.start(
                host=cfg.get("web_host", "0.0.0.0"),
                port=int(cfg.get("web_port", 8080)),
            ))
            logger.info("main: web interface starting on port %d", cfg.get("web_port", 8080))
        except ImportError:
            logger.info("main: web dependencies not installed, skipping web UI")
        except Exception:
            logger.exception("main: web startup failed")

    # ── Banner ────────────────────────────────────────────────────────────────
    _print_banner(me)

    # ── Keep alive ────────────────────────────────────────────────────────────
    stop_event = asyncio.Event()

    def _shutdown(*_: object) -> None:
        logger.info("main: received shutdown signal")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(OSError):
            asyncio.get_event_loop().add_signal_handler(sig, _shutdown)

    try:
        await stop_event.wait()
    finally:
        logger.info("main: shutting down…")
        if client.hydrogram:
            with contextlib.suppress(Exception):
                await client.hydrogram.stop()
        await client.disconnect()
        await db.force_save()
        logger.info("main: goodbye 🦊")


def _print_banner(me: Any) -> None:
    from .version import __version_str__
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
    print(
        f"\n{Fore.MAGENTA}{'━' * 42}{Style.RESET_ALL}\n"
        f"  🦊 {Fore.CYAN}Kitsune Userbot{Style.RESET_ALL} v{__version_str__}\n"
        f"  👤 {me.first_name} (id: {me.id})\n"
        f"  👨‍💻 Developer: Yushi — @Mikasu32\n"
        f"{Fore.MAGENTA}{'━' * 42}{Style.RESET_ALL}\n"
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Kitsune Userbot")
    p.add_argument("--no-web",       action="store_true", help="Disable web interface")
    p.add_argument("--no-hydrogram", action="store_true", help="Disable Hydrogram secondary client")
    p.add_argument("--debug",        action="store_true", help="Enable DEBUG logging")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        asyncio.run(_startup(args))
    except KeyboardInterrupt:
        pass
