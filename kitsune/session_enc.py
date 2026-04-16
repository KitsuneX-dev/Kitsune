from __future__ import annotations

import logging
import os
import stat
import sqlite3
from pathlib import Path

from .crypto import encrypt, decrypt

logger = logging.getLogger(__name__)

DATA_DIR     = Path.home() / ".kitsune"
SESSION_PATH = DATA_DIR / "kitsune.session"
ENC_PATH     = DATA_DIR / "kitsune.session.enc"

def _ensure_data_dir() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    try:
        os.chmod(DATA_DIR, 0o755)
    except Exception:
        pass

def _fix_session_permissions() -> None:
    try:
        if SESSION_PATH.exists():
            os.chmod(SESSION_PATH, 0o644)
            logger.info("session_enc: session permissions -> 644")
    except Exception as e:
        logger.warning("session_enc: could not chmod session file: %s", e)

def _fix_db_readonly() -> None:
    if not SESSION_PATH.exists():
        return
    try:
        os.chmod(SESSION_PATH, 0o644)
    except Exception as e:
        logger.warning("session_enc: _fix_db_readonly chmod failed: %s", e)

    try:
        conn = sqlite3.connect(str(SESSION_PATH))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("SELECT 1")
        conn.close()
        return  
    except sqlite3.OperationalError as e:
        if "readonly" not in str(e):
            return
        logger.warning("session_enc: DB is readonly, attempting recovery...")

    tmp_path = SESSION_PATH.with_suffix(".session.tmp")
    try:
        src = sqlite3.connect(str(SESSION_PATH))
        dst = sqlite3.connect(str(tmp_path))
        for line in src.iterdump():
            dst.execute(line)
        dst.commit()
        src.close()
        dst.close()
        os.chmod(tmp_path, 0o644)

        tmp_path.replace(SESSION_PATH)
        os.chmod(SESSION_PATH, 0o644)
        logger.info("session_enc: DB recovered from readonly state")
    except Exception as ex:
        logger.error("session_enc: DB recovery failed: %s", ex)
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

def _fix_all_permissions() -> None:
    _ensure_data_dir()

    try:
        mode = stat.S_IMODE(DATA_DIR.stat().st_mode)
        if not (mode & stat.S_IWUSR):
            os.chmod(DATA_DIR, 0o755)
            logger.info("session_enc: fixed DATA_DIR permissions -> 755")
    except Exception:
        pass

    if SESSION_PATH.exists():
        try:
            mode = stat.S_IMODE(SESSION_PATH.stat().st_mode)
            if not (mode & stat.S_IWUSR):
                os.chmod(SESSION_PATH, 0o644)
                logger.info("session_enc: fixed session file permissions -> 644")
        except Exception:
            pass

    if ENC_PATH.exists():
        try:
            mode = stat.S_IMODE(ENC_PATH.stat().st_mode)
            if not (mode & stat.S_IWUSR):
                os.chmod(ENC_PATH, 0o600)
                logger.info("session_enc: fixed enc file permissions -> 600")
        except Exception:
            pass

    for subdir in ["modules", "logs"]:
        p = DATA_DIR / subdir
        try:
            p.mkdir(parents=True, exist_ok=True)
            os.chmod(p, 0o755)
        except Exception:
            pass

def encrypt_session_file() -> bool:
    if not SESSION_PATH.exists():
        return False
    try:
        _ensure_data_dir()
        raw = SESSION_PATH.read_bytes()
        ENC_PATH.write_bytes(encrypt(raw))
        os.chmod(ENC_PATH, 0o600)
        SESSION_PATH.unlink()
        logger.info("session_enc: session encrypted -> %s", ENC_PATH)
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
        _ensure_data_dir()
        raw = decrypt(ENC_PATH.read_bytes())
        SESSION_PATH.write_bytes(raw)
        os.chmod(SESSION_PATH, 0o644)
        logger.info("session_enc: session decrypted -> %s", SESSION_PATH)
        return True
    except Exception:
        logger.exception("session_enc: failed to decrypt session")
        return False

def is_encrypted() -> bool:
    return ENC_PATH.exists() and not SESSION_PATH.exists()

def session_ready() -> bool:
    _ensure_data_dir()
    if SESSION_PATH.exists():
        _fix_session_permissions()
        return True
    return decrypt_session_file()
