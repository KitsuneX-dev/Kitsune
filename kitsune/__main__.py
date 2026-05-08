from __future__ import annotations
import os
import sys
import warnings
from pathlib import Path

# --- Python 3.13 готовность ---
# Проверяем минимальную версию Python
if sys.version_info < (3, 10):
    print(
        "[Kitsune] ОШИБКА: требуется Python 3.10+ (рекомендован 3.13).\n"
        f"Текущая версия: {sys.version_info.major}.{sys.version_info.minor}\n",
        file=sys.stderr,
    )
    sys.exit(1)

# Подавляем шум от deprecated asyncio.get_event_loop() в 3.12+
# (останется рабочим до Python 3.14)
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r".*get_event_loop.*",
)

def _auto_venv() -> None:

    try:

        import telethon

        return

    except ImportError:

        pass

    venv_python = Path(__file__).resolve().parent.parent / "venv" / "bin" / "python3"

    if venv_python.exists() and os.path.realpath(sys.executable) != os.path.realpath(str(venv_python)):

        print(

            "[Kitsune] telethon не найден в текущем окружении.\n"

            f"[Kitsune] Перезапуск через venv: {venv_python}\n"

        )

        os.execv(str(venv_python), [str(venv_python), "-m", "kitsune"] + sys.argv[1:])

    print(

        "[Kitsune] ОШИБКА: модуль 'telethon' не найден.\n"

        "Запусти установку зависимостей:\n"

        "    pip3 install --user -r ~/Kitsune/requirements.txt\n"

        "Или используй скрипт запуска:\n"

        "    ~/start_kitsune.sh\n"

    )

_auto_venv()

from .main import main

if __name__ == "__main__":

    main()
