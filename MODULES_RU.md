# Разработка модулей для Kitsune

Полная документация по API модулей. Разделы расположены в порядке изучения — от базового к сложному.

---

## Содержание

1. [Расположение модулей](#расположение-модулей)
2. [Минимальный модуль](#минимальный-модуль)
3. [Атрибуты класса](#атрибуты-класса)
4. [Команды — декоратор @command](#команды--декоратор-command)
5. [Уровни доступа](#уровни-доступа)
6. [Кастомные роли](#кастомные-роли)
7. [Входящие команды — incoming=True](#входящие-команды--incomingtrue)
8. [Watchers](#watchers)
9. [База данных](#база-данных)
10. [Конфиг модуля](#конфиг-модуля)
11. [Локализация](#локализация)
12. [Хуки on_load и on_unload](#хуки-on_load-и-on_unload)
13. [EventBus](#eventbus)
14. [Зависимости между модулями](#зависимости-между-модулями)
15. [Автоустановка зависимостей](#автоустановка-зависимостей)
16. [Ограничения безопасности](#ограничения-безопасности)
17. [Доступные атрибуты модуля](#доступные-атрибуты-модуля)
18. [Примеры](#примеры)

---

## Расположение модулей

Пользовательские модули хранятся в `~/.kitsune/modules/`. Способы добавления:

- Поместить `.py` файл непосредственно в директорию
- Установить через `.loadmod` — по URL или из локального файла
- Создать пакет — директорию с файлом `__init__.py` внутри

При запуске Kitsune загружает всё содержимое этой директории. Обязательное условие — файл должен содержать класс-наследник `KitsuneModule`. Файлы без такого класса игнорируются без ошибок.

---

## Минимальный модуль

```python
from kitsune.core.loader import KitsuneModule, command
from kitsune.core.security import OWNER

class HelloModule(KitsuneModule):
    name        = "hello"
    description = "Простой тестовый модуль"
    author      = "вы"
    version     = "1.0.0"

    @command("hello", required=OWNER)
    async def hello_cmd(self, event) -> None:
        await event.reply("Привет от Kitsune! 👋")
```

Сохраните в `~/.kitsune/modules/hello.py` и загрузите через `.loadmod`.

---

## Атрибуты класса

| Атрибут | Тип | Обязателен | Описание |
|---|---|---|---|
| `name` | `str` | да | Уникальный идентификатор модуля |
| `description` | `str` | желательно | Отображается в `.help` |
| `author` | `str` | нет | Информационное поле |
| `version` | `str` | нет | Любой формат, принято `"1.0.0"` |
| `icon` | `str` | нет | Эмодзи-иконка, по умолчанию `📦` |
| `category` | `str` | нет | Категория в `.help`, по умолчанию `"other"` |
| `requires` | `list[str]` | нет | Имена модулей, которые должны быть загружены раньше |
| `role_db_owner` | `str` | нет | Переопределяет пространство имён БД для кастомных ролей |

Если `name` не задан — используется имя класса.

---

## Команды — декоратор @command

```python
from kitsune.core.loader import command
from kitsune.core.security import OWNER, SUDO

@command("say", required=OWNER, aliases=["echo"])
async def say_cmd(self, event) -> None:
    text = self.get_args(event)
    if not text:
        await event.reply("Укажите текст")
        return
    await event.reply(text)
```

**Параметры декоратора:**

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `name` | `str` | имя метода без `_cmd` | Имя команды без префикса |
| `required` | `int` или `str` | `0` | Уровень доступа |
| `aliases` | `list[str]` | `None` | Дополнительные псевдонимы команды |
| `incoming` | `bool` | `False` | Реагировать на команды от других пользователей |

**`self.get_args(event)`** возвращает всё, что идёт после команды, с уже отрезанным префиксом и именем команды.

---

## Уровни доступа

Импортируются из `kitsune.core.security`:

```python
from kitsune.core.security import OWNER, SUDO, SUPPORT, EVERYONE, GROUP_ADMIN
```

| Константа | Кто имеет доступ |
|---|---|
| `OWNER` | Только владелец. По умолчанию для всех встроенных команд |
| `SUDO` | Доверенные пользователи, добавленные через `.sudoadd` |
| `SUPPORT` | Пользователи уровня поддержки |
| `GROUP_ADMIN` | Любой администратор группы |
| `GROUP_OWNER` | Создатель группы |
| `EVERYONE` | Все пользователи, включая незнакомцев |
| `PM` | Только в личных сообщениях |

Уровни можно комбинировать через `|`:

```python
@command("modcmd", required=OWNER | SUDO)
```

---

## Кастомные роли

Кастомные роли позволяют открыть доступ к конкретным командам без выдачи глобального sudo. Роль задаётся строкой в `required=`.

```python
RP_USER = "rp_user"

class RPModule(KitsuneModule):
    name = "rpmod"

    @command("hug", required=RP_USER)
    async def hug_cmd(self, event) -> None:
        ...

    @command("rpadd", required=OWNER)
    async def rpadd_cmd(self, event) -> None:
        target = await self.client.get_entity(event.message.mentioned_users[0])
        users = self.db.get(self.name, "rp_user_users", [])
        if target.id not in users:
            users.append(target.id)
            await self.db.set(self.name, "rp_user_users", users)
        await event.reply(f"✅ {target.first_name} получил доступ к RP-командам")

    @command("rpdel", required=OWNER)
    async def rpdel_cmd(self, event) -> None:
        target = await self.client.get_entity(event.message.mentioned_users[0])
        users = [u for u in self.db.get(self.name, "rp_user_users", []) if u != target.id]
        await self.db.set(self.name, "rp_user_users", users)
        await event.reply(f"✅ Доступ у {target.first_name} отозван")
```

**Как работает изнутри:**

Диспетчер ищет список пользователей в БД по ключу:

```
<module_db_owner>.<role_name>_users
```

По умолчанию `module_db_owner` совпадает с `module.name`. Для роли `"rp_user"` в модуле `rpmod` ключ будет `rpmod.rp_user_users`.

Именно поэтому `rpadd_cmd` обращается к:

```python
self.db.get(self.name, "rp_user_users", [])
#           ^^^^^^^^^ — module_db_owner
#                        ^^^^^^^^^^^^^^ — <role_name>_users
```

Чтобы несколько модулей разделяли один список ролей — переопределите `role_db_owner`:

```python
class RPModule(KitsuneModule):
    name          = "rpmod"
    role_db_owner = "shared_rp"
```

> Команды со строковым значением `required` автоматически получают `incoming=True` — без этого никто кроме владельца не смог бы их вызвать. Явно писать `incoming=True` не требуется, но допустимо.

---

## Входящие команды — incoming=True

По умолчанию Kitsune реагирует только на исходящие сообщения владельца. Чтобы команду мог вызвать другой пользователь (sudo, co-owner или участник кастомной роли) — добавьте `incoming=True`:

```python
@command("ping", required=SUDO, incoming=True)
async def ping_cmd(self, event) -> None:
    await event.reply("🏓 Pong!")
```

Диспетчер проверяет права отправителя через `SecurityManager`. При отказе — сообщение молча игнорируется.

**Когда указывать `incoming=True` явно:**
- `required=SUDO` или `required=OWNER` — чтобы они могли вызывать команду
- `required=EVERYONE` — команда доступна всем в чате

**Когда не нужно:**
- `required="role_name"` — `incoming=True` включается автоматически

---

## Watchers

Watchers реагируют на сообщения без команды — срабатывают на каждое подходящее сообщение.

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

> Watcher без фильтра срабатывает на каждое сообщение. Не выполняйте в нём тяжёлых операций.

---

## База данных

В каждом модуле доступен `self.db` — хранилище ключ-значение, разбитое по пространствам имён.

```python
# Сохранить (async)
await self.db.set("mymodule", "counter", 42)

# Сохранить (sync — для on_load и других синхронных контекстов)
self.db.set_sync("mymodule", "counter", 42)

# Прочитать (третий аргумент — значение по умолчанию)
counter = self.db.get("mymodule", "counter", 0)
```

Данные сохраняются между перезапусками. Рекомендуется использовать `self.name` как пространство имён — это исключает конфликты с другими модулями.

**Допустимые типы значений:** любые JSON-совместимые — `str`, `int`, `float`, `bool`, `list`, `dict`.

---

## Конфиг модуля

Чтобы пользователь мог настраивать параметры модуля через `.config` — объявите `self.config` в `__init__`:

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
                doc="Включить или отключить модуль",
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
                doc="Текст, добавляемый в начало каждого ответа",
                validator=String(max_len=50),
            ),
        )
```

Читать значение:

```python
if self.config["enabled"]:
    count = self.config["max_count"]
```

Kitsune автоматически восстанавливает сохранённые значения из БД при загрузке модуля.

**Доступные валидаторы** из `kitsune.validators`:

| Валидатор | Описание |
|---|---|
| `Boolean()` | true/false, yes/no, 1/0 |
| `Integer(minimum=..., maximum=...)` | Целое число с опциональными границами |
| `Float(...)` | Дробное число |
| `String(min_len=..., max_len=..., regex=...)` | Строка с опциональными ограничениями |
| `Choice(choices=[...])` | Одно значение из фиксированного списка |
| `MultiChoice(choices=[...])` | Несколько значений из фиксированного списка |
| `Link()` | URL |
| `TelegramID()` | Telegram ID пользователя или канала |
| `Hidden()` | Строка, не отображается в `.config` — для токенов и секретов |
| `RegExp(pattern)` | Строка по регулярному выражению |
| `Series(...)` | Список однотипных значений |
| `Union(validators=[...])` | Принимает одно из нескольких типов |

---

## Локализация

Храните строки в классе — Kitsune выберет нужный язык автоматически:

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

Если строки для текущего языка отсутствуют — fallback на `strings_ru`, затем на `strings_en`. Если не найдено ничего — возвращается ключ как есть.

---

## Хуки on_load и on_unload

```python
async def on_load(self) -> None:
    # Вызывается один раз после загрузки модуля.
    # Подходит для инициализации и запуска фоновых задач.
    self._task = asyncio.create_task(self._background_loop())

async def on_unload(self) -> None:
    # Вызывается перед выгрузкой модуля.
    # Здесь необходимо отменить задачи и закрыть соединения.
    if hasattr(self, "_task"):
        self._task.cancel()
```

> Если модуль запускает фоновые задачи — **обязательно** отменяйте их в `on_unload`. Задачи, которые не были отменены, продолжат работать после выгрузки модуля.

---

## EventBus

Kitsune предоставляет внутреннюю шину событий для взаимодействия между модулями:

```python
from kitsune.events import bus
from kitsune._types import ModuleLoadedEvent

async def on_load(self) -> None:
    bus.subscribe(ModuleLoadedEvent, self._on_module_loaded)

async def on_unload(self) -> None:
    bus.unsubscribe(ModuleLoadedEvent, self._on_module_loaded)
    # Или отписать все обработчики модуля сразу:
    # bus.unsubscribe_all(self)

async def _on_module_loaded(self, event: ModuleLoadedEvent) -> None:
    print(f"Загружен модуль: {event.module_name}")
```

**Доступные события** из `kitsune._types`:

| Событие | Поля | Описание |
|---|---|---|
| `ModuleLoadedEvent` | `module_name`, `is_builtin` | Модуль загружен |
| `ModuleUnloadedEvent` | `module_name` | Модуль выгружен |
| `ConfigChangedEvent` | `module_name`, `key`, `old_value`, `new_value` | Изменилось значение конфига |
| `PrefixChangedEvent` | `old_prefix`, `new_prefix` | Изменился префикс команд |
| `SecurityChangedEvent` | `action`, `user_id`, `role` | Изменились права пользователя |

> Если подписались в `on_load` — **обязательно** отпишитесь в `on_unload`. При повторной загрузке модуля будут зарегистрированы дублирующиеся обработчики.

---

## Зависимости между модулями

Если ваш модуль требует наличия другого — укажите это явно:

```python
class MyModule(KitsuneModule):
    name     = "mymod"
    requires = ["ping", "someothermodule"]
```

Если указанные модули не загружены — загрузчик откажет в загрузке вашего с понятным сообщением об ошибке. Это предпочтительнее, чем получить `AttributeError` в рантайме.

---

## Автоустановка зависимостей

Если модуль использует стороннюю библиотеку — загрузчик попытается установить её через pip автоматически. Импортируйте как обычно:

```python
import aiohttp  # входит в зависимости Kitsune, всегда доступен
import PIL      # загрузчик установит Pillow автоматически при отсутствии
```

Для распространённых пакетов уже есть маппинг (`PIL` → `Pillow`, `cv2` → `opencv-python`, `yaml` → `PyYAML` и т.д.), остальные устанавливаются по имени модуля. На Termux автоматически добавляются флаги `--prefer-binary --no-build-isolation`.

---

## Ограничения безопасности

Kitsune запускает AST-сканер на каждый модуль перед загрузкой.

**Запрещённые импорты:**
`subprocess`, `pty`, `ctypes`, `multiprocessing`, `socket`, `pickle`, `marshal`, `shelve`, `dbm`, `runpy`, `distutils` и ряд других.

**Запрещённые вызовы:**
- `os.system()`, `os.popen()`, `os.fork()`, `os.kill()` и другие опасные методы `os`
- `eval()`, `exec()`, `compile()` с динамическим или закодированным содержимым
- `__import__()` с динамическими аргументами
- `globals()["os"]` и любой динамический ключ, разрешающийся в запрещённое имя
- Обращение к `__builtins__`, `__loader__`

При обнаружении нарушения модуль не загружается, в лог записывается `ASTSecurityError` с указанием строки.

Для HTTP-запросов используйте `aiohttp`. Файловые операции доступны через стандартный `open()` и `pathlib.Path`.

---

## Доступные атрибуты модуля

| Атрибут | Описание |
|---|---|
| `self.client` | Telethon-клиент. Используется для всех обращений к Telegram API |
| `self.db` | База данных (`.get()` / `.set()` / `.set_sync()`) |
| `self.config` | Значения конфига модуля (если объявлены) |
| `self.tg_id` | Telegram ID владельца юзербота |
| `self.inline` | Inline-движок (для inline-режима) |
| `self.get_args(event)` | Аргументы строкой — всё после команды |
| `self.strings(key, **kwargs)` | Локализованная строка с опциональными подстановками |
| `self.name` | Имя модуля — удобно как пространство имён для БД |

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
        text = self.get_args(event)
        if not text:
            await event.reply("Укажите текст")
            return
        await event.edit(text)
```

---

### Модуль с кастомной ролью

```python
from kitsune.core.loader import KitsuneModule, command
from kitsune.core.security import OWNER

GREETER = "greeter"

class GreetModule(KitsuneModule):
    name        = "greet"
    description = "Приветствие от доверенных пользователей"

    @command("greet", required=GREETER)
    async def greet_cmd(self, event) -> None:
        await event.reply("Привет от доверенного пользователя! 👋")

    @command("greetadd", required=OWNER)
    async def greetadd_cmd(self, event) -> None:
        reply = await event.get_reply_message()
        if not reply:
            await event.reply("Ответьте на сообщение пользователя")
            return
        uid = reply.sender_id
        users = self.db.get(self.name, "greeter_users", [])
        if uid not in users:
            users.append(uid)
            await self.db.set(self.name, "greeter_users", users)
        await event.reply("✅ Доступ выдан")

    @command("greetdel", required=OWNER)
    async def greetdel_cmd(self, event) -> None:
        reply = await event.get_reply_message()
        if not reply:
            await event.reply("Ответьте на сообщение пользователя")
            return
        uid = reply.sender_id
        users = [u for u in self.db.get(self.name, "greeter_users", []) if u != uid]
        await self.db.set(self.name, "greeter_users", users)
        await event.reply("✅ Доступ отозван")
```

---

### Модуль с конфигом, локализацией и HTTP

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
    description = "Пример фоновой задачи"

    async def on_load(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def on_unload(self) -> None:
        self._running = False
        if hasattr(self, "_task"):
            self._task.cancel()

    async def _loop(self) -> None:
        while self._running:
            await asyncio.sleep(60)

    @command("watcherstatus", required=OWNER)
    async def status_cmd(self, event) -> None:
        alive = hasattr(self, "_task") and not self._task.done()
        await event.reply("✅ Задача работает" if alive else "❌ Задача не запущена")
```

---

## Референсные модули

Встроенные модули в `kitsune/modules/` покрывают все типовые сценарии:

| Модуль | Что демонстрирует |
|---|---|
| `ping.py` | Простейшая команда — хорошая отправная точка |
| `weather.py` | Конфиг и HTTP-запросы |
| `backup.py` | Работа с файлами и кастомные роли |
| `kitsune_security.py` | Управление правами пользователей |

При отладке проверяйте логи в `~/.kitsune/logs/` или запустите Kitsune с флагом `--debug`.
