                                                                                    
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import sqlite3
import pytest
import pytest_asyncio
from types import SimpleNamespace
from pathlib import Path


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_kitsune.db"
@pytest.fixture
def backend(db_path):
    from kitsune.database.manager import SQLiteBackend
    be = SQLiteBackend(db_path)
    yield be
    be.close()
def run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)
class _FakeClient:
    def __init__(self, tg_id=12345):
        self.tg_id = tg_id
    async def send_message(self, *a, **kw):
        return SimpleNamespace(id=1)
    async def get_messages(self, *a, **kw):
        return []
def test_save_and_load(backend):
    data = {"owner1": {"key1": "value1", "key2": 42}}
    assert run(backend.save(data))
    loaded = run(backend.load())
    assert loaded == data
def test_empty_save_and_load(backend):
    run(backend.save({}))
    loaded = run(backend.load())
    assert loaded == {}
def test_persistent_connection(backend):
    for i in range(5):
        run(backend.save({"o": {"k": str(i)}}))
    loaded = run(backend.load())
    assert loaded["o"]["k"] == "4"
def test_close_and_reload(db_path):
    from kitsune.database.manager import SQLiteBackend
    be = SQLiteBackend(db_path)
    run(be.save({"x": {"y": 1}}))
    be.close()
    be2 = SQLiteBackend(db_path)
    loaded = run(be2.load())
    assert loaded["x"]["y"] == 1
    be2.close()
def test_json_types_roundtrip(backend):
    data = {"o": {
        "str": "hello",
        "int": 42,
        "float": 3.14,
        "bool_true": True,
        "bool_false": False,
        "none": None,
        "list": [1, 2, 3],
        "nested_dict": {"a": "b", "c": [1, 2]},
        "empty_list": [],
        "empty_dict": {},
        "unicode": "🦊 кицунэ",
    }}
    run(backend.save(data))
    loaded = run(backend.load())
    assert loaded["o"] == data["o"]
def test_upsert_updates_existing(backend):
    run(backend.save({"owner": {"k": "old"}}))
    run(backend.save({"owner": {"k": "new"}}))
    loaded = run(backend.load())
    assert loaded["owner"]["k"] == "new"
def test_upsert_sync_inserts_new_rows(backend):
    rows = [("ownerA", "k1", '"v1"'), ("ownerA", "k2", '"v2"')]
    assert backend.upsert_sync(rows, [])
    loaded = run(backend.load())
    assert loaded["ownerA"]["k1"] == "v1"
    assert loaded["ownerA"]["k2"] == "v2"
def test_upsert_sync_overwrites_existing(backend):
    backend.upsert_sync([("o", "k", '"first"')], [])
    backend.upsert_sync([("o", "k", '"second"')], [])
    loaded = run(backend.load())
    assert loaded["o"]["k"] == "second"
    conn = backend._get_conn()
    n = conn.execute("SELECT COUNT(*) FROM kitsune_db WHERE owner='o' AND key='k'").fetchone()[0]
    assert n == 1
def test_upsert_sync_deletes_keys(backend):
    backend.upsert_sync([("o", "k1", '"v1"'), ("o", "k2", '"v2"')], [])
    backend.upsert_sync([], [("o", "k1")])
    loaded = run(backend.load())
    assert "k1" not in loaded.get("o", {})
    assert loaded["o"]["k2"] == "v2"
def test_deleted_keys_removed_via_full_save(backend):
    run(backend.save({"owner": {"k1": "v1", "k2": "v2"}}))
    run(backend.save({"owner": {"k1": "v1"}}))
    loaded = run(backend.load())
    assert "k2" not in loaded.get("owner", {})
def test_wal_mode_active(backend):
    conn = backend._get_conn()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
def test_wal_files_created(db_path, backend):
    run(backend.save({"o": {"k": "v"}}))
    conn = backend._get_conn()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
def test_synchronous_mode_normal(backend):
    conn = backend._get_conn()
    sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    assert sync == 1
def test_busy_timeout_set(backend):
    conn = backend._get_conn()
    timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert timeout == 5000
def test_table_schema_correct(backend):
    conn = backend._get_conn()
    cols = conn.execute("PRAGMA table_info(kitsune_db)").fetchall()
    col_names = {c[1] for c in cols}
    assert col_names == {"owner", "key", "value"}
@pytest_asyncio.fixture
async def manager(tmp_path, monkeypatch):
    from kitsune.database import manager as dbm
    fake_root = tmp_path
    monkeypatch.setattr(dbm, "__file__", str(fake_root / "fake" / "manager.py"))
    client = _FakeClient(tg_id=99999)
    mgr = dbm.DatabaseManager(client)
    db_file = tmp_path / "kitsune-99999.db"
    mgr._backend = dbm.SQLiteBackend(db_file)
    mgr._data = await mgr._backend.load()
    yield mgr
    await mgr.shutdown()
@pytest.mark.asyncio
async def test_manager_set_and_get(manager):
    await manager.set("ns", "k", "value")
    assert manager.get("ns", "k") == "value"
@pytest.mark.asyncio
async def test_manager_get_default(manager):
    assert manager.get("missing", "k", "DEF") == "DEF"
    assert manager.get("missing", "k") is None
@pytest.mark.asyncio
async def test_manager_set_validates_types(manager):
    with pytest.raises(TypeError):
        await manager.set(123, "k", "v")                 
    with pytest.raises(TypeError):
        await manager.set("o", 456, "v")               
@pytest.mark.asyncio
async def test_manager_set_rejects_non_serializable(manager):
    class Custom:
        pass
    with pytest.raises(ValueError):
        await manager.set("o", "k", Custom())
@pytest.mark.asyncio
async def test_manager_delete(manager):
    await manager.set("ns", "k", "v")
    assert manager.get("ns", "k") == "v"
    await manager.delete("ns", "k")
    assert manager.get("ns", "k") is None
@pytest.mark.asyncio
async def test_manager_pointer_creates_default(manager):
    p = manager.pointer("ns", "list_key", default=[])
    p.append("item")
    assert manager._data["ns"]["list_key"] == ["item"]
@pytest.mark.asyncio
async def test_manager_force_save_persists(manager, tmp_path):
    await manager.set("ns", "k", "v1")
    ok = await manager.force_save()
    assert ok is True
    db_file = tmp_path / "kitsune-99999.db"
    conn = sqlite3.connect(db_file)
    rows = conn.execute("SELECT owner, key, value FROM kitsune_db").fetchall()
    conn.close()
    assert any(o == "ns" and k == "k" for o, k, _ in rows)
@pytest.mark.asyncio
async def test_manager_export_data(manager):
    await manager.set("a", "1", "x")
    await manager.set("b", "2", "y")
    snap = manager.export_data()
    assert snap == {"a": {"1": "x"}, "b": {"2": "y"}}
    snap["a"]["1"] = "MUTATED"
    assert manager.get("a", "1") == "x"
@pytest.mark.asyncio
async def test_revisions_created_on_change(manager):
    await manager.set("ns", "k", "v1")
    await manager.set("ns", "k", "v2")
    assert len(manager._revisions) >= 1
    flat = [entry for _, batch in manager._revisions for entry in batch]
    assert any(o == "ns" and k == "k" for o, k, _ in flat)
@pytest.mark.asyncio
async def test_revisions_capture_old_values(manager):
    await manager.set("ns", "k", "original")
    await manager.set("ns", "k", "updated")
    flat = [entry for _, batch in manager._revisions for entry in batch]
    old_values = [v for o, k, v in flat if o == "ns" and k == "k"]
    assert "original" in old_values or None in old_values
@pytest.mark.asyncio
async def test_revisions_size_bounded(manager):
    from kitsune.database.manager import DatabaseManager
    manager._REVISION_INTERVAL = 0
    for i in range(DatabaseManager._MAX_REVISIONS + 10):
        await manager.set("ns", f"k{i}", i)
    assert len(manager._revisions) <= DatabaseManager._MAX_REVISIONS
@pytest.mark.asyncio
async def test_revision_rollback_manual(manager):
    await manager.set("ns", "k", "first")
    await manager.set("ns", "k", "second")
    await manager.set("ns", "k", "third")
    if manager._revisions:
        _, last_batch = manager._revisions[-1]
        for owner, key, old_val in reversed(last_batch):
            if old_val is None:
                if owner in manager._data and key in manager._data[owner]:
                    del manager._data[owner][key]
            else:
                manager._data.setdefault(owner, {})[key] = old_val
    cur = manager.get("ns", "k")
    assert cur != "third" or cur is None
@pytest.mark.asyncio
async def test_shutdown_persists_data(tmp_path):
    from kitsune.database import manager as dbm
    client = _FakeClient(tg_id=77777)
    mgr = dbm.DatabaseManager(client)
    db_file = tmp_path / "kitsune-77777.db"
    mgr._backend = dbm.SQLiteBackend(db_file)
    await mgr.set("ns", "before_shutdown", "preserved")
    await mgr.shutdown()
    conn = sqlite3.connect(db_file)
    rows = conn.execute(
        "SELECT value FROM kitsune_db WHERE owner='ns' AND key='before_shutdown'"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert "preserved" in rows[0][0]
@pytest.mark.asyncio
async def test_shutdown_cancels_pending_save(tmp_path):
    from kitsune.database import manager as dbm
    client = _FakeClient(tg_id=66666)
    mgr = dbm.DatabaseManager(client)
    db_file = tmp_path / "kitsune-66666.db"
    mgr._backend = dbm.SQLiteBackend(db_file)
    for i in range(20):
        await mgr.set("bulk", f"k{i}", i)
    await mgr.shutdown()
    pending = [t for t in mgr._bg_tasks if not t.done()]
    assert pending == []
@pytest.mark.asyncio
async def test_shutdown_idempotent(tmp_path):
    from kitsune.database import manager as dbm
    client = _FakeClient(tg_id=55555)
    mgr = dbm.DatabaseManager(client)
    db_file = tmp_path / "kitsune-55555.db"
    mgr._backend = dbm.SQLiteBackend(db_file)
    await mgr.set("ns", "k", "v")
    await mgr.shutdown()
    try:
        await mgr.shutdown()
    except Exception as e:
        pytest.fail(f"Double shutdown raised: {e}")
@pytest.mark.asyncio
async def test_set_sync_works(tmp_path):
    from kitsune.database import manager as dbm
    client = _FakeClient(tg_id=44444)
    mgr = dbm.DatabaseManager(client)
    db_file = tmp_path / "kitsune-44444.db"
    mgr._backend = dbm.SQLiteBackend(db_file)
    mgr.set_sync("ns", "k", "sync_value")
    assert mgr.get("ns", "k") == "sync_value"
    await asyncio.sleep(0.4)
    await mgr.shutdown()
@pytest.mark.asyncio
async def test_dunder_methods(manager):
    await manager.set("foo", "bar", 1)
    assert "foo" in manager
    assert manager["foo"]["bar"] == 1
    rep = repr(manager)
    assert "foo" in rep
    assert "DatabaseManager" in rep
