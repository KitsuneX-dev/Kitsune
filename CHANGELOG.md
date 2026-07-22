# Changelog

All notable changes to Kitsune Userbot are documented here.

---

## [1.4.3] — Фиксы автоустановки зависимостей и выгрузки модулей

### 🐞 Загрузка/установка зависимостей
- **Исправлен маппинг пакета для нового Google SDK.** В `kitsune/core/loader.py`
  словарь `_IMPORT_TO_PIP` теперь связывает импорт `google` с актуальным
  пакетом **`google-genai`** (было устаревшее `google-generativeai`).
  Модули, использующие `from google import genai` (например пользовательский
  `GeminiK`), теперь корректно доустанавливают зависимость при первой загрузке.
- `google-genai` добавлен в набор namespace-пакетов (`_NAMESPACE_PKGS`)
  в `_pip_install`; старый `google-generativeai` там сохранён ради
  обратной совместимости.
- **`.sh` / терминал теперь ставит пакеты в venv бота.** В
  `kitsune/modules/terminal.py` добавлена функция `_venv_aware_env()`:
  каталог текущего интерпретатора (`sys.executable`) ставится первым в `PATH`,
  а при настоящем venv (наличие `pyvenv.cfg`) выставляется `VIRTUAL_ENV`
  и убирается `PYTHONHOME`. Раньше `.sh pip install ...` мог попадать
  в системный/`--user` Python мимо venv.

### 🐞 Выгрузка модулей (`.unloadmod` / `.ulm`)
- **Модуль больше не «живёт» после выгрузки.** В `unload_module`
  (`kitsune/core/loader.py`) добавлена очистка `sys.modules`
  (метод `_purge_sys_modules`): удаляются и сам Python-модуль, и все его
  подмодули, после чего вызывается `importlib.invalidate_caches()`.
  Это устраняло причину, по которой фоновые asyncio-задачи, замыкания
  и напрямую навешенные telethon-хендлеры продолжали работать
  до полной перезагрузки процесса.
- **Снятие inline-хендлеров при выгрузке.** Добавлен
  `_unregister_inline_handlers_for`; в `inline/core.py`
  `unregister_inline_handler` теперь сопоставляет связанные методы
  по `__self__`/`__func__`, а не по `is` (иначе rebound-метод из
  `inspect.getmembers` не находился). Callback-хендлеры в текущей версии
  не задействованы (декоратора и регистрации нет), поэтому мёртвый код
  не добавлялся.
- **Watcher'ы и команды снимаются по модулю-владельцу.** В диспетчере
  (`kitsune/core/dispatcher.py`) `register_watcher` сохраняет владельца
  явным полем, а `unregister_watchers_for` снимает по нему — теперь
  корректно снимаются и watcher'ы, зарегистрированные как несвязанные
  функции/замыкания (без `__self__`). Проверка по `__self__` оставлена
  как дополнительный критерий. Команды снимаются по модулю из записи
  диспетчера, а не только по `__self__`.

### 🔬 Tests
- Новый файл `tests/test_unload_fixes.py`: маппинг `google → google-genai`,
  снятие watcher'а по владельцу (в т.ч. для функции без `__self__`),
  очистка `sys.modules` при `unload_module` (сам модуль и подмодули),
  снятие inline-хендлеров при выгрузке, а также поведение `_venv_aware_env()`.

### 🔖 Versioning
- Глобальная версия проекта поднята до **1.4.3**.

---

## [1.4.1] — CI & module-level tests

### 🔬 Tests
- Новый файл `tests/test_modules.py` — для каждого встроенного модуля `kitsune/modules/*.py`
  выполняется три проверки:
  - модуль импортируется без `ImportError`,
  - после загрузки `Loader._register_module()` регистрирует хендлеры
    в `Dispatcher` (либо класс является служебным — без хендлеров),
  - `instance.strings(key)` отдаёт строки локализации как на `ru`, так и на `en`.

### ⚙️ CI
- Добавлен `.github/workflows/ci.yml` — GitHub Actions запускает
  `ruff`, `mypy` и `pytest` на Python 3.12 и 3.13 при каждом push / pull_request.
- Добавлен optional-dependency `speedups` (`tgcrypto` + `uvloop`).
- `pyproject.toml`: исправлено поле `authors` (PEP 621), `requires-python` понижен до `>=3.12`,
  добавлены разделы `[tool.ruff.lint]` и `[tool.pytest.ini_options]`.

### 🔖 Versioning
- Глобальная версия проекта поднята до **1.4.1**.
- Версия модулей `Config` и `KitsuneInfo` обновлена `1.4.0 → 1.4.1`.

---

## [1.3.0] — Phase 3: Reliability

### 🛡 Reliability subsystem
- **Новый модуль `kitsune/core/reliability.py`** с полным набором инструментов надёжности:
  - `CircuitBreaker` — классический «автоматический выключатель»
    с тремя состояниями (CLOSED → OPEN → HALF_OPEN), async-safe.
  - `RetryPolicy` + `retry_with_backoff()` — экспоненциальный backoff
    с jitter для сетевых операций (1с → 2с → 4с → 8с → 16с).
  - `DegradationFlags` — глобальные флаги graceful degradation
    (`hydrogram_failed`, `assets_unavailable`, `redis_unavailable`, `vpn_down`).
  - `global_registry` — единый реестр всех breaker'ов.

### 💗 Health endpoint & модуль
- **Команда `.health`** переписана полностью (`kitsune/modules/health.py`):
  - Параллельные пробы SQLite (`SELECT 1`), Redis (`PING`),
    Telegram session (`GetStateRequest` под защитой breaker'а).
  - Latency-измерения для каждой подсистемы.
  - Статус всех circuit breaker'ов + флаги деградации.
  - Uptime, RAM/CPU/disk, process RSS.
- **Новые команды**: `.breakers`, `.resetbreaker <name>`.
- **HTTP `/health`** в web/core.py возвращает тот же расширенный JSON-snapshot;
  при проблемах отвечает HTTP 503 (удобно для load-balancer'ов).

### ⚡ Circuit breakers в боевых местах
- **`telegram_api`** (5 fail / 60с cooldown) — защищает GetState-probe.
- **`redis_io`** (3 fail / 30с cooldown) — после 3 провалов
  `DatabaseManager` автоматически фоллбекится на SQLite,
  без потерь данных.
- **`hydrogram_io`** (3 fail / 5 мин cooldown).

### 🔄 Graceful degradation
- **Hydrogram сломался → Telethon-only**: `hydro_media.py` после
  3 провалов подряд помечает Hydrogram мёртвым на 5 мин и всё
  время идёт напрямую через Telethon. PEER_ID_INVALID не считается
  системным сбоем. `HydrogramBridge` респектит флаг.
- **Assets channel недоступен → пропускаем медиа**:
  `store_asset()`/`fetch_asset()` больше не бросают RuntimeError,
  возвращают None и пишут в debug-лог.
- **Redis отвалился → SQLite-fallback**: `DatabaseManager` держит
  «тёплый» SQLite-backend наготове; переключение мгновенное,
  порог — 3 провальных save подряд.
- **VPN/прокси отключился → retry с backoff**: `_safe_force_reconnect()`
  в main.py использует `retry_with_backoff` и поднимает флаг
  `vpn_down` на время retry-цикла.

### ✋🏻 Tests
- `kitsune/tests/test_reliability.py` — 18 unit-тестов:
  CircuitBreaker (states/transitions/reset), RetryWithBackoff (success/
  retry/exhaust), DegradationFlags, registry. Все проходят (`OK`).

### 🔧 Misc
- Redis-клиент теперь создаётся с `socket_timeout=5s`,
  `socket_keepalive=True`, `health_check_interval=30s` — хвист ловит
  обрывы быстрее.
- Bumpнут версии `health` до v3.0.

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
