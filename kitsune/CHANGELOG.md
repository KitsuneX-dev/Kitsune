# Changelog

All notable changes to Kitsune Userbot are documented here.

---

## [1.2.7] — 2026-04-10

### ⚡ Performance
- SQLite: UPSERT вместо DELETE+INSERT — обновляется только изменившееся
- SQLite: PRAGMA `cache_size` / `temp_store` / `mmap_size` — быстрее I/O
- SQLite: постоянное соединение вместо open/close на каждый запрос
- Core: параллельная загрузка модулей через `asyncio.gather`

### 🔒 Security
- `crypto.py`: XOR-fallback заменён на AES-256-GCM, обратная совместимость сохранена
- AST-сканер: блокирует `getattr(__import__)`, `eval(переменная)`, динамические `__import__`

### 🐛 Fixes
- `RateLimiter`: исправлена утечка памяти — bucket удаляется через 1ч простоя
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

### 🔧 Misc
- `.gitignore`: добавлены `__pycache__`, `*.session`, `*.session.enc`, `*.key`, `*.db`, `*.db-shm`, `*.db-wal`
- `requirements.txt`: зафиксированы верхние границы версий (`>=X,<Y`) для всех зависимостей
- `CHANGELOG.md`: создан с полной историей v1.2.1 → v1.2.7
- `install.sh`: добавлен блок `chmod` для `~/.kitsune` и всех файлов сессии

---

## [1.2.6] — 2026-04-06

### Inline
- `inline/list.py` — пагинированные списки с кнопками ◀️ ▶️
- `inline/utils.py` — хелперы: `nav_row()`, `close_button()`, `make_progress_bar()`, `safe_edit()`
- `inline/events.py` — `BotInlineCall`, `BotInlineMessage`, `FSMState`
- `inline/bot_pm.py` — FSM-диалоги через ЛС бота (`ask()`)
- `inline/query_gallery.py` — медиа-галерея через `@bot query`

### Ядро
- `_internal.py` — `restart()`, `die()`, `print_banner()`, `get_platform()`
- `configurator.py` — интерактивный TTY-конфигуратор первого запуска
- `_local_storage.py` — локальное JSON-хранилище независимое от БД
- `utils/` — монолитный `utils.py` разбит на `args`, `entity`, `git`, `platform`

### Web
- `web/ssh_tunnel.py` — SSH-туннели через serveo.net / localhost.run
- `web/proxypass.py` — оркестрация туннелей с уведомлением об URL

### Прочее
- `modules/quickstart.py` — онбординг при первой установке
- `qr.py` — генерация QR без внешних зависимостей (текст + PNG через Pillow)
- `requirements.txt` — объединён с `optional_requirements.txt`

---

## [1.2.5] — 2026-04-01

### 🔒 Security
- Полная переработка модуля security — `.addsudo` / `.delsudo` / `.owneradd` теперь реально работают
- Диспатчер теперь обрабатывает входящие команды от sudo-пользователей и совладельцев
- Добавлена команда `.checkperms` — проверить права любого пользователя

### ✨ Features
- Startup banner — при запуске в канал Kitsune-logs отправляется GIF с информацией
  о версии, коммите и статусе обновлений
- Новый веб-интерфейс — три вкладки: Главная, Устройства (активные сессии),
  Информация (CPU / RAM / Диск), обновляется каждые 5 секунд без перезагрузки
- Новые модули: `terminal` (`.term` / `.sh`) и `weather` (`.weather`)

### 🏗 Architecture
- Добавлены `_types.py`, `events.py` (EventBus), `pointers.py` (умные ссылки на БД)
- `utils_additions.py` влит в `utils.py`, код стал чище
- `validators.py` подключён к `ConfigValue` — валидация конфига теперь работает

### 🐛 Fixes
- Исправлена ошибка SSL `CERTIFICATE_VERIFY_FAILED` в aiogram (notifier)
- Исправлен `AttributeError: Loader has no attribute 'modules'`
- Исправлен `AttributeError: _command_name` в модуле help
- Исправлена потеря `init()` в `log.py`

---

## [1.2.4] — 2026-03-20

### ✨ Новое
- Модуль `config` — интерактивное меню настройки модулей с inline-кнопками прямо в чате
- `.owneradd` теперь требует подтверждения через кнопки в боте
- Hydrogram используется для быстрой передачи файлов (бэкапы, загрузка модулей)

### 🔧 Улучшения
- `InlineManager` запускается автоматически вместе с ботом-нотификатором
- Кнопки обновления отображают пошаговый статус (скачиваю → устанавливаю → перезапускаю)
- При ошибке сети во время обновления — автоматически 3 попытки с паузой 15 сек

### 🐛 Fixes
- Кнопка "Обновить" в авто-уведомлении работает без команды `.update`
- Версия в уведомлении теперь показывает реальный номер (1.2.3 → 1.2.4)

---

## [1.2.3] — 2026-03-18

### ✨ Новое
- `backupdb` / `restoredb` — переименованы команды бэкапа БД
- `backupmods` / `restoremods` — бэкап и восстановление пользовательских модулей
- `owneradd` / `ownerrm` / `ownerlist` — управление совладельцами бота
- `lm` / `dlm` — короткие алиасы для `loadmod` и `dlmod`
- Новый модуль `info` — команды `info` / `setinfo` / `resetinfo`

### 🔧 Улучшения
- Системные модули помечены ◼️ в `.help`, пользовательские ▫️
- Ping → Tester в выводе `.help`
- Уведомление об обновлении теперь двуязычное (RU + EN) с пошаговым статусом установки
- Keepalive: автоматическое переподключение при смене IP / VPN
- Watchdog: автоперезапуск polling бота при SSL/timeout ошибках

### 🐛 Fixes
- Права на session-файл исправлены (readonly → read-write)
- Обновлён дизайн веб-интерфейса setup и dashboard

---

## [1.2.1] — 2026-03-01

### ✨ Новое
- Шифрование session-файла через Fernet (AES-128) — сессия хранится
  зашифрованной в покое
- Новый модуль `session_enc.py` — автоматически шифрует/расшифровывает
  сессию при старте и выключении

### 🔧 Улучшения
- Обновлён дизайн `README.md` — баннер, бейджи, улучшенные разделы
- Дизайн веб-интерфейса настройки (setup) переработан в тёмном стиле
- Дизайн основного веб-дашборда с отображением CPU и RAM

### 🐛 Fixes
- Права на расшифрованный session-файл исправлены (0o600 → 0o644)
