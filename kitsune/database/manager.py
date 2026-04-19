from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
import typing
from pathlib import Path

logger = logging.getLogger(__name__)

JSONValue = typing.Union[
    None, bool, int, float, str,
    typing.List[typing.Any],
    typing.Dict[str, typing.Any],
]

def _is_serializable(value: typing.Any) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False

class SQLiteBackend:

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(str(self._path), timeout=10, check_same_thread=False)

            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-8000")       
            conn.execute("PRAGMA temp_store=MEMORY")      
            conn.execute("PRAGMA mmap_size=67108864")     
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
                result.setdefault(owner, {})[key] = json.loads(raw)
            return result
        except Exception:
            logger.exception("SQLite: failed to load database")
            return {}

    async def save(self, data: dict[str, dict[str, JSONValue]]) -> bool:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._save_sync, data)

    def _save_sync(self, data: dict[str, dict[str, JSONValue]]) -> bool:
        try:
            conn = self._get_conn()
            rows = [
                (owner, key, json.dumps(value, ensure_ascii=False))
                for owner, sub in data.items()
                for key, value in sub.items()
            ]

            conn.executemany(
                "INSERT INTO kitsune_db (owner, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(owner, key) DO UPDATE SET value=excluded.value",
                rows,
            )

            if rows:
                placeholders = ",".join("(?,?)" for _ in rows)
                params = [v for owner, key, _ in rows for v in (owner, key)]
                conn.execute(
                    f"DELETE FROM kitsune_db WHERE (owner, key) NOT IN ({placeholders})",
                    params,
                )
            else:
                conn.execute("DELETE FROM kitsune_db")
            conn.commit()
            return True
        except Exception:
            logger.exception("SQLite: failed to save database")
            return False

class RedisBackend:

    def __init__(self, uri: str, client_id: int) -> None:
        import redis as _redis
        self._redis = _redis.Redis.from_url(uri)
        self._key = str(client_id)
        self._lock = asyncio.Lock()

    async def load(self) -> dict[str, dict[str, JSONValue]]:
        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(None, self._redis.get, self._key)
            if raw:
                return json.loads(raw.decode())
        except Exception:
            logger.exception("Redis: failed to load")
        return {}

    async def save(self, data: dict[str, dict[str, JSONValue]]) -> bool:
        loop = asyncio.get_event_loop()
        try:
            serialized = json.dumps(data, ensure_ascii=True)
            await loop.run_in_executor(None, self._redis.set, self._key, serialized)
            logger.debug("Redis: database saved")
            return True
        except Exception:
            logger.exception("Redis: failed to save")
            return False

class DatabaseManager:

    _MAX_REVISIONS = 20
    _REVISION_INTERVAL = 3

    def __init__(self, client: typing.Any) -> None:
        self._client = client
        self._data: dict[str, dict[str, JSONValue]] = {}
        self._lock = asyncio.Lock()
        self._backend: SQLiteBackend | RedisBackend | None = None
        self._revisions: list[dict] = []
        self._next_revision_at: float = 0.0
        self._pending_save: asyncio.Task | None = None
        self._assets_channel: int | None = None

    async def init(self) -> None:
        import os as _os
        from pathlib import Path as _Path

        redis_uri = _os.environ.get("REDIS_URL")
        if not redis_uri:
            try:
                import toml as _toml
                _cfg_path = _Path(__file__).parent.parent.parent / "config.toml"
                if _cfg_path.exists():
                    _cfg = _toml.loads(_cfg_path.read_text(encoding="utf-8"))
                    redis_uri = _cfg.get("redis_uri")
            except Exception:
                pass

        if redis_uri:
            try:
                self._backend = RedisBackend(redis_uri, self._client.tg_id)
                self._data = await self._backend.load()
                logger.info("Database: Redis backend active")
            except Exception:
                logger.warning("Database: Redis unavailable, falling back to SQLite")
                self._backend = None

        if self._backend is None:
            _base = _Path(__file__).parent.parent.parent
            db_path = _base / f"kitsune-{self._client.tg_id}.db"
            self._backend = SQLiteBackend(db_path)
            self._data = await self._backend.load()
            logger.info("Database: SQLite backend active (%s)", db_path)
            # Arch Linux: после веб-регистрации файл БД может быть создан
            # от другого пользователя/root — явно выставляем права на запись
            try:
                import os as _os
                if db_path.exists():
                    _os.chmod(db_path, 0o644)
                # WAL-режим создаёт вспомогательные файлы — чиним и их
                for _suffix in ("-wal", "-shm"):
                    _aux = db_path.with_name(db_path.name + _suffix)
                    if _aux.exists():
                        _os.chmod(_aux, 0o644)
            except Exception as _chmod_exc:
                logger.warning("Database: could not chmod db file (%s)", _chmod_exc)

        try:
            from .. import utils
            from telethon.errors import ChannelsTooMuchError, FloodWaitError
            import asyncio as _aio

            for _attempt in range(3):
                try:
                    self._assets_channel, _ = await utils.asset_channel(
                        self._client,
                        "kitsune-assets",
                        "🦊 Your Kitsune assets are stored here",
                        archive=True,
                    )
                    break
                except ChannelsTooMuchError:
                    logger.warning(
                        "Database: Too many channels on account — assets channel skipped. "
                        "Delete unused channels to enable asset storage."
                    )
                    break
                except FloodWaitError as _e:
                    logger.debug("Database: FloodWait %ds before creating assets channel", _e.seconds)
                    await _aio.sleep(min(_e.seconds, 10))
                except Exception:
                    if _attempt < 2:
                        await _aio.sleep(2)
                    else:
                        raise
        except Exception as _exc:
            logger.debug("Database: assets channel unavailable (%s) — asset storage disabled", _exc)

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
        if not _is_serializable(value):
            raise ValueError(
                f"Value for {owner}.{key} is not JSON-serializable: {type(value).__name__}"
            )

        async with self._lock:
            self._data.setdefault(owner, {})[key] = value
            self._maybe_snapshot()

        self._kick_save()
        return True

    def set_sync(self, owner: str, key: str, value: JSONValue) -> bool:
        if not _is_serializable(value):
            raise ValueError(f"Value for {owner}.{key} is not JSON-serializable")
        self._data.setdefault(owner, {})[key] = value
        self._maybe_snapshot()
        self._kick_save()
        return True

    async def delete(self, owner: str, key: str) -> bool:
        async with self._lock:
            if owner in self._data and key in self._data[owner]:
                del self._data[owner][key]
                if not self._data[owner]:
                    del self._data[owner]
        self._kick_save()
        return True

    async def force_save(self) -> bool:
        if self._backend is None:
            return False
        async with self._lock:
            snapshot = dict(self._data)
        result = await self._backend.save(snapshot)

        if isinstance(self._backend, SQLiteBackend):
            self._backend.close()
        return result

    async def store_asset(self, message: typing.Any) -> int:
        from telethon.tl.types import Message
        if not self._assets_channel:
            raise RuntimeError("Assets channel not available")
        if isinstance(message, Message):
            sent = await self._client.send_message(self._assets_channel, message)
        else:
            sent = await self._client.send_message(
                self._assets_channel, file=message, force_document=True
            )
        return sent.id

    async def fetch_asset(self, asset_id: int) -> typing.Any | None:
        if not self._assets_channel:
            raise RuntimeError("Assets channel not available")
        msgs = await self._client.get_messages(self._assets_channel, ids=[asset_id])
        return msgs[0] if msgs else None

    def export_data(self) -> dict:
        """Возвращает безопасную копию всей БД для резервного копирования."""
        return {owner: dict(sub) for owner, sub in self._data.items()}

    def _maybe_snapshot(self) -> None:
        now = time.monotonic()
        if now >= self._next_revision_at:
            self._revisions.append({
                owner: dict(sub) for owner, sub in self._data.items()
            })
            self._next_revision_at = now + self._REVISION_INTERVAL
            while len(self._revisions) > self._MAX_REVISIONS:
                self._revisions.pop(0)

    def _kick_save(self) -> None:
        if self._pending_save and not self._pending_save.done():
            self._pending_save.cancel()
        self._pending_save = asyncio.ensure_future(self._schedule_save())

    async def _schedule_save(self) -> None:
        await asyncio.sleep(1)
        if self._backend:
            async with self._lock:
                snapshot = {o: dict(s) for o, s in self._data.items()}
            await self._backend.save(snapshot)

    def __contains__(self, item: object) -> bool:
        return item in self._data

    def __getitem__(self, item: str) -> dict:
        return self._data[item]

    def __repr__(self) -> str:
        return f"<DatabaseManager owners={list(self._data.keys())}>"
