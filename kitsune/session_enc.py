from __future__ import annotations
import logging
import os
import stat
import sqlite3
import time
from pathlib import Path
from .crypto import encrypt, decrypt

logger = logging.getLogger(__name__)

_RECOVERY_MAX_LOGGED_ERRORS = 5
_RECOVERY_ERROR_RATIO_THRESHOLD = 0.10

from .paths import (
    data_dir as _kdd,
    harden_dir as _harden_dir,
    harden_file as _harden_file,
    PRIVATE_DIR_MODE,
    PRIVATE_FILE_MODE,
)
DATA_DIR     = _kdd()
SESSION_PATH = DATA_DIR / "kitsune.session"
ENC_PATH     = DATA_DIR / "kitsune.session.enc"

def _ensure_data_dir() -> None:

    _harden_dir(DATA_DIR)
def _fix_session_permissions() -> None:
    try:
        if SESSION_PATH.exists():
            os.chmod(SESSION_PATH, PRIVATE_FILE_MODE)
            logger.info("session_enc: session permissions -> 600")
    except Exception as e:
        logger.warning("session_enc: could not chmod session file: %s", e)
def _fix_companion_files() -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        p = SESSION_PATH.parent / (SESSION_PATH.name + suffix)
        if p.exists():
            try:
                os.chmod(p, PRIVATE_FILE_MODE)
            except Exception as e:
                logger.debug(
                    "session_enc: chmod %s failed: %s", p.name, e,
                )
def _fix_db_readonly() -> None:
    if not SESSION_PATH.exists():
        return
    _fix_session_permissions()
    _fix_companion_files()
    try:
        conn = sqlite3.connect(str(SESSION_PATH))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            cur = conn.execute("PRAGMA user_version")
            v = cur.fetchone()[0]
            conn.execute("PRAGMA user_version = {}".format(int(v)))
            conn.commit()
        finally:
            conn.close()
        _fix_companion_files()
        return
    except sqlite3.OperationalError as e:
        if "readonly" not in str(e).lower() and "read-only" not in str(e).lower():
            return
        logger.warning("session_enc: DB is readonly, attempting recovery...")
    tmp_path = SESSION_PATH.with_suffix(".session.tmp")
    try:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        src = sqlite3.connect(
            "file:{}?mode=ro".format(str(SESSION_PATH)), uri=True
        )
        dst = sqlite3.connect(str(tmp_path))
        total = 0
        errors = 0
        try:
            for line in src.iterdump():
                total += 1
                try:
                    dst.execute(line)
                except Exception as dump_err:
                    errors += 1
                    if errors <= _RECOVERY_MAX_LOGGED_ERRORS:
                        logger.warning(
                            "session_enc: ошибка восстановления строки #%d: %s",
                            total, dump_err,
                        )
            dst.commit()
        finally:
            src.close()
            dst.close()
        ratio = (errors / total) if total else 0.0
        if errors and ratio > _RECOVERY_ERROR_RATIO_THRESHOLD:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            corrupt_path = SESSION_PATH.with_name(
                "{}.corrupt.{}".format(SESSION_PATH.name, int(time.time()))
            )
            try:
                SESSION_PATH.replace(corrupt_path)
            except Exception as move_err:
                logger.error(
                    "session_enc: не удалось сохранить повреждённую БД: %s", move_err,
                )
                corrupt_path = SESSION_PATH
            logger.error(
                "session_enc: восстановление ПРЕРВАНО — %d из %d операций "
                "завершились ошибкой (%.0f%%). Повреждённая БД сохранена как %s. "
                "Требуется повторный вход в аккаунт.",
                errors, total, ratio * 100, corrupt_path.name,
            )
            return
        if errors:
            logger.warning(
                "session_enc: БД восстановлена с %d незначительными ошибками из %d",
                errors, total,
            )
        os.chmod(tmp_path, PRIVATE_FILE_MODE)
        for suffix in ("-wal", "-shm", "-journal"):
            p = SESSION_PATH.parent / (SESSION_PATH.name + suffix)
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        tmp_path.replace(SESSION_PATH)
        os.chmod(SESSION_PATH, PRIVATE_FILE_MODE)
        logger.info("session_enc: DB recovered from readonly state")
    except Exception as ex:
        logger.error("session_enc: DB recovery failed: %s", ex)
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
def _fix_all_permissions() -> None:


    before = None
    try:
        before = stat.S_IMODE(DATA_DIR.stat().st_mode)
    except OSError:
        pass
    _harden_dir(DATA_DIR)
    if before is not None and before != PRIVATE_DIR_MODE:
        logger.info(
            "session_enc: fixed DATA_DIR permissions -> %o", PRIVATE_DIR_MODE
        )
    for path, label in ((SESSION_PATH, "session file"), (ENC_PATH, "enc file")):
        if not path.exists():
            continue
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError:
            mode = None
        _harden_file(path)
        if mode is not None and mode != PRIVATE_FILE_MODE:
            logger.info(
                "session_enc: fixed %s permissions -> %o", label, PRIVATE_FILE_MODE
            )
    for subdir in ["modules", "logs"]:
        _harden_dir(DATA_DIR / subdir)
def encrypt_session_file() -> bool:
    if not SESSION_PATH.exists():
        return False
    try:
        _ensure_data_dir()
        try:
            conn = sqlite3.connect(str(SESSION_PATH))
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.commit()
            finally:
                conn.close()
        except Exception as _e:
            logger.debug("session_enc: WAL checkpoint skipped — %s", _e)
        raw = SESSION_PATH.read_bytes()
        ENC_PATH.write_bytes(encrypt(raw))
        os.chmod(ENC_PATH, PRIVATE_FILE_MODE)
        for suffix in ("", "-wal", "-shm", "-journal"):
            p = SESSION_PATH.parent / (SESSION_PATH.name + suffix)
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
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
        _fix_companion_files()
        return True
    try:
        _ensure_data_dir()
        raw = decrypt(ENC_PATH.read_bytes())
        SESSION_PATH.write_bytes(raw)
        os.chmod(SESSION_PATH, PRIVATE_FILE_MODE)
        for suffix in ("-wal", "-shm", "-journal"):
            p = SESSION_PATH.parent / (SESSION_PATH.name + suffix)
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        logger.info("session_enc: session decrypted -> %s", SESSION_PATH)
        return True
    except Exception:
        logger.exception("session_enc: failed to decrypt session")
        return False
def is_encrypted() -> bool:
    return ENC_PATH.exists() and not SESSION_PATH.exists()
def session_ready() -> bool:
    _ensure_data_dir()
    _fix_all_permissions()
    if SESSION_PATH.exists():
        _fix_session_permissions()
        _fix_db_readonly()
        return True
    ok = decrypt_session_file()
    if ok:
        _fix_db_readonly()
    return ok
