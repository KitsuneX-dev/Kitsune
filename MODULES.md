# Как писать модули для Kitsune

Полная документация по написанию модулей. Здесь описано всё что есть в фреймворке — читай по порядку или прыгай к нужному разделу.

---

## Содержание

1. [Куда класть файл](#куда-класть-файл)
2. [Минимальный модуль](#минимальный-модуль)
3. [Атрибуты класса](#атрибуты-класса)
4. [Команды — декоратор @command](#команды--декоратор-command)
5. [Уровни доступа](#уровни-доступа)
6. [Кастомные роли для модуля](#кастомные-роли-для-модуля)
7. [Входящие команды — incoming=True](#входящие-команды--incomingtrue)
8. [Watchers — слушатели сообщений](#watchers--слушатели-сообщений)
9. [База данных](#база-данных)
10. [Конфиг модуля](#конфиг-модуля)
11. [Локализация строк](#локализация-строк)
12. [Хуки on_load и on_unload](#хуки-on_load-и-on_unload)
13. [События EventBus](#события-eventbus)
14. [Зависимости между модулями](#зависимости-между-модулями)
15. [Автоустановка зависимостей](#автоустановка-зависимостей)
16. [Ограничения безопасности](#ограничения-безопасности)
17. [Что доступно внутри модуля](#что-доступно-внутри-модуля)
18. [Примеры](#примеры)

---

## Куда класть файл

Пользовательские модули живут в `~/.kitsune/modules/`. Варианты:

- Кинуть `.py` файл напрямую
- Установить через `.loadmod` (по URL или файлу)
- Создать пакет — папку с `__init__.py` внутри

При запуске Kitsune подхватывает всё что там лежит. Единственное условие — в файле должен быть класс-наследник `KitsuneModule`, иначе загрузчик тихо проигнорирует файл.

---

## Минимальный модуль

```python
from kitsune.core.loader import KitsuneModule, command
from kitsune.core.security import OWNER

class HelloModule(KitsuneModule):
    name        = "hello"
    description = "Простой тестовый модуль"
    author      = "ты"
    version     = "1.0.0"

    @command("hello", required=OWNER)
    async def hello_cmd(self, event) -> None:
        """hello — отправить приветствие."""
        await event.reply("Привет от Kitsune! 👋")
```

Сохраняем в `~/.kitsune/modules/hello.py` и загружаем через `.loadmod`.

---

## Атрибуты класса

| Атрибут | Тип | Обязателен | Что значит |
|---|---|---|---|
| `name` | `str` | да | Уникальный идентификатор модуля |
| `description` | `str` | желательно | Показывается в `.help` |
| `author` | `str` | нет | Для информации |
| `version` | `str` | нет | Формат любой, обычно `"1.0.0"` |
| `icon` | `str` | нет | Эмодзи-иконка, по умолчанию `📦` |
| `category` | `str` | нет | Категория в `.help`, по умолчанию `"other"` |
| `requires` | `list[str]` | нет | Имена модулей, без которых этот не загрузится |
| `role_db_owner` | `str` | нет | Переопределяет ключ БД для кастомных ролей (подробнее в разделе про роли) |

Если `name` не задан — возьмётся имя класса.

---

## Команды — декоратор @command

```python
from kitsune.core.loader import command
from kitsune.core.security import OWNER, SUDO

@command("say", required=OWNER, aliases=["echo"])
async def say_cmd(self, event) -> None:
    """say <текст> — повторить сообщение."""
    text = self.get_args(event)
    if not text:
        await event.reply("Укажи что сказать")
        return
    await event.reply(text)
```

**Параметры декоратора:**

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `name` | `str` | имя метода без `_cmd` | Имя команды без префикса |
| `required` | `int` или `str` | `0` | Уровень доступа (подробнее ниже) |
| `aliases` | `list[str]` | `None` | Дополнительные псевдонимы команды |
| `incoming` | `bool` | `False` | Реагировать на команды от других юзеров |

**`self.get_args(event)`** — возвращает всё что идёт после команды, уже без префикса и самой команды.

---

## Уровни доступа

Импортируются из `kitsune.core.security`:

```python
from kitsune.core.security import OWNER, SUDO, SUPPORT, EVERYONE, GROUP_ADMIN
```

| Константа | Кто имеет доступ |
|---|---|
| `OWNER` | Только владелец юзербота. По умолчанию для всех встроенных команд |
| `SUDO` | Доверенные пользователи из `.sudoadd` |
| `SUPPORT` | Пользователи поддержки |
| `GROUP_ADMIN` | Любой администратор группы |
| `GROUP_OWNER` | Создатель группы |
| `EVERYONE` | Вообще все, включая незнакомцев |
| `PM` | Только в личке |

Можно комбинировать через `|`:

```python
@command("modcmd", required=OWNER | SUDO)
```

---

## Кастомные роли для модуля

Если нужно дать доступ к командам конкретным людям — без выдачи им глобального sudo — используй кастомную роль. Это строка вместо битовой маски в `required=`.

```python
RP_USER = "rp_user"  # просто строка — имя роли

class RPModule(KitsuneModule):
    name = "rpmod"

    @command("hug", required=RP_USER)
    async def hug_cmd(self, event) -> None:
        """hug — обнять кого-то."""
        ...

    @command("rpadd", required=OWNER)
    async def rpadd_cmd(self, event) -> None:
        """rpadd @user — выдать доступ к RP-командам."""
        target = await self.client.get_entity(event.message.mentioned_users[0])

        users = self.db.get(self.name, "rp_user_users", [])
        if target.id not in users:
            users.append(target.id)
            await self.db.set(self.name, "rp_user_users", users)

        await event.reply(f"✅ {target.first_name} теперь может использовать RP-команды")

    @command("rpdel", required=OWNER)
    async def rpdel_cmd(self, event) -> None:
        """rpdel @user — забрать доступ."""
        target = await self.client.get_entity(event.message.mentioned_users[0])

        users = self.db.get(self.name, "rp_user_users", [])
        users = [u for u in users if u != target.id]
        await self.db.set(self.name, "rp_user_users", users)

        await event.reply(f"✅ Доступ у {target.first_name} забран")
```

**Как это работает изнутри:**

Dispatcher ищет список пользователей в БД по ключу:
```
<module_db_owner>.<role_name>_users
```

По умолчанию `module_db_owner` — это `module.name`. То есть для роли `"rp_user"` в модуле `rpmod` ключ будет `rpmod.rp_user_users`.

Именно поэтому в `rpadd_cmd` мы пишем:
```python
self.db.get(self.name, "rp_user_users", [])
#           ^^^^^^^^^ — это module_db_owner
#                        ^^^^^^^^^^^^^^ — это <role_name>_users
```

**Если нужно переопределить ключ** (например, чтобы несколько модулей делили один список) — добавь атрибут `role_db_owner` в класс:

```python
class RPModule(KitsuneModule):
    name         = "rpmod"
    role_db_owner = "shared_rp"  # все роли будут храниться под ключом "shared_rp"
```

> **Важно:** команды со строковым `required` автоматически работают как `incoming=True` — иначе их никто кроме владельца и не смог бы вызвать. Писать `incoming=True` явно не нужно, но можно.

---

## Входящие команды — incoming=True

По умолчанию Kitsune реагирует только на твои исходящие сообщения. Если нужно чтобы команду мог вызвать другой пользователь (sudo, co-owner или участник кастомной роли) — добавь `incoming=True`:

```python
@command("ping", required=SUDO, incoming=True)
async def ping_cmd(self, event) -> None:
    """ping — проверить работу бота."""
    await event.reply("🏓 Pong!")
```

Dispatcher сам проверит права отправителя через `SecurityManager`. Если не проходит — сообщение тихо игнорируется.

**Когда писать `incoming=True` явно:**
- Команда с `required=SUDO` или `required=OWNER` — чтобы они могли вызывать её не только ты
- Команда с `required=EVERYONE` — доступна всем в чате

**Когда не нужно:**
- Команда с `required="role_name"` — `incoming=True` уже включён автоматически

---

## Watchers — слушатели сообщений

Если нужно реагировать на сообщения без команды — используй `@watcher`. Срабатывает на каждое подходящее сообщение.

```python
from kitsune.core.loader import watcher

@watcher()
async def on_message(self, event) -> None:
    text = event.message.raw_text or ""
    if "купить подписку" in text.lower():
        await event.reply("Нет.")
```

Можно передать фильтр-функцию:

```python
def only_groups(event) -> bool:
    return event.is_group

@watcher(filter_func=only_groups)
async def group_watcher(self, event) -> None:
    ...
```

> **Осторожно** — вотчер без фильтра срабатывает на каждое сообщение. Не делай там ничего тяжёлого.

---

## База данных

В каждом модуле есть `self.db`. Простое хранилище ключ-значение, разбитое по неймспейсам.

```python
# Сохранить (async)
await self.db.set("mymodule", "counter", 42)

# Сохранить (sync — для on_load и других синхронных мест)
self.db.set_sync("mymodule", "counter", 42)

# Прочитать (третий аргумент — дефолтное значение)
counter = self.db.get("mymodule", "counter", 0)
```

Данные сохраняются между перезапусками. В качестве неймспейса удобно использовать `self.name` — тогда точно не будет конфликтов с другими модулями.

**Что можно хранить:** любые JSON-совместимые типы — `str`, `int`, `float`, `bool`, `list`, `dict`.

---

## Конфиг модуля

Если хочешь чтобы пользователь мог настраивать параметры через `.config` — объяви `self.config` в `__init__`:

```python
from kitsune.core.loader import ModuleConfig, ConfigValue
from kitsune.validators import Boolean, Integer, String

class MyModule(KitsuneModule):
    name = "mymod"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = ModuleConfig(
            ConfigValue(
                "enabled",
                default=True,
                doc="Включить/выключить модуль",
                validator=Boolean(),
            ),
            ConfigValue(
                "max_count",
                default=10,
                doc="Максимальное количество повторений (1–100)",
                validator=Integer(minimum=1, maximum=100),
            ),
            ConfigValue(
                "prefix_text",
                default="",
                doc="Текст, добавляемый в начало ответа",
                validator=String(max_len=50),
            ),
        )
```

Читать значение:

```python
if self.config["enabled"]:
    count = self.config["max_count"]
```

Kitsune сам подтянет сохранённые значения из БД при загрузке.

**Доступные валидаторы** из `kitsune.validators`:

| Валидатор | Описание |
|---|---|
| `Boolean()` | true/false, yes/no, 1/0 |
| `Integer(minimum=..., maximum=...)` | Целое число с опциональными границами |
| `Float(...)` | Дробное число |
| `String(min_len=..., max_len=..., regex=...)` | Строка с опциональными ограничениями |
| `Choice(choices=[...])` | Одно значение из списка |
| `MultiChoice(choices=[...])` | Несколько значений из списка |
| `Link()` | URL |
| `TelegramID()` | Telegram ID пользователя или канала |
| `Hidden()` | Строка, не показывается в `.config` — для токенов |
| `RegExp(pattern)` | Строка по регулярному выражению |
| `Series(...)` | Список однотипных значений |
| `Union(validators=[...])` | Одно из нескольких типов |

---

## Локализация строк

Храни тексты в классе — Kitsune сам выберет нужный язык:

```python
class MyModule(KitsuneModule):
    name = "mymod"

    strings_ru = {
        "done":  "✅ Готово",
        "error": "❌ Ошибка: {msg}",
    }

    strings_en = {
        "done":  "✅ Done",
        "error": "❌ Error: {msg}",
    }

    @command("test", required=OWNER)
    async def test_cmd(self, event) -> None:
        await event.reply(self.strings("done"))
        # С подстановкой:
        # await event.reply(self.strings("error", msg="что-то пошло не так"))
```

Если строки для текущего языка не нашлись — упадёт на `strings_ru`, потом на `strings_en`. Если вообще ничего нет — вернёт ключ как есть.

---

## Хуки on_load и on_unload

```python
async def on_load(self) -> None:
    # Вызывается один раз после загрузки модуля
    # Хорошее место для инициализации, запуска фоновых задач
    self._task = asyncio.create_task(self._background_loop())

async def on_unload(self) -> None:
    # Вызывается перед выгрузкой
    # Обязательно чисти за собой: отменяй задачи, закрывай соединения
    if hasattr(self, "_task"):
        self._task.cancel()
```

> Если модуль запускает фоновые задачи — **обязательно** отменяй их в `on_unload`. Иначе они будут висеть в памяти даже после выгрузки.

---

## События EventBus

Kitsune имеет внутреннюю шину событий:

```python
from kitsune.events import bus
from kitsune._types import ModuleLoadedEvent

async def on_load(self) -> None:
    bus.subscribe(ModuleLoadedEvent, self._on_module_loaded)

async def on_unload(self) -> None:
    bus.unsubscribe(ModuleLoadedEvent, self._on_module_loaded)
    # Или сразу всё:
    # bus.unsubscribe_all(self)

async def _on_module_loaded(self, event: ModuleLoadedEvent) -> None:
    print(f"Загружен модуль: {event.module_name}")
```

**Доступные события** из `kitsune._types`:

| Событие | Поля | Описание |
|---|---|---|
| `ModuleLoadedEvent` | `module_name`, `is_builtin` | Модуль загружен |
| `ModuleUnloadedEvent` | `module_name` | Модуль выгружен |
| `ConfigChangedEvent` | `module_name`, `key`, `old_value`, `new_value` | Изменилась настройка |
| `PrefixChangedEvent` | `old_prefix`, `new_prefix` | Сменился префикс команд |
| `SecurityChangedEvent` | `action`, `user_id`, `role` | Изменились права пользователя |

> Если подписался в `on_load` — **обязательно** отпишись в `on_unload`. Иначе после перезагрузки модуля будут висеть сразу два обработчика.

---

## Зависимости между модулями

Если твой модуль зависит от другого — укажи это явно:

```python
class MyModule(KitsuneModule):
    name     = "mymod"
    requires = ["ping", "someothermodule"]
```

Если нужные модули не загружены — загрузчик откажется загружать и твой, с понятной ошибкой. Это лучше чем падать с `AttributeError` в рантайме.

---

## Автоустановка зависимостей

Если модулю нужна сторонняя библиотека — загрузчик попробует поставить её через pip автоматически. Просто импортируй как обычно:

```python
import aiohttp  # есть в требованиях Kitsune, всегда доступен
import PIL      # загрузчик сам поставит Pillow, если его нет
```

Для некоторых пакетов уже есть маппинг (`PIL` → `Pillow`, `cv2` → `opencv-python`, `yaml` → `PyYAML` и т.д.), остальные ставятся по имени модуля. На Termux добавляются флаги `--prefer-binary --no-build-isolation`.

---

## Ограничения безопасности

Kitsune проверяет код модулей через AST-сканер перед загрузкой.

**Запрещённые импорты:**
`subprocess`, `pty`, `ctypes`, `multiprocessing`, `socket`, `pickle`, `marshal`, `shelve`, `dbm`, `runpy`, `distutils` и ряд других.

**Запрещённые вызовы:**
- `os.system()`, `os.popen()`, `os.fork()`, `os.kill()` и другие опасные методы `os`
- `eval()`, `exec()`, `compile()` с динамическим или закодированным содержимым
- `__import__()` с динамическими аргументами
- Обращение к `__builtins__`, `__loader__`

Если в коде найдётся что-то из этого — модуль не загрузится, в логах будет `ASTSecurityError` с указанием строки.

Если нужен HTTP — используй `aiohttp`. Файлы — стандартный `open()` и `pathlib.Path` доступны.

---

## Что доступно внутри модуля

| Атрибут | Описание |
|---|---|
| `self.client` | Telethon-клиент. Любые запросы к Telegram API |
| `self.db` | База данных (`.get()` / `.set()` / `.set_sync()`) |
| `self.config` | Настройки модуля (если объявлены) |
| `self.tg_id` | Telegram ID владельца |
| `self.inline` | Inline-движок (для inline-режима) |
| `self.get_args(event)` | Аргументы команды строкой |
| `self.strings(key, **kwargs)` | Локализованная строка |
| `self.name` | Имя модуля (удобно как неймспейс для БД) |

---

## Примеры

### Простая команда с аргументами

```python
from kitsune.core.loader import KitsuneModule, command
from kitsune.core.security import OWNER

class EchoModule(KitsuneModule):
    name        = "echo"
    description = "Повторяет текст"

    @command("echo", required=OWNER, aliases=["say"])
    async def echo_cmd(self, event) -> None:
        """echo <текст> — повторить сообщение."""
        text = self.get_args(event)
        if not text:
            await event.reply("Укажи текст")
            return
        await event.edit(text)
```

---

### Модуль с кастомной ролью

```python
from kitsune.core.loader import KitsuneModule, command
from kitsune.core.security import OWNER

GREETER = "greeter"  # имя кастомной роли

class GreetModule(KitsuneModule):
    name        = "greet"
    description = "Приветствие от доверенных пользователей"

    # incoming=True включается автоматически для строковых ролей
    @command("greet", required=GREETER)
    async def greet_cmd(self, event) -> None:
        """greet — поприветствовать чат."""
        await event.reply("Привет от доверенного пользователя! 👋")

    @command("greetadd", required=OWNER)
    async def greetadd_cmd(self, event) -> None:
        """greetadd @user — выдать доступ к .greet."""
        reply = await event.get_reply_message()
        if not reply:
            await event.reply("Ответь на сообщение пользователя")
            return
        uid = reply.sender_id
        users = self.db.get(self.name, "greeter_users", [])
        if uid not in users:
            users.append(uid)
            await self.db.set(self.name, "greeter_users", users)
        await event.reply("✅ Доступ выдан")

    @command("greetdel", required=OWNER)
    async def greetdel_cmd(self, event) -> None:
        """greetdel @user — забрать доступ."""
        reply = await event.get_reply_message()
        if not reply:
            await event.reply("Ответь на сообщение пользователя")
            return
        uid = reply.sender_id
        users = [u for u in self.db.get(self.name, "greeter_users", []) if u != uid]
        await self.db.set(self.name, "greeter_users", users)
        await event.reply("✅ Доступ забран")
```

---

### Модуль с конфигом, локализацией и HTTP-запросом

```python
from __future__ import annotations
import aiohttp
from kitsune.core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from kitsune.core.security import OWNER
from kitsune.validators import String

class QuoteModule(KitsuneModule):
    name        = "quote"
    description = "Случайная цитата"
    icon        = "💬"
    category    = "fun"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = ModuleConfig(
            ConfigValue(
                "lang",
                default="ru",
                doc="Язык цитат: ru или en",
                validator=String(),
            ),
        )

    strings_ru = {
        "loading": "⏳ Загружаю...",
        "result":  "💬 <i>{text}</i>\n\n— {author}",
        "error":   "❌ Не удалось загрузить цитату",
    }

    strings_en = {
        "loading": "⏳ Loading...",
        "result":  "💬 <i>{text}</i>\n\n— {author}",
        "error":   "❌ Failed to load quote",
    }

    @command("quote", required=OWNER)
    async def quote_cmd(self, event) -> None:
        """quote — случайная цитата."""
        msg = await event.reply(self.strings("loading"), parse_mode="html")
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    "https://api.quotable.io/random",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    data = await r.json()
            text = self.strings("result", text=data["content"], author=data["author"])
        except Exception:
            text = self.strings("error")
        await msg.edit(text, parse_mode="html")
```

---

### Модуль с фоновой задачей

```python
import asyncio
from kitsune.core.loader import KitsuneModule, command
from kitsune.core.security import OWNER

class WatcherModule(KitsuneModule):
    name        = "watcher"
    description = "Фоновая задача"

    async def on_load(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def on_unload(self) -> None:
        self._running = False
        if hasattr(self, "_task"):
            self._task.cancel()

    async def _loop(self) -> None:
        while self._running:
            # что-то делаем раз в минуту
            await asyncio.sleep(60)

    @command("watcherstatus", required=OWNER)
    async def status_cmd(self, event) -> None:
        """watcherstatus — проверить статус задачи."""
        alive = hasattr(self, "_task") and not self._task.done()
        await event.reply("✅ Задача работает" if alive else "❌ Задача не запущена")
```

---

## Совет напоследок

Смотри на встроенные модули в `kitsune/modules/` — там есть примеры на все случаи:
- `ping.py` — самый простой, с которого стоит начать
- `weather.py` — конфиг и HTTP-запросы
- `backup.py` — работа с файлами и кастомные роли
- `kitsune_security.py` — управление правами пользователей

Если что-то не работает — проверь логи (`~/.kitsune/logs/` или запусти с `--debug`), там обычно написано достаточно внятно.
