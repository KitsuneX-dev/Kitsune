"""
kitsune/_local_storage.py — локальное файловое хранилище.

Отличается от DatabaseManager тем, что:
  1. Хранит данные на диске рядом с кодом (не в ~/.kitsune/kitsune.db)
  2. Не требует Telegram-клиента
  3. Синхронное API — удобно для конфигурации на старте
  4. Поддерживает неймспейсы (секции) как в DB

Используется для:
  - кэша токенов бота перед запуском клиента
  - хранения installer-флагов (первый запуск, миграции)
  - runtime-данных которые не должны попасть в Telegram-бэкап

Расположение: ~/.kitsune/local_storage.json
"""

from __future__ import annotations

import json
import logging
import os
import threading
import typing
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path.home() / ".kitsune" / "local_storage.json"


class LocalStorage:
    """
    Простое JSON-хранилище с неймспейсами.

    API намеренно совпадает с DatabaseManager.get / .set / .delete
    чтобы код модулей мог работать с обоими без изменений.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path  = Path(path) if path else _DEFAULT_PATH
        self._lock  = threading.Lock()
        self._data: dict[str, dict[str, typing.Any]] = {}
        self._dirty = False
        self._load()

    # ─── Чтение / Запись ──────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            self._data = {}
            return
        try:
            raw = self._path.read_text(encoding="utf-8")
            self._data = json.loads(raw)
        except Exception:
            logger.warning("LocalStorage: не удалось прочитать %s, начинаю пустым", self._path)
            self._data = {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._path)
            self._dirty = False
        except Exception:
            logger.exception("LocalStorage: ошибка сохранения в %s", self._path)

    # ─── Публичный API ────────────────────────────────────────────────────────

    def get(self, owner: str, key: str, default: typing.Any = None) -> typing.Any:
        """Получить значение из хранилища."""
        with self._lock:
            return self._data.get(owner, {}).get(key, default)

    def set(self, owner: str, key: str, value: typing.Any) -> None:
        """Сохранить значение в хранилище (сразу пишет на диск)."""
        with self._lock:
            self._data.setdefault(owner, {})[key] = value
            self._dirty = True
            self._save()

    def delete(self, owner: str, key: str) -> bool:
        """Удалить ключ. Возвращает True если ключ существовал."""
        with self._lock:
            section = self._data.get(owner, {})
            if key not in section:
                return False
            del section[key]
            if not section:
                del self._data[owner]
            self._dirty = True
            self._save()
            return True

    def clear_owner(self, owner: str) -> None:
        """Удалить весь неймспейс owner."""
        with self._lock:
            if owner in self._data:
                del self._data[owner]
                self._dirty = True
                self._save()

    def all(self, owner: str) -> dict[str, typing.Any]:
        """Получить все ключи неймспейса owner."""
        with self._lock:
            return dict(self._data.get(owner, {}))

    def keys(self, owner: str) -> list[str]:
        """Получить список ключей неймспейса."""
        with self._lock:
            return list(self._data.get(owner, {}).keys())

    def has(self, owner: str, key: str) -> bool:
        """Проверить наличие ключа."""
        with self._lock:
            return key in self._data.get(owner, {})

    def reload(self) -> None:
        """Перечитать данные с диска (если файл изменился извне)."""
        with self._lock:
            self._load()

    def flush(self) -> None:
        """Принудительно записать данные на диск."""
        with self._lock:
            if self._dirty:
                self._save()

    # ─── Контекстный менеджер для атомарных операций ──────────────────────────

    def __enter__(self) -> "LocalStorage":
        self._lock.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        if self._dirty:
            self._save()
        self._lock.release()


# Глобальный синглтон — можно использовать напрямую
_storage: LocalStorage | None = None


def get_storage(path: Path | str | None = None) -> LocalStorage:
    """Возвращает глобальный экземпляр LocalStorage."""
    global _storage
    if _storage is None:
        _storage = LocalStorage(path)
    return _storage
