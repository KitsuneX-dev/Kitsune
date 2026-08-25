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

DB_OWNER_LOADER: str = "kitsune.loader"

async def fw_protect(min_ms: int = 500, max_ms: int = 1500) -> None:
    await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)
def is_docker() -> bool:
    return (
        os.path.exists("/.dockerenv")
        or "DOCKER" in os.environ
        or _cgroup_has("docker")
    )
def is_termux() -> bool:
    return (
        "com.termux" in os.environ.get("PREFIX", "")
        or Path("/data/data/com.termux").exists()
    )
def is_heroku() -> bool:
    return "DYNO" in os.environ
def _cgroup_has(keyword: str) -> bool:
    try:
        return keyword in Path("/proc/1/cgroup").read_text(errors="ignore")
    except Exception:
        return False
def get_platform() -> str:
    if is_docker():
        return "Docker"
    if is_termux():
        return "Termux"
    if is_heroku():
        return "Heroku"
    system = platform.system()
    if system == "Linux":
        try:
            import distro
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
    v = sys.version_info
    return f"{v.major}.{v.minor}.{v.micro}"
def die(code: int = 0) -> typing.NoReturn:
    logger.info("_internal.die: завершение с кодом %d", code)
    if sys.platform != "win32" and not is_termux():
        try:
            pgid = os.getpgid(0)
            os.killpg(pgid, signal.SIGTERM)
        except Exception:
            pass
        import time
        time.sleep(0.5)
        try:
            pgid = os.getpgid(0)
            os.killpg(pgid, signal.SIGKILL)
        except Exception:
            pass
    sys.exit(code)
_RESTART_DONE = False
_RESTART_REQUESTED: bool = False
_RESTART_INITIATOR: asyncio.Task | None = None


def restart_requested() -> bool:
    return _RESTART_REQUESTED


def mark_restart_requested() -> None:
    global _RESTART_REQUESTED
    _RESTART_REQUESTED = True


def restart_initiator() -> asyncio.Task | None:
    return _RESTART_INITIATOR


def package_name() -> str:
    name = (__package__ or "").split(".")[0]
    if not name:
        name = Path(__file__).resolve().parent.name
    return name


def package_parent() -> str:
    return str(Path(__file__).resolve().parent.parent)


def build_restart_command(
    *extra_args: str,
    python: str | None = None,
) -> tuple[list[str], dict[str, str], str]:
    parent = package_parent()
    argv = [python or sys.executable, "-m", package_name()]
    argv.extend(a for a in sys.argv[1:] if a not in extra_args)
    argv.extend(extra_args)
    env = dict(os.environ)
    old_pp = env.get("PYTHONPATH", "")
    parts = [p for p in old_pp.split(os.pathsep) if p]
    if parent not in parts:
        parts.insert(0, parent)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return argv, env, parent


def exec_restart(*extra_args: str, python: str | None = None) -> typing.NoReturn:
    argv, env, parent = build_restart_command(*extra_args, python=python)
    logger.info("_internal.exec_restart: %s (cwd=%s)", " ".join(argv), parent)
    try:
        os.chdir(parent)
    except Exception:
        logger.debug("_internal.exec_restart: chdir failed", exc_info=True)
    try:
        os.execve(argv[0], argv, env)
    except Exception as exc:
        logger.exception("_internal.exec_restart: os.execve failed: %s", exc)
        try:
            subprocess.Popen(argv, env=env, cwd=parent, start_new_session=True)
        except Exception:
            logger.exception("_internal.exec_restart: fallback spawn failed")
        os._exit(0)


async def graceful_restart(
    client: typing.Any = None,
    db: typing.Any = None,
    *,
    web: typing.Any = None,
    accounts: typing.Any = None,
    extra_tasks: typing.Iterable[asyncio.Task] | None = None,
    timeout: float = 45.0,
) -> None:
    global _RESTART_DONE, _RESTART_REQUESTED, _RESTART_INITIATOR
    if _RESTART_DONE:
        logger.debug("graceful_restart: завершение уже выполнено, пропускаю")
        return
    _RESTART_DONE = True
    _RESTART_REQUESTED = True
    try:
        _RESTART_INITIATOR = asyncio.current_task()
    except RuntimeError:
        _RESTART_INITIATOR = None

    if db is None and client is not None:
        db = getattr(client, "_kitsune_db", None)
    if web is None and client is not None:
        web = getattr(client, "_kitsune_web", None)
    if accounts is None and client is not None:
        accounts = getattr(client, "_kitsune_accounts", None)

    logger.info("graceful_restart: корректное завершение перед перезапуском...")

    if db is not None and hasattr(db, "force_save"):
        try:
            await asyncio.wait_for(db.force_save(), timeout=10.0)
        except Exception:
            logger.exception("graceful_restart: force_save не удался")

    if web is not None:
        try:
            await asyncio.wait_for(web.stop(), timeout=10.0)
            logger.debug("graceful_restart: веб-сервер остановлен")
        except Exception:
            logger.exception("graceful_restart: остановка веб-сервера не удалась")

    if accounts is not None and client is not None:
        if getattr(client, "_kitsune_accounts", None) is None:
            try:
                client._kitsune_accounts = accounts
            except Exception:
                logger.debug("graceful_restart: не удалось привязать менеджер твинков")

    if client is not None:
        try:
            from .core.lifecycle import shutdown as _lifecycle_shutdown
            await asyncio.wait_for(_lifecycle_shutdown(client, db), timeout=timeout)
        except Exception:
            logger.exception("graceful_restart: lifecycle.shutdown не завершился штатно")
    else:
        if accounts is not None:
            try:
                await asyncio.wait_for(accounts.shutdown_all(), timeout=25.0)
            except Exception:
                logger.exception("graceful_restart: остановка твинков не удалась")
        try:
            from .core.lifecycle import _cancel_background_tasks
            await _cancel_background_tasks()
        except Exception:
            logger.exception("graceful_restart: отмена фоновых задач не удалась")

    if extra_tasks:
        pending = [t for t in extra_tasks if t is not None and not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True), timeout=5.0
                )
            except Exception:
                logger.debug("graceful_restart: часть задач не отменилась в срок")

    logger.info("graceful_restart: завершение выполнено, можно замещать процесс")


def _graceful_restart_blocking(
    client: typing.Any = None,
    db: typing.Any = None,
    **kwargs: typing.Any,
) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(graceful_restart(client, db, **kwargs))
        except Exception:
            logger.exception("_internal.restart: корректное завершение не удалось")
        return
    if not _RESTART_DONE:
        logger.warning(
            "_internal.restart: вызван из работающего event loop — "
            "перед вызовом ожидается await graceful_restart()"
        )


def restart(
    *extra_args: str,
    client: typing.Any = None,
    db: typing.Any = None,
    **shutdown_kwargs: typing.Any,
) -> typing.NoReturn:
    logger.info("_internal.restart: перезапуск...")
    _graceful_restart_blocking(client, db, **shutdown_kwargs)
    exec_restart(*extra_args)
def get_startup_callback(*extra_args: str) -> typing.Callable:
    def _cb(*_: object) -> None:
        restart(*extra_args)
    return _cb
def print_banner(
    name: str,
    uid: int,
    version: str,
    mod_count: int = 0,
    *,
    tty: bool | None = None,
) -> None:
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
