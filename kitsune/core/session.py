from __future__ import annotations
import asyncio
import contextlib
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def interactive_login(client: Any) -> None:
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


async def hydrogram_web_reauth(
    save_config_fn,
    get_config_fn,
    web_port: int,
) -> bool:
    try:
        from ..web.setup import SetupServer
    except Exception:
        logger.exception("main: web.setup import failed — hydrogram re-auth skipped")
        return False
    setup = SetupServer(
        save_config_fn=save_config_fn,
        get_config_fn=get_config_fn,
        hydrogram_only=True,
    )
    try:
        await setup.start(host="0.0.0.0", port=web_port)
    except Exception:
        logger.exception(
            "main: web setup (hydrogram_only) failed to start on port %d", web_port,
        )
        return False
    print(
        "\n\033[1;33m⚠  Hydrogram-сессия не валидна.\n"
        "   Открой веб-интерфейс выше и пройди повторную регистрацию\n"
        "   только для Hydrogram.\033[0m\n"
    )
    try:
        await setup.wait_done()
    except Exception:
        logger.exception("main: web setup (hydrogram_only) wait_done failed")
        return False
    ok = bool(setup.hydrogram_only_success())
    if ok:
        logger.info(
            "main: Hydrogram повторная регистрация завершена через веб-мастер"
        )
    else:
        logger.warning(
            "main: web setup (hydrogram_only) закрыт, но флаг успеха не выставлен"
        )
    return ok


async def run_web_setup(
    cfg: dict[str, Any],
    save_config_fn,
    get_config_fn,
) -> Any:
    from ..qr_login import ask_login_method, run_console_qr_login
    use_qr = ask_login_method()
    if use_qr:
        session_path = Path.home() / ".kitsune" / "kitsune"
        session_path.parent.mkdir(parents=True, exist_ok=True)
        return await run_console_qr_login(
            cfg, save_config_fn, get_config_fn, session_path,
        )
    from ..web.setup import SetupServer
    web_port = int(cfg.get("web_port", 8080))
    setup = SetupServer(save_config_fn=save_config_fn, get_config_fn=get_config_fn)
    await setup.start(host="0.0.0.0", port=web_port)
    await setup.wait_done()
    return setup.get_client()


async def restore_session(
    cfg: dict[str, Any],
    api_id: int,
    api_hash: str,
    session_path: Path,
    save_config_fn,
    get_config_fn,
) -> Any:
    from ..session_enc import (
        decrypt_session_file,
        _fix_session_permissions,
        _fix_db_readonly,
        _fix_all_permissions,
    )
    from .connection import build_proxy, verify_proxy, build_telethon_client, connect_with_rkn_bypass

    _fix_all_permissions()
    decrypt_session_file()
    session_file = Path(str(session_path) + ".session")
    if session_file.exists():
        _fix_session_permissions()
        _fix_db_readonly()

    need_setup = (not api_id or not api_hash or not session_file.exists())
    if need_setup:
        client = await run_web_setup(cfg, save_config_fn, get_config_fn)
        _fix_session_permissions()
        _fix_db_readonly()
        cfg_new = get_config_fn()
        client.flood_sleep_threshold = 60
        client.system_version = "1.0"
        return client, cfg_new

    proxy, connection = build_proxy(cfg)
    if proxy:
        ok = await verify_proxy(cfg)
        if not ok:
            proxy = None
            connection = None
    client = build_telethon_client(session_path, api_id, api_hash, proxy, connection)
    client = await connect_with_rkn_bypass(
        client, cfg, api_id, api_hash, session_path, save_config_fn,
    )

    session_size = session_file.stat().st_size if session_file.exists() else 0
    if session_size < 100:
        logger.info(
            "main: session file too small (%d bytes), launching web setup",
            session_size,
        )
        client = await run_web_setup(cfg, save_config_fn, get_config_fn)
    else:
        logger.info(
            "main: session file OK (%d bytes), skipping auth check",
            session_size,
        )
    return client, cfg


async def ensure_authorized(
    client: Any,
    cfg: dict[str, Any],
    save_config_fn,
    get_config_fn,
) -> tuple[Any, Any]:
    me = await client.get_me()
    if me is not None:
        return client, me
    logger.warning(
        "main: get_me() returned None — session may be stale, checking authorization…"
    )
    try:
        authorized = await client.is_user_authorized()
    except Exception:
        authorized = False
    if not authorized:
        logger.warning(
            "main: not authorized — re-launching web setup to re-authenticate…"
        )
        with contextlib.suppress(Exception):
            await client.disconnect()
        client = await run_web_setup(cfg, save_config_fn, get_config_fn)
        me = await client.get_me()
    else:
        logger.info(
            "main: authorized but get_me() returned None — retrying after delay…"
        )
        await asyncio.sleep(2)
        me = await client.get_me()
    if me is None:
        raise RuntimeError(
            "main: get_me() returned None after all retries — "
            "delete the session file and re-authenticate."
        )
    return client, me
