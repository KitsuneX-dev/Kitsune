"""
Точка входа: python3 -m kitsune

Фикс #2: если telethon не найден в текущем окружении (пользователь запустил
системным python3 вместо venv), автоматически перезапускаемся через
<INSTALL_DIR>/venv/bin/python3, где зависимости уже установлены.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _auto_venv() -> None:
    """Перезапускает процесс через venv-python, если telethon недоступен."""
    try:
        import telethon  # noqa: F401 — просто проверяем наличие
        return  # всё хорошо, зависимости найдены
    except ImportError:
        pass

    # Ищем venv относительно каталога пакета (../venv/bin/python3)
    venv_python = Path(__file__).resolve().parent.parent / "venv" / "bin" / "python3"
    if venv_python.exists() and os.path.realpath(sys.executable) != os.path.realpath(str(venv_python)):
        print(
            "[Kitsune] telethon не найден в текущем окружении.\n"
            f"[Kitsune] Перезапуск через venv: {venv_python}\n"
        )
        os.execv(str(venv_python), [str(venv_python), "-m", "kitsune"] + sys.argv[1:])
        # os.execv заменяет процесс — сюда мы не вернёмся.
        # Если вдруг не удалось (редкость) — упадём дальше с понятной ошибкой.

    # venv не найден или мы УЖЕ в venv — выводим подсказку и продолжаем.
    print(
        "[Kitsune] ОШИБКА: модуль 'telethon' не найден.\n"
        "Запусти установку зависимостей:\n"
        "    pip3 install --user -r ~/Kitsune/requirements.txt\n"
        "Или используй скрипт запуска:\n"
        "    ~/start_kitsune.sh\n"
    )


_auto_venv()

from .main import main  # noqa: E402

if __name__ == "__main__":
    main()
