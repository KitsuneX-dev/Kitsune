# 🦊 Kitsune Userbot

<p align="center">
  <b>Быстрый · Стабильный · Современный Telegram Userbot</b><br>
  <sub>Developer: <a href="https://t.me/Mikasu32">Yushi (@Mikasu32)</a></sub>
</p>

---

## ✨ Особенности

| Функция | Описание |
|---|---|
| **Двойной стек** | Telethon (основной) + Hydrogram (вторичный) |
| **Безопасная загрузка** | AST-сканирование модулей перед exec() |
| **Rate Limiter** | Token-bucket алгоритм — защита от флуд-бана |
| **Async SQLite WAL** | Не теряет данные при крэше |
| **aiogram 3.x** | Современный inline-бот без legacy API |
| **TOML конфиг** | Читаемый, поддерживает комментарии |
| **Hikka-совместимость** | Большинство Hikka-модулей работают без изменений |
| **Termux + Ubuntu** | Один установщик для обоих окружений |

---

## 🚀 Установка

### Termux (Android)
```bash
curl -s https://raw.githubusercontent.com/KitsuneX-dev/Kitsune/main/termux.sh | bash
```

### Ubuntu / Debian
```bash
curl -s https://raw.githubusercontent.com/KitsuneX-dev/Kitsune/main/install.sh | bash
```

### Docker
```bash
git clone https://github.com/KitsuneX-dev/Kitsune
cd Kitsune
# Отредактируй config.toml
docker build -t kitsune .
docker run -d --name kitsune -v $(pwd)/data:/data kitsune
```

### Вручную
```bash
git clone https://github.com/KitsuneX-dev/Kitsune
cd Kitsune
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install hydrogram tgcrypto   # опционально
cp config.toml.example config.toml   # заполни api_id и api_hash
python -m kitsune
```

---

## ⚙️ Конфигурация

Отредактируй `config.toml` перед первым запуском:

```toml
api_id   = 123456          # https://my.telegram.org
api_hash = "abcdef..."
prefix   = "."
lang     = "ru"
```

---

## 📦 Встроенные модули

| Модуль | Команды | Описание |
|---|---|---|
| `help` | `.help [модуль]` | Список команд |
| `eval` | `.e` `.ex` `.sh` | Python eval/exec и shell |
| `loader` | `.loadmod` `.unloadmod` `.mods` | Управление модулями |
| `settings` | `.prefix` `.lang` `.info` | Настройки |
| `security` | `.addsudo` `.delsudo` `.sudolist` | Права доступа |
| `updater` | `.update` `.restart` | Обновление и перезапуск |

---

## 🔌 Загрузка сторонних модулей

```
.loadmod https://raw.githubusercontent.com/someone/repo/main/mymodule.py
```

Все загружаемые модули проходят AST-сканирование на безопасность.

---

## 🏗 Структура проекта

```
Kitsune/
├── kitsune/
│   ├── core/
│   │   ├── dispatcher.py    # маршрутизация команд + rate limiting
│   │   ├── loader.py        # загрузчик модулей с AST-сканом
│   │   ├── security.py      # проверка прав доступа
│   │   └── rate_limiter.py  # token-bucket лимитер
│   ├── database/
│   │   └── manager.py       # async SQLite WAL + Redis backend
│   ├── inline/
│   │   ├── core.py          # aiogram 3.x inline менеджер
│   │   └── types.py         # типы для inline кнопок
│   ├── web/
│   │   └── core.py          # aiohttp веб-интерфейс
│   ├── compat/
│   │   ├── hikka.py         # Hikka-совместимость
│   │   └── pyroproxy.py     # pyrogram → hydrogram прокси
│   ├── modules/             # встроенные модули
│   ├── langpacks/           # переводы (ru, en, de)
│   ├── main.py              # точка входа
│   ├── log.py               # async logging
│   ├── utils.py             # утилиты
│   └── tl_cache.py          # кастомный Telethon клиент
├── install.sh               # установщик Ubuntu/Termux
├── termux.sh                # установщик Termux
├── Dockerfile
├── config.toml              # конфигурация
└── requirements.txt
```

---

## 📝 Создание модуля

```python
from kitsune.core.loader import KitsuneModule, command
from kitsune.core.security import OWNER

class MyModule(KitsuneModule):
    name        = "mymodule"
    description = "Мой первый модуль"
    author      = "Yushi"

    strings_ru = {
        "hello": "👋 Привет, {name}!",
    }

    @command("hello", required=OWNER)
    async def hello_cmd(self, event):
        """.hello — поприветствовать себя"""
        me = await self.client.get_me()
        await event.reply(
            self.strings("hello").format(name=me.first_name),
            parse_mode="html",
        )
```

Сохрани в `~/.kitsune/modules/mymodule.py` — загрузится автоматически.

---

## 📄 Лицензия

AGPLv3 © Yushi (@Mikasu32), 2024-2025
