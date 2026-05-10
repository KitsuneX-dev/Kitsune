from __future__ import annotations
import logging as _logging

__author__ = "Yushi"
__contact__ = "@Mikasu32"
__copyright__ = "Copyright 2024-2026, Yushi"
__license__ = "AGPLv3"
__status__ = "Production"

_log = _logging.getLogger(__name__)

_PATCHES_INSTALLED = False


def _chmod_session_files(filename) -> None:
    """Чиним права на основной файл сессии и его WAL/SHM/journal-спутники."""
    if not filename or filename == ":memory:":
        return
    try:
        import os as _os
        from pathlib import Path as _PP
        base = _PP(str(filename))
        parent = base.parent
        try:
            if parent.exists():
                _os.chmod(parent, 0o755)
        except Exception:
            pass
        for _suf in ("", "-wal", "-shm", "-journal"):
            _p = _PP(str(filename) + _suf)
            if _p.exists():
                try:
                    _os.chmod(_p, 0o644)
                except Exception:
                    pass
    except Exception:
        pass


def install_patches() -> None:
    global _PATCHES_INSTALLED
    if _PATCHES_INSTALLED:
        return

    # ── 1. Hardening MTProxy readexactly ────────────────────────────────────
    try:
        from telethon.network.connection import tcpmtproxy as _m
        _target = None
        for _name in dir(_m):
            _obj = getattr(_m, _name, None)
            if isinstance(_obj, type) and "readexactly" in _obj.__dict__:
                _target = _obj
                break
        if _target is not None and not getattr(
            _target.readexactly, "_kitsune_size_guard", False
        ):
            _orig = _target.readexactly

            async def _readexactly_safe(self, n):
                if n is None or n < 0:
                    raise ConnectionError(f"MTProxy: invalid packet size ({n!r})")
                if n == 0:
                    return b""
                return await _orig(self, n)

            _readexactly_safe._kitsune_size_guard = True
            _target.readexactly = _readexactly_safe
            _log.info(
                "kitsune: MTProxy hardening (patched %s.readexactly)",
                _target.__name__,
            )
    except Exception as _exc:
        _log.debug("kitsune: MTProxyIO patch skipped — %s", _exc)

    # ── 2. Hardening IntermediatePacketCodec ────────────────────────────────
    try:
        from telethon.network.connection import tcpintermediate as _ti
        _cls = getattr(_ti, "IntermediatePacketCodec", None)
        if (
            _cls is not None
            and "read_packet" in _cls.__dict__
            and not getattr(_cls.read_packet, "_kitsune_len_guard", False)
        ):
            import struct as _struct

            async def _read_packet_safe(self, reader):
                length_bytes = await reader.readexactly(4)
                if not length_bytes or len(length_bytes) < 4:
                    raise ConnectionError(
                        "Intermediate codec: short read on length field"
                    )
                (length,) = _struct.unpack("<i", length_bytes)
                MAX_PACKET = 16 * 1024 * 1024
                if length <= 0 or length > MAX_PACKET:
                    raise ConnectionError(
                        f"Intermediate codec: bogus packet length ({length})"
                    )
                return await reader.readexactly(length)

            _read_packet_safe._kitsune_len_guard = True
            _cls.read_packet = _read_packet_safe
            _log.info(
                "kitsune: MTProxy hardening (patched %s.read_packet)",
                _cls.__name__,
            )
    except Exception as _exc:
        _log.debug("kitsune: IntermediatePacketCodec patch skipped — %s", _exc)

    # ── 3. SQLiteSession.process_entities: лечим "no such table"/readonly ───
    try:
        from telethon.sessions import sqlite as _ts_sqlite
        import sqlite3 as _sqlite3

        _SQLiteSession = getattr(_ts_sqlite, "SQLiteSession", None)

        if (
            _SQLiteSession is not None
            and "process_entities" in _SQLiteSession.__dict__
            and not getattr(
                _SQLiteSession.process_entities, "_kitsune_table_guard", False
            )
        ):
            _orig_pe = _SQLiteSession.process_entities

            _SCHEMA = {
                "entities": (
                    "CREATE TABLE IF NOT EXISTS entities ("
                    "id integer primary key, hash integer not null, "
                    "username text, phone integer, name text, date integer)"
                ),
                "sent_files": (
                    "CREATE TABLE IF NOT EXISTS sent_files ("
                    "md5_digest blob, file_size integer, type integer, "
                    "id integer, hash integer, "
                    "primary key(md5_digest, file_size, type))"
                ),
                "update_state": (
                    "CREATE TABLE IF NOT EXISTS update_state ("
                    "id integer primary key, pts integer, qts integer, "
                    "date integer, seq integer)"
                ),
                "version": (
                    "CREATE TABLE IF NOT EXISTS version ("
                    "version integer primary key)"
                ),
                "sessions": (
                    "CREATE TABLE IF NOT EXISTS sessions ("
                    "dc_id integer primary key, server_address text, "
                    "port integer, auth_key blob, takeout_id integer, "
                    "tmp_auth_key blob)"
                ),
            }

            def _ensure_tables(self) -> None:
                try:
                    cur = self._cursor()
                    try:
                        for _ddl in _SCHEMA.values():
                            cur.execute(_ddl)
                    finally:
                        cur.close()
                    try:
                        self.save()
                    except Exception:
                        pass
                except Exception as _e:
                    _log.debug("kitsune: _ensure_tables failed — %s", _e)

            def _safe_process_entities(self, tlo):
                try:
                    return _orig_pe(self, tlo)
                except _sqlite3.OperationalError as exc:
                    msg = str(exc).lower()
                    if "readonly" in msg or "read-only" in msg:
                        # Чиним права и пробуем ещё раз
                        _chmod_session_files(getattr(self, "filename", None))
                        try:
                            return _orig_pe(self, tlo)
                        except Exception as _e2:
                            _log.debug(
                                "kitsune: process_entities readonly retry failed — %s",
                                _e2,
                            )
                            return
                    if "no such table" not in msg:
                        raise
                    _log.info(
                        "kitsune: session-db missing table during "
                        "process_entities (%s) — пересоздаю схему", exc,
                    )
                    _ensure_tables(self)
                    try:
                        return _orig_pe(self, tlo)
                    except Exception as _e2:
                        _log.debug(
                            "kitsune: process_entities повторно упал — %s "
                            "(игнорирую, чтобы не ломать shutdown)", _e2,
                        )
                        return
                except Exception as _e:
                    _log.debug(
                        "kitsune: process_entities silently swallowed — %s", _e,
                    )
                    return

            _safe_process_entities._kitsune_table_guard = True
            _SQLiteSession.process_entities = _safe_process_entities
            _log.info(
                "kitsune: SQLiteSession.process_entities patched "
                "(self-heal missing 'entities' table on shutdown)",
            )
    except Exception as _exc:
        _log.debug("kitsune: SQLiteSession patch skipped — %s", _exc)

    # ── 4. SQLiteSession._create_table: идемпотентный CREATE ────────────────
    #
    # ИСПРАВЛЕНО: вместо ловли ошибки "already exists" пост-фактум — превентивно
    # подставляем "IF NOT EXISTS" в определение, чтобы запрос вообще не падал.
    # Это нужно потому, что патч может применяться УЖЕ ПОСЛЕ того, как Telethon
    # успел импортировать класс (например, через tl_cache.py на верхнем уровне).
    try:
        from telethon.sessions import sqlite as _ts_sqlite2
        import re as _re

        _SQLiteSession2 = getattr(_ts_sqlite2, "SQLiteSession", None)

        if (
            _SQLiteSession2 is not None
            and "_create_table" in _SQLiteSession2.__dict__
            and not getattr(
                _SQLiteSession2._create_table, "_kitsune_idempotent_guard", False
            )
        ):

            def _safe_create_table(self, c, *definitions):
                for definition in definitions:
                    # Превентивно превращаем "name (...)" в "IF NOT EXISTS name (..."
                    # чтобы запрос был идемпотентным изначально.
                    stmt = "create table if not exists {}".format(definition)
                    try:
                        c.execute(stmt)
                    except Exception as _e:
                        msg = str(_e).lower()
                        if "already exists" in msg:
                            _log.debug(
                                "kitsune: _create_table — таблица уже есть, пропускаю"
                            )
                            continue
                        # Если SQLite по какой-то причине не поддерживает синтаксис —
                        # пробуем старый CREATE TABLE как fallback.
                        try:
                            c.execute("create table {}".format(definition))
                        except Exception as _e2:
                            msg2 = str(_e2).lower()
                            if "already exists" in msg2:
                                continue
                            raise

            _safe_create_table._kitsune_idempotent_guard = True
            _SQLiteSession2._create_table = _safe_create_table
            _log.info(
                "kitsune: SQLiteSession._create_table patched (idempotent, IF NOT EXISTS)",
            )
    except Exception as _exc:
        _log.debug("kitsune: SQLiteSession._create_table patch skipped — %s", _exc)

    # ── 5. SQLiteSession.set_update_state / save: readonly-safe ─────────────
    try:
        from telethon.sessions import sqlite as _ts_sqlite3
        import sqlite3 as _sqlite3_v3

        _SQLiteSession3 = getattr(_ts_sqlite3, "SQLiteSession", None)

        if (
            _SQLiteSession3 is not None
            and "set_update_state" in _SQLiteSession3.__dict__
            and not getattr(
                _SQLiteSession3.set_update_state, "_kitsune_ro_guard", False
            )
        ):
            _orig_sus = _SQLiteSession3.set_update_state

            def _safe_set_update_state(self, entity_id, state):
                try:
                    return _orig_sus(self, entity_id, state)
                except _sqlite3_v3.OperationalError as exc:
                    msg = str(exc).lower()
                    if "readonly" in msg or "read-only" in msg:
                        # Чиним права на основной файл + WAL/SHM/journal
                        _chmod_session_files(getattr(self, "filename", None))
                        try:
                            return _orig_sus(self, entity_id, state)
                        except Exception:
                            pass
                        _log.debug(
                            "kitsune: set_update_state — readonly DB, skipping (%s)",
                            exc,
                        )
                        return
                    raise
                except Exception as _e:
                    _log.debug(
                        "kitsune: set_update_state silently swallowed — %s", _e,
                    )
                    return

            _safe_set_update_state._kitsune_ro_guard = True
            _SQLiteSession3.set_update_state = _safe_set_update_state
            _log.info(
                "kitsune: SQLiteSession.set_update_state patched (readonly-safe)",
            )

        if (
            _SQLiteSession3 is not None
            and "save" in _SQLiteSession3.__dict__
            and not getattr(_SQLiteSession3.save, "_kitsune_ro_guard", False)
        ):
            _orig_save = _SQLiteSession3.save

            def _safe_save(self):
                try:
                    return _orig_save(self)
                except _sqlite3_v3.OperationalError as exc:
                    msg = str(exc).lower()
                    if "readonly" in msg or "read-only" in msg:
                        _chmod_session_files(getattr(self, "filename", None))
                        try:
                            return _orig_save(self)
                        except Exception:
                            pass
                        _log.debug(
                            "kitsune: SQLiteSession.save() — readonly DB, skip (%s)",
                            exc,
                        )
                        return
                    raise
                except Exception as _e:
                    _log.debug("kitsune: SQLiteSession.save() swallowed — %s", _e)
                    return

            _safe_save._kitsune_ro_guard = True
            _SQLiteSession3.save = _safe_save
            _log.info("kitsune: SQLiteSession.save patched (readonly-safe)")
    except Exception as _exc:
        _log.debug("kitsune: SQLiteSession set_update_state patch skipped — %s", _exc)

    # ── 6. TelegramBaseClient._save_states_and_entities: readonly-safe ──────
    try:
        from telethon.client import telegrambaseclient as _tbc
        import sqlite3 as _sqlite3_v4

        _TBC = getattr(_tbc, "TelegramBaseClient", None)

        if (
            _TBC is not None
            and "_save_states_and_entities" in _TBC.__dict__
            and not getattr(
                _TBC._save_states_and_entities, "_kitsune_ro_guard", False
            )
        ):
            _orig_sse = _TBC._save_states_and_entities

            async def _safe_sse(self):
                try:
                    return await _orig_sse(self)
                except _sqlite3_v4.OperationalError as exc:
                    msg = str(exc).lower()
                    if (
                        "readonly" in msg
                        or "read-only" in msg
                        or "no such table" in msg
                    ):
                        # Пробуем починить права и повторить (важно для shutdown)
                        try:
                            sess = getattr(self, "session", None)
                            _chmod_session_files(getattr(sess, "filename", None))
                            return await _orig_sse(self)
                        except Exception:
                            pass
                        _log.debug(
                            "kitsune: _save_states_and_entities — DB issue swallowed (%s)",
                            exc,
                        )
                        return
                    raise
                except Exception as _e:
                    _log.debug(
                        "kitsune: _save_states_and_entities silently swallowed — %s",
                        _e,
                    )
                    return

            _safe_sse._kitsune_ro_guard = True
            _TBC._save_states_and_entities = _safe_sse
            _log.info(
                "kitsune: TelegramBaseClient._save_states_and_entities patched (safe)",
            )
    except Exception as _exc:
        _log.debug(
            "kitsune: TelegramBaseClient._save_states_and_entities patch skipped — %s",
            _exc,
        )

    _PATCHES_INSTALLED = True


# ── АВТО-ПРИМЕНЕНИЕ ПАТЧЕЙ ПРИ ИМПОРТЕ ПАКЕТА ───────────────────────────────
# КРИТИЧНО: патчи должны быть применены ДО того, как любой другой модуль пакета
# (например, kitsune/tl_cache.py) выполнит `from telethon import TelegramClient`.
# Поэтому вызываем install_patches() прямо здесь, на этапе импорта пакета kitsune.
# main.py всё равно вызовет install_patches() повторно — это безопасно благодаря
# _PATCHES_INSTALLED-флагу.
try:
    install_patches()
except Exception as _e:
    _log.debug("kitsune: auto install_patches at import failed — %s", _e)
