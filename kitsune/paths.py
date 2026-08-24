from __future__ import annotations
import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_DATA_DIR = "KITSUNE_DATA_DIR"
_ENV_CONFIG = "KITSUNE_CONFIG"
_ENV_DOCKER = "DOCKER"

DOCKER_DATA_DIR = "/data"

_FALSY = frozenset({"0", "false", "no", "off"})


PRIVATE_DIR_MODE = 0o700

PRIVATE_FILE_MODE = 0o600


def in_docker() -> bool:
    raw = os.environ.get(_ENV_DOCKER)
    if raw is not None and raw.strip().lower() not in _FALSY:
        return True
    return Path("/.dockerenv").exists()


def default_data_dir() -> Path:
    if in_docker():
        return Path(DOCKER_DATA_DIR)
    return Path.home() / ".kitsune"


def data_dir() -> Path:
    override = os.environ.get(_ENV_DATA_DIR, "").strip()
    if override:
        return Path(override).expanduser()
    return default_data_dir()


def config_path(base_dir: Path | None = None) -> Path:
    override = os.environ.get(_ENV_CONFIG, "").strip()
    if override:
        return Path(override).expanduser()
    if base_dir is not None:
        return Path(base_dir) / "config.toml"
    if in_docker():
        return default_data_dir() / "config.toml"
    return Path.cwd() / "config.toml"


def effective_config_path() -> Path:
    try:
        from .main import CONFIG_PATH as _path
        return Path(_path)
    except Exception:
        return config_path()


def is_secondary() -> bool:
    override = os.environ.get(_ENV_DATA_DIR, "").strip()
    if not override:
        return False
    own = Path(override).expanduser()
    base = default_data_dir()
    try:
        return own.resolve() != base.resolve()
    except OSError:
        return str(own) != str(base)


def harden_dir(path: Path | str, *, create: bool = True) -> Path:
    p = Path(path)
    if create:
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.debug("paths: mkdir %s не удался — %s", p, e)
    try:
        mode = stat.S_IMODE(p.stat().st_mode)
    except OSError as e:
        logger.debug("paths: stat %s не удался — %s", p, e)
        return p
    if mode == PRIVATE_DIR_MODE:
        return p
    try:
        os.chmod(p, PRIVATE_DIR_MODE)
        logger.debug("paths: %s -> 0700 (было %o)", p, mode)
    except Exception as e:
        logger.debug("paths: chmod %s не поддерживается — %s", p, e)
    return p


def harden_file(path: Path | str) -> Path:
    p = Path(path)
    try:
        mode = stat.S_IMODE(p.stat().st_mode)
    except OSError as e:
        logger.debug("paths: stat %s не удался — %s", p, e)
        return p
    if mode == PRIVATE_FILE_MODE:
        return p
    try:
        os.chmod(p, PRIVATE_FILE_MODE)
        logger.debug("paths: %s -> 0600 (было %o)", p, mode)
    except Exception as e:
        logger.debug("paths: chmod %s не поддерживается — %s", p, e)
    return p
