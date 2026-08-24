from __future__ import annotations

import asyncio
import importlib
import logging
import os
import shlex
import shutil
import sys

logger = logging.getLogger(__name__)

_PIP_INSTALL_TIMEOUT: float = 300.0
_PIP_STDERR_TAIL: int = 200
_LAST_PIP_STDERR: dict[str, str] = {}


_INTERNAL_PACKAGE_NAMES = frozenset(
    {
        "kitsune", "loader", "utils",
        "hikka", "hikkatl", "hikkamods",
        "heroku", "herokutl", "hikkapyro",
    }
)


def _extract_missing_package(exc: ImportError) -> str | None:
    name = getattr(exc, "name", None)
    if name:
        top = name.split(".")[0]
        if top in _INTERNAL_PACKAGE_NAMES:
            logger.warning(
                "Loader: refusing pip auto-install of internal/foreign "
                "package %r (likely a module for another userbot API)", top,
            )
            return None
        return top
    msg = str(exc)
    import re
    m = re.search(r"No module named ['\"]([a-zA-Z0-9_\-\.]+)['\"]", msg)
    if m:
        top = m.group(1).split(".")[0]
        if top in _INTERNAL_PACKAGE_NAMES:
            logger.warning(
                "Loader: refusing pip auto-install of internal/foreign "
                "package %r (likely a module for another userbot API)", top,
            )
            return None
        return top
    return None
_IMPORT_TO_PIP: dict[str, str] = {
    "PIL": "Pillow",
    "matplotlib": "matplotlib",
    "numpy": "numpy",
    "spotipy": "spotipy",
    "mutagen": "mutagen",
    "pydub": "pydub",
    "qrcode": "qrcode",
    "aiofiles": "aiofiles",
    "fake_useragent": "fake-useragent",
    "cv2": "opencv-python",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "Crypto": "pycryptodome",
    "nacl": "PyNaCl",
    "attr": "attrs",
    "magic": "python-magic",
    "usb": "pyusb",
    "serial": "pyserial",
    "google": "google-genai",
}

async def _run_cmd(args: list[str], timeout: float | None = None) -> tuple[bool, str]:
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        if timeout is not None:
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                return False, f"command timed out after {timeout:.0f}s"
        else:
            _, stderr = await proc.communicate()
        return proc.returncode == 0, stderr.decode(errors="replace")
    except FileNotFoundError:
        return False, "command not found"
    except Exception as exc:
        return False, str(exc)

def _is_permission_error(stderr: str) -> bool:
    _permission_markers = (
        "permission denied",
        "could not open lock file",
        "are you root",
        "operation not permitted",
        "eacces",
        "eperm",
    )
    low = stderr.lower()
    return any(m in low for m in _permission_markers)

def _build_pip_base_cmd() -> list[str]:
    override = os.environ.get("KITSUNE_PIP_CMD", "").strip()
    if override:
        try:
            parts = shlex.split(override)
        except ValueError:
            parts = []
        if parts:
            return parts
    return [sys.executable, "-m", "pip"]

def _record_pip_stderr(package: str, pip_name: str, stderr: str) -> None:
    tail = (stderr or "").strip()
    if len(tail) > _PIP_STDERR_TAIL:
        tail = tail[-_PIP_STDERR_TAIL:]
    _LAST_PIP_STDERR[package] = tail
    if pip_name != package:
        _LAST_PIP_STDERR[pip_name] = tail

def get_last_pip_stderr(package: str) -> str:
    return _LAST_PIP_STDERR.get(package, "")

async def _pip_install(package: str) -> bool:
    pip_name = _IMPORT_TO_PIP.get(package, package)
    is_termux = "com.termux" in os.environ.get("PREFIX", "") or os.path.isdir("/data/data/com.termux")
    _NAMESPACE_PKGS = {"google-genai", "google-generativeai", "google-cloud-storage", "google-auth"}
    base = _build_pip_base_cmd()
    args = base + ["install", pip_name, "--quiet", "--no-warn-script-location"]
    if pip_name in _NAMESPACE_PKGS:
        args.append("--upgrade")
    if is_termux:
        args += ["--prefer-binary", "--no-build-isolation"]

    ok, stderr = await _run_cmd(args, timeout=_PIP_INSTALL_TIMEOUT)
    if ok:
        logger.info("Loader: pip installed %r successfully", pip_name)
        _LAST_PIP_STDERR.pop(package, None)
        _LAST_PIP_STDERR.pop(pip_name, None)
        importlib.invalidate_caches()
        return True

    if _is_permission_error(stderr):
        logger.info("Loader: pip install %r failed with permission error, retrying with sudo", pip_name)
        ok, stderr = await _run_cmd(["sudo"] + args, timeout=_PIP_INSTALL_TIMEOUT)
        if ok:
            logger.info("Loader: pip installed %r successfully (sudo)", pip_name)
            _LAST_PIP_STDERR.pop(package, None)
            _LAST_PIP_STDERR.pop(pip_name, None)
            importlib.invalidate_caches()
            return True
        logger.warning("Loader: pip install %r failed even with sudo: %s", pip_name, stderr[:300])
    else:
        logger.warning("Loader: pip install %r failed: %s", pip_name, stderr[:300])

    _record_pip_stderr(package, pip_name, stderr)
    return False

_SYSTEM_UTIL_TO_PKG: dict[str, dict[str, str]] = {
    "ffmpeg":    {"apt": "ffmpeg",       "termux": "ffmpeg"},
    "ffprobe":   {"apt": "ffmpeg",       "termux": "ffmpeg"},
    "convert":   {"apt": "imagemagick",  "termux": "imagemagick"},
    "wget":      {"apt": "wget",         "termux": "wget"},
    "curl":      {"apt": "curl",         "termux": "curl"},
    "yt-dlp":    {"apt": "yt-dlp",       "termux": "yt-dlp"},
    "gallery-dl":{"apt": "gallery-dl",   "termux": "gallery-dl"},
}

def _is_termux() -> bool:
    import os as _os
    return "com.termux" in _os.environ.get("PREFIX", "") or _os.path.isdir("/data/data/com.termux")

async def _system_install(utility: str) -> bool:
    pkg_map = _SYSTEM_UTIL_TO_PKG.get(utility)
    if not pkg_map:
        logger.warning("Loader: no system package known for utility %r", utility)
        return False

    if _is_termux():

        cmd = ["termux-pkg", "install", "-y", pkg_map["termux"]]
        ok, stderr = await _run_cmd(cmd)
        if ok:
            logger.info("Loader: system package for %r installed (termux)", utility)
            return True
        logger.warning("Loader: termux-pkg install %r failed: %s", utility, stderr[:200])
        return False

    cmd = ["apt-get", "install", "-y", "--no-install-recommends", pkg_map["apt"]]
    ok, stderr = await _run_cmd(cmd)
    if ok:
        logger.info("Loader: system package for %r installed successfully", utility)
        return True

    if _is_permission_error(stderr):
        logger.info(
            "Loader: apt-get for %r failed with permission error, retrying with sudo", utility
        )
        ok, stderr = await _run_cmd(["sudo"] + cmd)
        if ok:
            logger.info("Loader: system package for %r installed successfully (sudo)", utility)
            return True
        logger.warning(
            "Loader: apt-get install %r failed even with sudo: %s", utility, stderr[:200]
        )
    else:
        logger.warning("Loader: apt-get install %r failed: %s", utility, stderr[:200])

    return False

async def _ensure_pip_deps(
    deps: list[str],
    progress_cb=None,
    already_installed: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    ok: list[str] = []
    failed: list[str] = []
    if already_installed is None:
        already_installed = set()
    for dep in deps:
        if dep in already_installed:
            ok.append(dep)
            continue
        pip_name = _IMPORT_TO_PIP.get(dep, dep)
        if progress_cb:
            try:
                await progress_cb(
                    f"📦 Устанавливаю зависимость <code>{pip_name}</code>..."
                )
            except Exception:
                pass
        if await _pip_install(dep):
            ok.append(dep)
            already_installed.add(dep)
        else:
            failed.append(pip_name)
    return ok, failed

async def _ensure_system_deps(
    utils: list[str],
    progress_cb=None,
) -> tuple[list[str], list[str]]:
    ok: list[str] = []
    failed: list[str] = []
    for util in utils:
        if shutil.which(util) is not None:
            ok.append(util)
            continue
        if progress_cb:
            try:
                await progress_cb(
                    f"🔧 Устанавливаю системную утилиту <code>{util}</code>..."
                )
            except Exception:
                pass
        if await _system_install(util):
            if shutil.which(util) is not None:
                ok.append(util)
            else:
                logger.warning("Loader: %r installed but still not found in PATH", util)
                failed.append(util)
        else:
            failed.append(util)
    return ok, failed
