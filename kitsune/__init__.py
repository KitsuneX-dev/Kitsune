from __future__ import annotations
import logging as _logging

__author__ = "Yushi"

__contact__ = "@Mikasu32"

__copyright__ = "Copyright 2024-2026, Yushi"

__license__ = "AGPLv3"

__status__ = "Production"

_log = _logging.getLogger(__name__)

_PATCHES_INSTALLED = False

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

                    raise ConnectionError(

                        f"MTProxy: invalid packet size ({n!r})"

                    )

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

    # ── 3. SQLiteSession: лечим "no such table: entities" при disconnect ────
    #
    # Telethon 1.40+ при `client.disconnect()` зовёт `_save_states_and_entities`,
    # который вызывает `session.process_entities(...)`. Если SQLite-файл сессии
    # был создан/мигрирован некорректно (например, после ручной правки или сбоя
    # в момент шифрования), таблицы `entities` может НЕ быть, и мы получаем:
    #
    #     sqlite3.OperationalError: no such table: entities
    #
    # Это валит весь shutdown по Ctrl+C. Лечим точечно: при первом таком
    # OperationalError создаём недостающие таблицы (по схеме Telethon) и
    # повторяем операцию. Если таблицы уже есть — патч прозрачен.
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

            # Полная схема таблиц Telethon — на случай, если повреждён не только
            # `entities`, но и соседние (`sent_files`, `update_state`).
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
                """Создаёт все недостающие таблицы Telethon-сессии."""
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
                    _log.debug(
                        "kitsune: _ensure_tables failed — %s", _e,
                    )

            def _safe_process_entities(self, tlo):

                try:

                    return _orig_pe(self, tlo)

                except _sqlite3.OperationalError as exc:

                    msg = str(exc).lower()

                    if "no such table" not in msg:

                        # Не наш кейс — пробрасываем дальше.
                        raise

                    _log.info(
                        "kitsune: session-db missing table during "
                        "process_entities (%s) — пересоздаю схему", exc,
                    )

                    _ensure_tables(self)

                    try:

                        return _orig_pe(self, tlo)

                    except Exception as _e2:

                        # Не валим disconnect из-за служебного апдейта сущностей.
                        _log.debug(
                            "kitsune: process_entities повторно упал — %s "
                            "(игнорирую, чтобы не ломать shutdown)",
                            _e2,
                        )

                        return

                except Exception as _e:

                    # Любая другая ошибка процесса сущностей не должна
                    # обрушать disconnect (это поведение и так нормально
                    # для Telethon-а — у него тут не критичный путь).
                    _log.debug(
                        "kitsune: process_entities silently swallowed — %s",
                        _e,
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

    _PATCHES_INSTALLED = True
