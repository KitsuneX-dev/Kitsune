from __future__ import annotations
import os
import platform
import sys
from pathlib import Path

def is_docker() -> bool:
    return (
        os.path.exists("/.dockerenv")
        or "DOCKER" in os.environ
        or _cgroup("docker")
    )
def is_termux() -> bool:
    if "com.termux" in os.environ.get("PREFIX", ""):
        return True
    try:
        return Path("/data/data/com.termux").exists()
    except PermissionError:
        return False
USERLAND_DIRS = ("/data/data/tech.ula", "/data/user/0/tech.ula")
_LOW_POWER_TRUTHY = frozenset({"1", "true", "yes", "on"})

def is_userland() -> bool:
    for path in USERLAND_DIRS:
        try:
            if os.path.isdir(path):
                return True
        except OSError:
            continue
    return False

def _is_android_kernel() -> bool:
    try:
        return "android" in Path("/proc/version").read_text(errors="ignore").lower()
    except Exception:
        return False


def is_mobile() -> bool:
    if _is_android_kernel():
        return True
    if is_termux() or is_userland():
        return True
    if os.environ.get("KITSUNE_LOW_POWER", "").strip().lower() in _LOW_POWER_TRUTHY:
        return True
    try:
        from ..low_power import load_config, resolve
        if resolve(load_config()):
            return True
    except Exception:
        pass
    return False


def _tracer_pid() -> int:
    try:
        for line in Path("/proc/self/status").read_text(errors="ignore").splitlines():
            if line.startswith("TracerPid:"):
                return int(line.split(":", 1)[1].strip())
    except Exception:
        return 0
    return 0


def _detect_proot() -> bool:
    try:
        if _tracer_pid() != 0:
            return True
    except Exception:
        pass
    try:
        if is_userland() and not _is_android_kernel():
            return True
    except Exception:
        pass
    return False

def is_heroku() -> bool:
    return "DYNO" in os.environ
def _cgroup(kw: str) -> bool:
    try:
        return kw in Path("/proc/1/cgroup").read_text(errors="ignore")
    except Exception:
        return False
def get_platform_name() -> str:
    if is_docker():   return "Docker"
    if is_termux():   return "Termux"
    if is_heroku():   return "Heroku"
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
def get_arch() -> str:
    return platform.machine() or "unknown"


def get_named_platform_label(*, termux_suffix: bool = False) -> str:
    if os.environ.get("TERMUX_VERSION") or os.path.isdir("/data/data/com.termux"):
        return "📱 Termux — Android" if termux_suffix else "📱 Termux"
    system = platform.system()
    return {
        "Linux": "🐧 Linux",
        "Windows": "🪟 Windows",
        "Darwin": "🍎 macOS",
    }.get(system, f"❓ {system}" if termux_suffix else system)


def get_os_pretty_name() -> str:
    try:
        path = Path("/etc/os-release")
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'") or platform.system()
        return platform.system() or "—"
    except Exception:
        return "—"


def get_kernel_release() -> str:
    try:
        return platform.release() or "—"
    except Exception:
        return "—"


def get_hostname() -> str:
    try:
        import socket
        return socket.gethostname() or "—"
    except Exception:
        return "—"


def get_username() -> str:
    try:
        import getpass
        return getpass.getuser() or "—"
    except Exception:
        return "—"


def get_cpu_model_cores() -> str:
    try:
        import psutil
        physical = psutil.cpu_count(logical=False) or 0
        logical = psutil.cpu_count(logical=True) or 0
        model = ""
        try:
            cpuinfo = Path("/proc/cpuinfo")
            if cpuinfo.is_file():
                for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.lower().startswith("model name"):
                        model = line.split(":", 1)[1].strip()
                        break
        except Exception:
            model = ""
        if not model:
            model = (platform.processor() or "").strip()
        cores = f"{physical} ({logical}) core(-s)"
        return f"{model}; {cores}" if model else cores
    except Exception:
        return "—"


def get_run_environment() -> str:
    try:
        if os.environ.get("TERMUX_VERSION") or os.path.isdir("/data/data/com.termux"):
            return "📱 Termux"
        if is_userland():
            return "📦 UserLand"
        if os.path.exists("/.dockerenv"):
            return "🐳 Docker"
        wsl_distro = os.environ.get("WSL_DISTRO_NAME")
        if "microsoft" in platform.release().lower() or wsl_distro:
            return f"🪟 WSL ({wsl_distro or '?'})"
        return "💻 Bare-metal"
    except Exception:
        return "❓ неизвестно"
