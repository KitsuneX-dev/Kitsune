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
    return (
        "com.termux" in os.environ.get("PREFIX", "")
        or Path("/data/data/com.termux").exists()
    )

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
