"""Smoke-тесты для kitsune/database/manager.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import pytest
import pathlib

@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_kitsune.db"

@pytest.fixture
def backend(db_path):
    from kitsune.database.manager import SQLiteBackend
    return SQLiteBackend(db_path)

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)

def test_save_and_load(backend):
    data = {"owner1": {"key1": "value1", "key2": 42}}
    assert run(backend.save(data))
    loaded = run(backend.load())
    assert loaded == data

def test_upsert_updates_existing(backend):
    data1 = {"owner": {"k": "old"}}
    data2 = {"owner": {"k": "new"}}
    run(backend.save(data1))
    run(backend.save(data2))
    loaded = run(backend.load())
    assert loaded["owner"]["k"] == "new"

def test_deleted_keys_removed(backend):
    data1 = {"owner": {"k1": "v1", "k2": "v2"}}
    run(backend.save(data1))
    data2 = {"owner": {"k1": "v1"}}  # k2 удалён
    run(backend.save(data2))
    loaded = run(backend.load())
    assert "k2" not in loaded.get("owner", {})

def test_empty_save(backend):
    run(backend.save({}))
    loaded = run(backend.load())
    assert loaded == {}

def test_persistent_connection(backend):
    """Соединение переиспользуется, не падает при повторных вызовах."""
    for i in range(5):
        run(backend.save({"o": {"k": str(i)}}))
    loaded = run(backend.load())
    assert loaded["o"]["k"] == "4"

def test_close(backend):
    run(backend.save({"x": {"y": 1}}))
    backend.close()
    # После close должна открыться снова
    loaded = run(backend.load())
    assert loaded["x"]["y"] == 1

def test_json_types(backend):
    data = {"o": {
        "str": "hello",
        "int": 42,
        "float": 3.14,
        "bool": True,
        "none": None,
        "list": [1, 2, 3],
        "dict": {"a": "b"},
    }}
    run(backend.save(data))
    loaded = run(backend.load())
    assert loaded["o"] == data["o"]
