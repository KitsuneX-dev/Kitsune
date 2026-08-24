from __future__ import annotations
import asyncio
import logging
import sqlite3
import time
import typing
from pathlib import Path
from .._json import dumps as json_dumps, loads as json_loads, is_serializable

logger = logging.getLogger(__name__)

try:
    from ..utils.platform import is_mobile as _is_mobile
    _IS_ANDROID = _is_mobile()
except Exception:
    try:
        _IS_ANDROID = "android" in Path("/proc/version").read_text(errors="ignore").lower()
    except Exception:
        _IS_ANDROID = False

try:
    from ..utils.platform import _detect_proot
    _UNDER_PROOT = _detect_proot()
except Exception:
    _UNDER_PROOT = False

_DELAY_CACHE_TTL = 30.0
_delay_cache: float | None = None
_delay_checked_at: float = 0.0

_DB_SIDECARS = ("-wal", "-shm", "-journal")


def _journal_settings() -> tuple[str, int]:
    if _UNDER_PROOT:
        return "WAL", 0
    if _IS_ANDROID:
        return "DELETE", 0
    return "WAL", 64 << 20


def _migrate_legacy_db(legacy_dir: Path, new_path: Path) -> None:
    try:
        legacy_path = Path(legacy_dir) / new_path.name
        if legacy_path == new_path or not legacy_path.is_file() or new_path.exists():
            return
        import shutil
        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_path), str(new_path))
        logger.info("Database: БД перенесена %s -> %s", legacy_path, new_path)
        for suffix in _DB_SIDECARS:
            side = legacy_path.with_name(legacy_path.name + suffix)
            target = new_path.with_name(new_path.name + suffix)
            if side.is_file() and not target.exists():
                try:
                    shutil.move(str(side), str(target))
                except OSError:
                    logger.warning("Database: не удалось перенести %s", side, exc_info=True)
    except Exception:
        logger.warning("Database: миграция старой БД не удалась", exc_info=True)

JSONValue = typing.Union[
    None, bool, int, float, str,
    typing.List[typing.Any],
    typing.Dict[str, typing.Any],
]

class SQLiteBackend:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None
    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(str(self._path), timeout=10, check_same_thread=False)
            journal_mode, mmap_size = _journal_settings()
            if _UNDER_PROOT:


                conn.execute(f"PRAGMA journal_mode={journal_mode}")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA cache_size=-4000")
                conn.execute(f"PRAGMA mmap_size={mmap_size}")
                conn.execute("PRAGMA temp_store=MEMORY")
                conn.execute("PRAGMA wal_autocheckpoint=10000")
                conn.execute("PRAGMA busy_timeout=5000")
            elif _IS_ANDROID:
                conn.execute(f"PRAGMA journal_mode={journal_mode}")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute(f"PRAGMA mmap_size={mmap_size}")
                conn.execute("PRAGMA cache_size=-4000")
                conn.execute("PRAGMA temp_store=MEMORY")
                conn.execute("PRAGMA busy_timeout=5000")
            else:
                conn.execute(f"PRAGMA journal_mode={journal_mode}")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA cache_size=-8000")
                conn.execute(f"PRAGMA mmap_size={mmap_size}")
                conn.execute("PRAGMA temp_store=MEMORY")
                conn.execute("PRAGMA wal_autocheckpoint=10000")
                conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS kitsune_db "
                "(owner TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
                "PRIMARY KEY (owner, key))"
            )
            conn.commit()
            self._conn = conn
        return self._conn
    def close(self) -> None:
        if self._conn:
            try:
                self._conn.execute("PRAGMA optimize")
                self._conn.commit()
            except Exception:
                pass
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
    async def load(self) -> dict[str, dict[str, JSONValue]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._load_sync)
    def _load_sync(self) -> dict[str, dict[str, JSONValue]]:
        try:
            conn = self._get_conn()
            rows = conn.execute("SELECT owner, key, value FROM kitsune_db").fetchall()
            result: dict[str, dict[str, JSONValue]] = {}
            for owner, key, raw in rows:
                result.setdefault(owner, {})[key] = json_loads(raw)
            return result
        except Exception:
            logger.exception("SQLite: failed to load database")
            return {}
    async def save(self, data: dict[str, dict[str, JSONValue]]) -> bool:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._save_sync, data)
    def upsert_sync(self, rows: list[tuple[str, str, str]], deleted: list[tuple[str, str]]) -> bool:
        try:
            conn = self._get_conn()
            if rows:
                conn.executemany(
                    "INSERT INTO kitsune_db (owner, key, value) VALUES (?, ?, ?) "
                    "ON CONFLICT(owner, key) DO UPDATE SET value=excluded.value",
                    rows,
                )
            if deleted:
                conn.executemany(
                    "DELETE FROM kitsune_db WHERE owner=? AND key=?",
                    deleted,
                )
            conn.commit()
            return True
        except Exception:
            logger.exception("SQLite: upsert_sync failed")
            return False
    def _save_sync(self, data: dict[str, dict[str, JSONValue]]) -> bool:
        try:
            conn = self._get_conn()
            rows = [
                (owner, key, json_dumps(value))
                for owner, sub in data.items()
                for key, value in sub.items()
            ]
            conn.executemany(
                "INSERT INTO kitsune_db (owner, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(owner, key) DO UPDATE SET value=excluded.value",
                rows,
            )
            conn.execute(
                "CREATE TEMP TABLE IF NOT EXISTS _ks_keep "
                "(owner TEXT NOT NULL, key TEXT NOT NULL, PRIMARY KEY(owner, key))"
            )
            conn.execute("DELETE FROM _ks_keep")
            conn.executemany("INSERT OR IGNORE INTO _ks_keep VALUES (?,?)",
                             [(o, k) for o, k, _ in rows])
            conn.execute(
                "DELETE FROM kitsune_db WHERE NOT EXISTS "
                "(SELECT 1 FROM _ks_keep WHERE _ks_keep.owner=kitsune_db.owner "
                " AND _ks_keep.key=kitsune_db.key)"
            )
            conn.commit()
            return True
        except Exception:
            logger.exception("SQLite: failed to save database")
            return False
class RedisBackend:
    def __init__(self, uri: str, client_id: int) -> None:
        import redis as _redis
        self._redis = _redis.Redis.from_url(
            uri,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            socket_keepalive=True,
            health_check_interval=30,
        )
        self._key = str(client_id)
        self._lock = asyncio.Lock()
        self._uri = uri
    def ping(self) -> bool:
        try:
            return bool(self._redis.ping())
        except Exception:
            return False
    async def load(self) -> dict[str, dict[str, JSONValue]]:
        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(None, self._redis.get, self._key)
            if raw:
                return json_loads(raw.decode() if isinstance(raw, bytes) else raw)
        except Exception:
            logger.exception("Redis: failed to load")
            raise
        return {}
    async def save(self, data: dict[str, dict[str, JSONValue]]) -> bool:
        loop = asyncio.get_event_loop()
        try:
            serialized = json_dumps(data)
            await loop.run_in_executor(None, self._redis.set, self._key, serialized)
            logger.debug("Redis: database saved")
            return True
        except Exception:
            logger.exception("Redis: failed to save")
            return False
class DatabaseManager:
    _MAX_REVISIONS = 20
    _REVISION_INTERVAL = 3
    _SAVE_DELAY = 0.2
    _REDIS_FAIL_THRESHOLD = 3
    def __init__(self, client: typing.Any) -> None:
        self._client = client
        self._data: dict[str, dict[str, JSONValue]] = {}
        self._lock = asyncio.Lock()
        self._backend: SQLiteBackend | RedisBackend | None = None
        self._revisions: list[tuple[float, list[tuple[str, str, JSONValue]]]] = []
        self._next_revision_at: float = 0.0
        self._pending_save: asyncio.Task | None = None
        self._assets_channel: int | None = None
        self._dirty: set[tuple[str, str]] = set()
        self._deleted: set[tuple[str, str]] = set()
        self._bg_tasks: set[asyncio.Task] = set()
        self._redis_fail_streak: int = 0
        self._sqlite_fallback: SQLiteBackend | None = None
        self._redis_uri: str | None = None
        self._sqlite_path: typing.Any = None
    def _save_delay(self) -> float:
        global _delay_cache, _delay_checked_at
        now = time.monotonic()
        if _delay_cache is not None and now - _delay_checked_at < _DELAY_CACHE_TTL:
            return _delay_cache
        try:
            from ..low_power import load_config, save_delay
            value = save_delay(load_config())
        except Exception:
            return self._SAVE_DELAY
        _delay_cache = value
        _delay_checked_at = now
        return value
    async def init(self) -> None:
        import os as _os
        from pathlib import Path as _Path
        redis_uri = _os.environ.get("REDIS_URL")
        if not redis_uri:
            try:
                import toml as _toml
                from ..paths import effective_config_path as _eff_cfg
                _cfg_path = _eff_cfg()
                if _cfg_path.exists():
                    _cfg = _toml.loads(_cfg_path.read_text(encoding="utf-8"))
                    redis_uri = _cfg.get("redis_uri")
            except Exception:
                pass
        from ..paths import data_dir as _data_dir
        _base = _data_dir()
        try:
            _base.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("Database: не удалось создать каталог данных %s", _base, exc_info=True)
        db_path = _base / f"kitsune-{self._client.tg_id}.db"
        _migrate_legacy_db(_Path(__file__).parent.parent.parent, db_path)
        self._sqlite_path = db_path
        if redis_uri:
            self._redis_uri = redis_uri
            try:
                self._backend = RedisBackend(redis_uri, self._client.tg_id)
                self._data = await self._backend.load()
                logger.info("Database: Redis backend active")
                try:
                    self._sqlite_fallback = SQLiteBackend(db_path)
                except Exception:
                    logger.debug("Database: SQLite fallback not pre-warmed", exc_info=True)
                try:
                    from ..core.reliability import flags as _deg_flags
                    _deg_flags.clear_redis_unavailable()
                except Exception:
                    pass
            except Exception as _exc:
                logger.warning(
                    "Database: Redis unavailable (%s: %s), falling back to SQLite",
                    type(_exc).__name__, _exc,
                )
                try:
                    from ..core.reliability import flags as _deg_flags
                    _deg_flags.mark_redis_unavailable(f"{type(_exc).__name__}: {_exc}")
                except Exception:
                    pass
                self._backend = None
        if self._backend is None:
            self._backend = SQLiteBackend(db_path)
            self._data = await self._backend.load()
            logger.info("Database: SQLite backend active (%s)", db_path)
        try:
            cached_assets = (
                self._data.get("kitsune.asset_channels", {}).get("kitsune-assets")
                or self._data.get("kitsune.assets_channel", {}).get("channel_id")
                or self._data.get("kitsune.assets", {}).get("known_kitsune_assets")
            )
            if isinstance(cached_assets, int) and cached_assets:
                self._assets_channel = cached_assets
                logger.debug(
                    "Database: assets channel id=%s взят из кэша БД (без сетевого запроса)",
                    cached_assets,
                )
        except Exception:
            pass
        try:
            _bg = asyncio.ensure_future(self._init_assets_channel())
            self._bg_tasks.add(_bg)
            _bg.add_done_callback(self._bg_tasks.discard)
        except RuntimeError:
            await self._init_assets_channel()

    async def _init_assets_channel(self) -> None:
        try:
            from .. import utils
            from telethon.errors import ChannelsTooMuchError, FloodWaitError
            import asyncio as _aio
            for _attempt in range(3):
                try:
                    new_id, _created = await utils.asset_channel(
                        self._client,
                        "kitsune-assets",
                        description="🦊 Your Kitsune assets are stored here",
                        archive=True,
                        db=self,
                    )
                    if new_id:
                        self._assets_channel = new_id
                    break
                except ChannelsTooMuchError:
                    logger.warning(
                        "Database: Too many channels on account — assets channel skipped."
                    )
                    break
                except FloodWaitError as _e:
                    logger.debug(
                        "Database: FloodWait %ds before creating assets channel",
                        _e.seconds,
                    )
                    await _aio.sleep(min(_e.seconds, 10))
                except Exception:
                    if _attempt < 2:
                        await _aio.sleep(2)
                    else:
                        raise
        except Exception as _exc:
            logger.debug(
                "Database: assets channel unavailable (%s) — asset storage disabled",
                _exc,
            )
            try:
                from ..core.reliability import flags as _deg_flags
                _deg_flags.mark_assets_unavailable(
                    f"{type(_exc).__name__}: {_exc}"
                )
            except Exception:
                pass
        else:
            if self._assets_channel:
                try:
                    from ..core.reliability import flags as _deg_flags
                    _deg_flags.clear_assets_unavailable()
                except Exception:
                    pass
    def get(
        self,
        owner: str,
        key: str,
        default: JSONValue = None,
    ) -> JSONValue:
        return self._data.get(owner, {}).get(key, default)
    def pointer(
        self,
        owner: str,
        key: str,
        default: JSONValue = None,
        item_type: typing.Any = None,
    ) -> JSONValue:
        return self._data.setdefault(owner, {}).setdefault(key, default)
    async def set(
        self,
        owner: str,
        key: str,
        value: JSONValue,
    ) -> bool:
        if not isinstance(owner, str):
            raise TypeError(f"owner must be str, got {type(owner).__name__}")
        if not isinstance(key, str):
            raise TypeError(f"key must be str, got {type(key).__name__}")
        if not is_serializable(value):
            raise ValueError(
                f"Value for {owner}.{key} is not JSON-serializable: {type(value).__name__}"
            )
        async with self._lock:
            old_value = self._data.get(owner, {}).get(key)
            self._data.setdefault(owner, {})[key] = value
            self._dirty.add((owner, key))
            self._deleted.discard((owner, key))
            self._maybe_snapshot(owner, key, old_value)
        self._kick_save()
        return True
    def set_sync(self, owner: str, key: str, value: JSONValue) -> bool:
        if not is_serializable(value):
            raise ValueError(f"Value for {owner}.{key} is not JSON-serializable")
        old_value = self._data.get(owner, {}).get(key)
        self._data.setdefault(owner, {})[key] = value
        self._dirty.add((owner, key))
        self._deleted.discard((owner, key))
        self._maybe_snapshot(owner, key, old_value)
        self._kick_save()
        return True
    force_set = set_sync
    def clear(self) -> bool:
        for owner, sub in list(self._data.items()):
            for key in list(sub.keys()):
                self._deleted.add((owner, key))
        self._data.clear()
        self._dirty.clear()
        try:
            self._kick_save()
        except RuntimeError:
            pass
        return True
    async def delete(self, owner: str, key: str) -> bool:
        async with self._lock:
            if owner in self._data and key in self._data[owner]:
                old_value = self._data[owner][key]
                del self._data[owner][key]
                if not self._data[owner]:
                    del self._data[owner]
                self._maybe_snapshot(owner, key, old_value)
            self._dirty.discard((owner, key))
            self._deleted.add((owner, key))
        self._kick_save()
        return True
    async def remove(self, owner: str, key: str) -> bool:
        return await self.delete(owner, key)
    async def force_save(self) -> bool:
        if self._backend is None:
            return False
        if self._pending_save and not self._pending_save.done():
            self._pending_save.cancel()
            try:
                await self._pending_save
            except (asyncio.CancelledError, Exception):
                pass
        async with self._lock:
            dirty = list(self._dirty)
            deleted = list(self._deleted)
            self._dirty.clear()
            self._deleted.clear()
        if isinstance(self._backend, SQLiteBackend):
            upsert_rows = []
            for owner, key in dirty:
                val = self._data.get(owner, {}).get(key)
                if val is not None or (owner in self._data and key in self._data[owner]):
                    upsert_rows.append((owner, key, json_dumps(val)))
            loop = asyncio.get_event_loop()
            ok = await loop.run_in_executor(
                None, self._backend.upsert_sync, upsert_rows, deleted
            )
            return bool(ok)
        else:
            async with self._lock:
                snapshot = {o: dict(s) for o, s in self._data.items()}
            try:
                ok = await self._backend.save(snapshot)
                if ok:
                    self._redis_fail_streak = 0
                    return True
                self._redis_fail_streak += 1
            except Exception:
                self._redis_fail_streak += 1
                logger.warning(
                    "Database: Redis save failed (streak=%d)",
                    self._redis_fail_streak,
                )
            if self._redis_fail_streak >= self._REDIS_FAIL_THRESHOLD:
                self._switch_to_sqlite_fallback()
                return await self._save_sqlite_fallback(dirty, deleted)
            return False
    async def shutdown(self) -> None:
        await self.force_save()
        if isinstance(self._backend, SQLiteBackend):
            self._backend.close()
        if self._sqlite_fallback is not None and self._sqlite_fallback is not self._backend:
            try:
                self._sqlite_fallback.close()
            except Exception:
                pass
    def _switch_to_sqlite_fallback(self) -> None:
        if isinstance(self._backend, SQLiteBackend):
            return
        if self._sqlite_fallback is None:
            try:
                self._sqlite_fallback = SQLiteBackend(self._sqlite_path)
            except Exception:
                logger.exception("Database: cannot create SQLite fallback")
                return
        old_backend = self._backend
        self._backend = self._sqlite_fallback
        logger.warning(
            "Database: switched to SQLite fallback after %d Redis failures",
            self._redis_fail_streak,
        )
        try:
            from ..core.reliability import flags as _deg_flags
            _deg_flags.mark_redis_unavailable(
                f"{self._redis_fail_streak} consecutive save failures",
            )
        except Exception:
            pass
        try:
            old_redis = getattr(old_backend, "_redis", None)
            if old_redis is not None:
                old_redis.close()
        except Exception:
            pass
    async def _save_sqlite_fallback(
        self,
        dirty: list[tuple[str, str]],
        deleted: list[tuple[str, str]],
    ) -> bool:
        backend = self._sqlite_fallback if isinstance(self._sqlite_fallback, SQLiteBackend) else (
            self._backend if isinstance(self._backend, SQLiteBackend) else None
        )
        if backend is None:
            return False
        upsert_rows: list[tuple[str, str, str]] = []
        for owner, key in dirty:
            val = self._data.get(owner, {}).get(key)
            if val is not None or (owner in self._data and key in self._data[owner]):
                upsert_rows.append((owner, key, json_dumps(val)))
        loop = asyncio.get_event_loop()
        try:
            ok = await loop.run_in_executor(
                None, backend.upsert_sync, upsert_rows, deleted,
            )
            return bool(ok)
        except Exception:
            logger.exception("Database: SQLite fallback save failed")
            return False
    @property
    def assets_available(self) -> bool:
        return bool(self._assets_channel)
    async def store_asset(self, message: typing.Any) -> int | None:
        from telethon.tl.types import Message
        if not self._assets_channel:
            logger.debug("Database.store_asset: assets channel unavailable, skipping")
            return None
        try:
            if isinstance(message, Message):
                sent = await self._client.send_message(self._assets_channel, message)
            else:
                sent = await self._client.send_message(
                    self._assets_channel, file=message, force_document=True
                )
            return sent.id
        except Exception as exc:
            logger.warning(
                "Database.store_asset: failed (%s: %s) — returning None",
                type(exc).__name__, exc,
            )
            try:
                from ..core.reliability import flags as _deg_flags
                _deg_flags.mark_assets_unavailable(f"store: {type(exc).__name__}")
            except Exception:
                pass
            return None
    async def fetch_asset(self, asset_id: int) -> typing.Any | None:
        if not self._assets_channel:
            logger.debug("Database.fetch_asset: assets channel unavailable")
            return None
        try:
            msgs = await self._client.get_messages(self._assets_channel, ids=[asset_id])
            return msgs[0] if msgs else None
        except Exception as exc:
            logger.warning(
                "Database.fetch_asset(%s) failed: %s: %s",
                asset_id, type(exc).__name__, exc,
            )
            return None
    def export_data(self) -> dict:
        return {owner: dict(sub) for owner, sub in self._data.items()}
    def _maybe_snapshot(self, owner: str, key: str, old_value: JSONValue) -> None:
        now = time.monotonic()
        if not self._revisions or now - self._revisions[-1][0] >= self._REVISION_INTERVAL:
            self._revisions.append((now, []))
            while len(self._revisions) > self._MAX_REVISIONS:
                self._revisions.pop(0)
        self._revisions[-1][1].append((owner, key, old_value))
    def _kick_save(self) -> None:
        if self._pending_save and not self._pending_save.done():
            self._pending_save.cancel()
        task = asyncio.ensure_future(self._schedule_save())
        self._pending_save = task
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
    async def _schedule_save(self) -> None:
        try:
            await asyncio.sleep(self._save_delay())
        except asyncio.CancelledError:
            return
        if not self._backend:
            return
        if isinstance(self._backend, SQLiteBackend):
            async with self._lock:
                dirty = list(self._dirty)
                deleted = list(self._deleted)
                self._dirty.clear()
                self._deleted.clear()
            if not dirty and not deleted:
                return
            upsert_rows = []
            for owner, key in dirty:
                val = self._data.get(owner, {}).get(key)
                if val is not None or (owner in self._data and key in self._data[owner]):
                    upsert_rows.append((owner, key, json_dumps(val)))
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self._backend.upsert_sync, upsert_rows, deleted
            )
        else:
            async with self._lock:
                snapshot_dirty = list(self._dirty)
                snapshot_deleted = list(self._deleted)
                snapshot = {o: dict(s) for o, s in self._data.items()}
                self._dirty.clear()
                self._deleted.clear()
            try:
                ok = await self._backend.save(snapshot)
                if ok:
                    self._redis_fail_streak = 0
                    return
                self._redis_fail_streak += 1
            except Exception:
                self._redis_fail_streak += 1
                logger.warning(
                    "Database: Redis scheduled save failed (streak=%d)",
                    self._redis_fail_streak,
                )
            if self._redis_fail_streak >= self._REDIS_FAIL_THRESHOLD:
                self._switch_to_sqlite_fallback()
                await self._save_sqlite_fallback(snapshot_dirty, snapshot_deleted)
    def __contains__(self, item: object) -> bool:
        return item in self._data
    def __getitem__(self, item: str) -> dict:
        return self._data[item]
    def __repr__(self) -> str:
        return f"<DatabaseManager owners={list(self._data.keys())}>"
