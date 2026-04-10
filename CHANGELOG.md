# Changelog

All notable changes to Kitsune Userbot are documented here.

---

## [1.2.7] — 2026-04-10

### Fixed
- **sqlite3.OperationalError: attempt to write a readonly database** — добавлена функция
  `_fix_all_permissions()` которая выдаёт права на `~/.kitsune` и все файлы сессии
  при каждом старте. Если DB всё равно readonly — пересоздаётся через dump/restore.
- **Hydrogram запрашивает номер телефона в консоли** — Hydrogram больше не стартует
  если `*_hydro.session` файл отсутствует (избегает интерактивного промпта).
- **setbot не распознаёт токен** — `.setbot` теперь принимает и username и сырой токен
  напрямую. Улучшен flow через BotFather: `/mybots` → кнопка бота → кнопка API Token.
- **Веб-интерфейс в Termux** — `webbrowser.open()` больше не вызывается в Termux.
  Вместо этого выводится LAN IP для открытия в браузере телефона.
- **FilePartEmptyError при бэкапе** — позиция BytesIO буфера сохраняется перед попыткой
  отправки через Hydrogram и сбрасывается при fallback на Telethon.
- **PEER_ID_INVALID при первом бэкапе** — перед `send_document` вызывается `get_chat()`
  для кэширования entity в Hydrogram.

### Improved
- **install.sh** — добавлен блок `chmod` для `~/.kitsune` и всех файлов сессии.

---

## [1.2.6] — 2026-04-08

### Added
- Двойной клиентский стек: Telethon (основной) + Hydrogram (вспомогательный).
- `hydro_media.py` — единая точка отправки/скачивания медиа с fallback на Telethon.
- Обход РКН через автоматический подбор MTProto прокси.
- Web-интерфейс на порту 8080 для первоначальной настройки (ввод api_id / api_hash / телефона).
- Шифрование сессии: `kitsune.session` → `kitsune.session.enc` (Fernet или XOR+HMAC).
- Команды `.setbot`, `.resetbot`, `.mybots`, `.fixbot`, `.setinline`.
- Авто-создание бота через @BotFather при первом запуске.
- Авто-бэкап по расписанию (2ч / 4ч / 6ч / 12ч / 24ч).
- Модуль `rkn_bypass` — автоматический поиск рабочего MTProto прокси.
- Мультиязычность: ru / en / de.

### Changed
- `config.toml` вместо `config.json` (с автоматической миграцией).
- `SecurityManager` — кэш прав с TTL 60 сек, bitfield-права (14 уровней).

---

## [1.2.5] — 2026-04-01

### Added
- `RateLimiter` с token-bucket алгоритмом, защита от флуд-бана.
- AST-сканер модулей перед `exec()`.
- Redis backend для базы данных (опционально).
- Inline-галерея и inline-список.

### Fixed
- Падение при загрузке модуля с синтаксической ошибкой.
- Дублирование команд при перезагрузке модуля.

---

## [1.2.4] — 2026-03-20

### Added
- `DatabaseManager` с WAL-режимом SQLite и ревизиями (до 20 снапшотов).
- `backup.py` — ручной и авто-бэкап с шифрованием.
- `updater.py` — обновление через git pull с уведомлением.

---

## [1.2.1] — 2026-03-01

### Added
- Первый публичный релиз.
- Базовый набор модулей: ping, eval, help, info, terminal, settings.
- Установщики: `install.sh` (Ubuntu/Debian) и `termux.sh` (Android).
- Docker поддержка.
