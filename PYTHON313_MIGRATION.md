# 🐍 Kitsune Userbot — переход на Python 3.13

## Что изменилось

| Файл | Изменение |
|------|-----------|
| `pyproject.toml` | `requires-python = ">=3.13"` (было `>=3.10`) |
| `pyproject.toml` | `[tool.black] target-version = ["py313"]` |
| `pyproject.toml` | `[tool.ruff] target-version = "py313"` |
| `pyproject.toml` | `[tool.mypy] python_version = "3.13"` |
| `pyproject.toml` | `build-backend` исправлен на `setuptools.build_meta` (был несуществующий `setuptools.backends.legacy:build`) |
| `pyproject.toml` | Добавлены `classifiers` для PyPI с явным указанием Python 3.13 |
| `Dockerfile` | `FROM python:3.13-slim` (было `python:3.12-slim`) |
| `install.sh` | Приоритет `python3.13 → python3.12 → python3.11` |
| `install.sh` | Минимальная версия `>= 3.13` (с graceful fallback на 3.12) |
| `install.sh` | Auto-add deadsnakes PPA на Ubuntu, если 3.13 недоступен |
| `kitsune/__main__.py` | Подавление шумных `DeprecationWarning` от `asyncio.get_event_loop()` (актуально для 3.12+) |
| `kitsune/__main__.py` | Защитная проверка минимальной версии Python при запуске |

## Что НЕ требовало изменений

- ✅ `from __future__ import annotations` стоит во всех ключевых модулях
- ✅ Нет deprecated `@asyncio.coroutine`, `asyncio.async`
- ✅ Нет использования удалённых в 3.13 модулей (`distutils`, `imp`, `aifc`, `chunk`, `crypt`, `nis`, `ossaudiodev`, `sndhdr`, `spwd`, `sunau`, `telnetlib`, `uu`, `xdrlib`)
- ✅ Не используется `typing.io`, `typing.re` (удалены в 3.12)
- ✅ Pyrogram 2.0.106+, Telethon 1.36+, aiogram 3.7+, pydantic 2.7+ — все совместимы с 3.13
- ✅ TgCrypto-pyrofork собирает wheel под 3.13 (на CPython 3.13.0+)

## Замечания по `asyncio.get_event_loop()`

В коде остались 21 вызов `asyncio.get_event_loop()` (database, inline, web, modules).
В Python 3.13 они ещё работают, но генерируют `DeprecationWarning`. Шум подавлен в `__main__.py`.
**В Python 3.14** API будет удалён. Рекомендуется при следующем рефакторе заменить на:

```python
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
```

## Установка на голой системе с Python 3.13

```bash
# Ubuntu 24.04 / Debian 13
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.13 python3.13-venv python3-pip git

git clone <repo> Kitsune
cd Kitsune
bash install.sh        # авто-выберет python3.13
```

## Docker

```bash
docker build -t kitsune .
docker run -v $(pwd)/data:/data kitsune
```
