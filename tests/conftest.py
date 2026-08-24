
from __future__ import annotations

import importlib
import os
import sys
import typing
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class FakeDB:

    def __init__(self, lang: str = "ru") -> None:
        self._lang = lang
        self.store: dict[str, dict[str, typing.Any]] = {}
        self.set_sync_calls = 0
        self.async_set_calls = 0
        self.force_save_calls = 0
        self.deleted: list[tuple[str, str]] = []

    def get(self, owner: str, key: str, default: typing.Any = None) -> typing.Any:
        bucket = self.store.get(owner, {})
        if key in bucket:
            return bucket[key]
        if owner == "kitsune.core" and key == "lang":
            return self._lang
        return default

    def set_sync(self, owner: str, key: str, value: typing.Any) -> bool:
        self.set_sync_calls += 1
        self.store.setdefault(owner, {})[key] = value
        return True

    force_set = set_sync

    async def set(self, owner: str, key: str, value: typing.Any) -> bool:
        self.async_set_calls += 1
        self.store.setdefault(owner, {})[key] = value
        return True

    async def delete(self, owner: str, key: str) -> bool:
        self.deleted.append((owner, key))
        self.store.get(owner, {}).pop(key, None)
        return True

    async def remove(self, owner: str, key: str) -> bool:
        return await self.delete(owner, key)

    async def force_save(self) -> None:
        self.force_save_calls += 1
        return None


@pytest.fixture()
def fake_db_factory() -> typing.Callable[..., FakeDB]:
    return FakeDB


@pytest.fixture()
def fake_db() -> FakeDB:
    return FakeDB()


@pytest.fixture()
def fake_client() -> MagicMock:
    client = MagicMock()
    client.tg_id = 12345
    client.tg_me = None
    client.inline = None
    client._kitsune_dispatcher = None
    client._kitsune_loader = None
    client._kitsune_translator = None
    client.get_me = AsyncMock(return_value=None)
    client.send_message = AsyncMock()
    return client


@pytest.fixture()
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> typing.Iterator[Path]:
    monkeypatch.setenv("KITSUNE_DATA_DIR", str(tmp_path))
    sys.modules.pop("kitsune.paths", None)
    import kitsune.paths as paths
    importlib.reload(paths)
    try:
        yield tmp_path
    finally:
        monkeypatch.delenv("KITSUNE_DATA_DIR", raising=False)
        sys.modules.pop("kitsune.paths", None)
        import kitsune.paths as paths_after
        importlib.reload(paths_after)
