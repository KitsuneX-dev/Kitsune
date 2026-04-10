from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

from .crypto import encrypt, decrypt

logger = logging.getLogger(__name__)

DATA_DIR     = Path.home() / ".kitsune"
SESSION_PATH = DATA_DIR / "kitsune.session"
ENC_PATH     = DATA_DIR / "kitsune.session.enc"


def _ensure_dir_writable() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        current = stat.S_IMODE(DATA_DIR.stat().st_mode)
        if not (current & stat.S_IWUSR):
            DATA_DIR.chmod(0o755)
    except Exception:
        pass


def _fix_session_permissions() -> None:
    try:
        if SESSION_PATH.exists():
            current = stat.S_IMODE(SESSION_PATH.stat().st_mode)
            if not (current & stat.S_IWUSR):
                SESSION_PATH.chmod(0o644)
                logger.info("session_enc: fixed session file permissions → 644")
    except Exception:
        pass


def encrypt_session_file() -> bool:
    if not SESSION_PATH.exists():
        return False
    try:
        _ensure_dir_writable()
        raw = SESSION_PATH.read_bytes()
        ENC_PATH.write_bytes(encrypt(raw))
        ENC_PATH.chmod(0o600)
        SESSION_PATH.unlink()
        logger.info("session_enc: session encrypted → %s", ENC_PATH)
        return True
    except Exception:
        logger.exception("session_enc: failed to encrypt session")
        return False


def decrypt_session_file() -> bool:
    if not ENC_PATH.exists():
        return False
    if SESSION_PATH.exists():
        _fix_session_permissions()
        return True
    try:
        _ensure_dir_writable()
        raw = decrypt(ENC_PATH.read_bytes())
        SESSION_PATH.write_bytes(raw)
        SESSION_PATH.chmod(0o644)
        logger.info("session_enc: session decrypted → %s", SESSION_PATH)
        return True
    except Exception:
        logger.exception("session_enc: failed to decrypt session")
        return False


def is_encrypted() -> bool:
    return ENC_PATH.exists() and not SESSION_PATH.exists()


def session_ready() -> bool:
    if SESSION_PATH.exists():
        _fix_session_permissions()
        return True
    return decrypt_session_file()
