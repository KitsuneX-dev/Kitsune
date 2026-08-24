from __future__ import annotations
import logging
import sys

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
    if getattr(target_cls.readexactly, "_kitsune_size_guard", False):  # type: ignore[attr-defined]
        return
    original = target_cls.readexactly  # type: ignore[attr-defined]
    async def readexactly_safe(self, n):
        if n is None or n < 0:
            raise ConnectionError(
                f"MTProxy: получен невалидный размер пакета ({n!r}). "
                "Прокси, вероятно, мёртв или не поддерживает FakeTLS — обрываю."
            )
        if n == 0:
            return b""
        return await original(self, n)
    readexactly_safe._kitsune_size_guard = True  # type: ignore[attr-defined]
    target_cls.readexactly = readexactly_safe  # type: ignore[attr-defined]
    logger.info(
        "rkn_bypass: fallback MTProxy patch applied (class=%s)",
        target_cls.__name__,
    )

patch_telethon_mtproxy = _patch_telethon_mtproxy

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

__all__ = [
    "ensure_python_socks",
    "ensure_aiohttp_socks",
    "patch_telethon_mtproxy",
    "normalize_secret",
]
