<div align="center">

```
██╗  ██╗██╗████████╗███████╗██╗   ██╗███╗   ██╗███████╗
██║ ██╔╝██║╚══██╔══╝██╔════╝██║   ██║████╗  ██║██╔════╝
█████╔╝ ██║   ██║   ███████╗██║   ██║██╔██╗ ██║█████╗
██╔═██╗ ██║   ██║   ╚════██║██║   ██║██║╚██╗██║██╔══╝
██║  ██╗██║   ██║   ███████║╚██████╔╝██║ ╚████║███████╗
╚═╝  ╚═╝╚═╝   ╚═╝   ╚══════╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝
```

**Быстрый · Стабильный · Современный Telegram Userbot**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-AGPLv3-blue?style=flat-square)](LICENSE)
[![Telegram](https://img.shields.io/badge/Developer-@Mikasu32-2CA5E0?style=flat-square&logo=telegram)](https://t.me/Mikasu32)

</div>

---

## Что такое Kitsune?

Kitsune — это userbot для Telegram, написанный на Python. Он запускается локально на твоём устройстве и значительно расширяет возможности Telegram: автоматизация, утилиты, управление группами, резервные копии и многое другое — всё через простые команды с префиксом.

---

## Возможности

| Функция | Описание |
|---|---|
| Двойной стек | Telethon (основной) + Hydrogram (вторичный) |
| Шифрование сессии | Session-файл шифруется через AES-128 (Fernet) — в покое не читается |
| AST-сканер | Безопасная загрузка модулей — блокирует опасный код до `exec()` |
| Rate Limiter | Token-bucket алгоритм — защита от флуд-бана |
| Async SQLite WAL | Не теряет данные при крэше, WAL journal mode |
| aiogram 3.x | Встроенный бот для уведомлений и бэкапов |
| Авто-бэкап | Зашифрованные резервные копии БД в группу KitsuneBackup |
| Авто-удаление | Сервисные сообщения удаляются через заданное время |
| Прогресс-бар | Визуальный прогресс для длинных операций |
| TOML конфиг | Читаемый конфиг с кэшированием |
| Termux + Ubuntu | Один установщик для обоих окружений |

---

## Встроенные модули

| Модуль | Команды | Описание |
|---|---|---|
| Backup | `.backup` `.restore` | Зашифрованные резервные копии БД, авто-бэкап по расписанию |
| Evaluator | `.e` `.ex` `.sh` | Выполнение Python / Shell кода |
| Health | `.health` `.monitor` | Мониторинг системы |
| Help | `.help` | Список команд и модулей |
| Loader | `.dlmod` `.loadmod` `.mods` | Управление модулями |
| Notifier | `.resetbot` `.mybots` `.setbot` | Бот-нотификатор |
| Pastebin | `.paste` | Загрузка текста на pastebin |
| Ping | `.ping` `.me` `.id` | Пинг, аптайм, информация |
| Security | `.addsudo` `.delsudo` | Управление правами доступа |
| Settings | `.prefix` `.lang` `.autodel` `.info` | Настройки юзербота |
| Updater | `.update` `.restart` | Обновление и перезапуск |

---

## Установка

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
docker build -t kitsune .
docker run -d --name kitsune -v $(pwd)/data:/data kitsune
```

### Вручную
```bash
git clone https://github.com/KitsuneX-dev/Kitsune
cd Kitsune
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m kitsune
```

После запуска открой `http://localhost:8080` в браузере, введи `api_id` и `api_hash` — и готово.

---

## Конфигурация

```toml
api_id   = 123456
api_hash = "abcdef..."
prefix   = "."
lang     = "ru"

[proxy]
type   = "MTPROTO"
host   = "127.0.0.1"
port   = 443
secret = "00000000000000000000000000000000"
```

`api_id` и `api_hash` получи на [my.telegram.org](https://my.telegram.org). Блок `[proxy]` опционален.

---

## Загрузка модулей

```
.dlmod https://raw.githubusercontent.com/someone/repo/main/mymodule.py
```

Все загружаемые модули проходят AST-сканирование перед выполнением. Загруженные модули восстанавливаются автоматически после перезапуска.

---

## Безопасность

**Шифрование сессии**

Session-файл шифруется через Fernet (AES-128-CBC) сразу после авторизации и при каждом выключении бота. На диске в состоянии покоя хранится только `kitsune.session.enc` — нечитаемый без ключа.

**Шифрование бэкапов**

Все бэкапы зашифрованы тем же алгоритмом Fernet. Ключ хранится локально в `~/.kitsune/kitsune.key` и никогда не покидает твоё устройство.

> Сохрани `~/.kitsune/kitsune.key` в безопасном месте. Без него расшифровать сессию и бэкапы невозможно.

При первом запуске бот предложит выбрать интервал авто-бэкапа (2ч / 4ч / 6ч / 12ч / 24ч). Бэкапы отправляются в группу **KitsuneBackup** в виде файлов `.kbak`.

Восстановление — ответь на файл бэкапа командой `.restore`.

---

## Структура проекта

```
Kitsune/
├── kitsune/
│   ├── core/           диспетчер, загрузчик, security, rate limiter
│   ├── database/       SQLite и Redis backends
│   ├── modules/        встроенные модули
│   ├── web/            веб-интерфейс настройки
│   ├── inline/         inline-бот
│   ├── crypto.py       шифрование бэкапов и сессии (Fernet)
│   ├── session_enc.py  управление зашифрованной сессией
│   ├── main.py         точка входа
│   └── utils.py        вспомогательные функции
├── requirements.txt
└── install.sh
```

---

## Лицензия

AGPLv3 © Yushi ([@Mikasu32](https://t.me/Mikasu32)), 2024–2026
