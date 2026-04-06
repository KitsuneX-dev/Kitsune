"""
kitsune/_internal.py — управление процессом Kitsune.

Содержит:
  - die()            — корректное завершение процесса (платформозависимо)
  - restart()        — перезапуск через os.execl
  - fw_protect()     — случайная задержка для защиты от флуда
  - print_banner()   — печать стартового баннера в терминал
  - get_startup_callback() — callback для перезапуска после обновления
  - is_docker()      — определение Docker-окружения
  - is_termux()      — определение Termux-окружения
  - get_platform()   — строка платформы для отображения
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import platform
import random
import signal
import subprocess
import sys
import typing
from pathlib import Path

logger = logging.getLogger(__name__)


# ─── Случайная задержка (защита от FloodWait при массовых запросах) ───────────

async def fw_protect(min_ms: int = 500, max_ms: int = 1500) -> None:
    """Случайная задержка — снижает риск FloodWait при параллельных запросах."""
    await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)


# ─── Определение окружения ────────────────────────────────────────────────────

def is_docker() -> bool:
    """True если запущен внутри Docker-контейнера."""
    return (
        os.path.exists("/.dockerenv")
        or "DOCKER" in os.environ
        or _cgroup_has("docker")
    )


def is_termux() -> bool:
    """True если запущен в Termux (Android)."""
    return (
        "com.termux" in os.environ.get("PREFIX", "")
        or Path("/data/data/com.termux").exists()
    )


def is_heroku() -> bool:
    """True если запущен на Heroku."""
    return "DYNO" in os.environ


def _cgroup_has(keyword: str) -> bool:
    try:
        return keyword in Path("/proc/1/cgroup").read_text(errors="ignore")
    except Exception:
        return False


def get_platform() -> str:
    """Возвращает читаемое название платформы."""
    if is_docker():
        return "Docker"
    if is_termux():
        return "Termux"
    if is_heroku():
        return "Heroku"
    system = platform.system()
    if system == "Linux":
        try:
            import distro  # type: ignore
            name = distro.name(pretty=True)
            if name:
                return name
        except ImportError:
            pass
        return "Linux"
    if system == "Darwin":
        return f"macOS {platform.mac_ver()[0]}"
    if system == "Windows":
        return f"Windows {platform.release()}"
    return system or "Unknown"


def get_python_version() -> str:
    """Возвращает строку версии Python."""
    v = sys.version_info
    return f"{v.major}.{v.minor}.{v.micro}"


# ─── Завершение процесса ──────────────────────────────────────────────────────

def die(code: int = 0) -> typing.NoReturn:
    """
    Платформозависимое завершение процесса.

    На Linux/Docker: завершает всю группу процессов (убивает дочерние).
    На Windows/Termux: sys.exit().
    """
    logger.info("_internal.die: завершение с кодом %d", code)

    if sys.platform != "win32" and not is_termux():
        try:
            pgid = os.getpgid(0)
            os.killpg(pgid, signal.SIGTERM)
        except Exception:
            pass
        # Небольшая пауза — даём процессам обработать SIGTERM
        import time
        time.sleep(0.5)
        try:
            pgid = os.getpgid(0)
            os.killpg(pgid, signal.SIGKILL)
        except Exception:
            pass

    sys.exit(code)


# ─── Перезапуск ───────────────────────────────────────────────────────────────

def restart(*extra_args: str) -> typing.NoReturn:
    """
    Перезапускает Kitsune через os.execl (заменяет текущий процесс).
    extra_args добавляются к аргументам командной строки.
    """
    logger.info("_internal.restart: перезапуск...")

    # Базовая команда: python -m kitsune [оригинальные аргументы] [extra]
    module_path = os.path.relpath(
        os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
    )

    argv = [sys.executable, sys.executable, "-m", module_path]
    argv.extend(a for a in sys.argv[1:] if a not in extra_args)
    argv.extend(extra_args)

    try:
        os.execl(*argv)
    except Exception as exc:
        logger.exception("_internal.restart: os.execl failed: %s", exc)
        # Fallback: subprocess + exit
        subprocess.Popen([sys.executable, "-m", module_path] + list(extra_args))
        sys.exit(0)


def get_startup_callback(*extra_args: str) -> typing.Callable:
    """
    Возвращает callable для использования в atexit или после обновления.

    get_startup_callback()()  →  перезапускает Kitsune
    """
    def _cb(*_: object) -> None:
        restart(*extra_args)
    return _cb


# ─── Баннер ──────────────────────────────────────────────────────────────────

def print_banner(
    name: str,
    uid: int,
    version: str,
    mod_count: int = 0,
    *,
    tty: bool | None = None,
) -> None:
    """Выводит стартовый баннер в терминал."""
    if tty is None:
        tty = sys.stdout.isatty()

    if tty:
        try:
            from colorama import Fore, Style, init as _init
            _init(autoreset=True)
            cyan    = Fore.CYAN
            magenta = Fore.MAGENTA
            green   = Fore.GREEN
            reset   = Style.RESET_ALL
        except ImportError:
            cyan = magenta = green = reset = ""
    else:
        cyan = magenta = green = reset = ""

    line = "━" * 44
    plat = get_platform()
    pyv  = get_python_version()

    print(
        f"\n{magenta}{line}{reset}\n"
        f"  🦊 {cyan}Kitsune Userbot{reset} v{version}\n"
        f"  👤 {name}  (id: {uid})\n"
        f"  📦 Модулей загружено: {green}{mod_count}{reset}\n"
        f"  🖥  {plat}  ·  Python {pyv}\n"
        f"  👨‍💻 Developer: Yushi — @Mikasu32\n"
        f"{magenta}{line}{reset}\n"
    )
