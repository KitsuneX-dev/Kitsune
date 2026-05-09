# Как писать модули для Kitsune

Это неофициальная документация по написанию модулей. Написал её потому что вопросов в чате становится всё больше, а нормального гайда нигде нет. Постараюсь объяснить как оно работает изнутри, без лишней воды.

---

## Куда класть файл

Пользовательские модули живут в `~/.kitsune/modules/`. Туда можно:

- Кинуть `.py` файл напрямую
- Установить через `.loadmod` (по URL или файлу)
- Создать пакет — папку с `__init__.py` внутри

При запуске Kitsune сам подхватывает всё, что там лежит. Единственное условие — в файле должен быть класс-наследник `KitsuneModule`, иначе загрузчик тихо проигнорирует файл.

---

## Минимальный рабочий модуль

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

Вот и весь скелет. Сохраняем в `~/.kitsune/modules/hello.py` и загружаем через `.loadmod`.

---

## Атрибуты класса

| Атрибут | Тип | Обязателен | Что значит |
|---|---|---|---|
| `name` | `str` | да | Уникальный идентификатор, по нему происходит поиск и выгрузка |
| `description` | `str` | желательно | Показывается в `.help` |
| `author` | `str` | нет | Просто для информации |
| `version` | `str` | нет | Формат любой, обычно `"1.0.0"` |
| `icon` | `str` | нет | Эмодзи-иконка, по умолчанию `📦` |
| `category` | `str` | нет | Категория в `.help`, по умолчанию `"other"` |
| `requires` | `list[str]` | нет | Имена модулей, без которых этот не загрузится |

Если `name` не задан, возьмётся имя класса.

---

## Команды — декоратор `@command`

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

- `name` — имя команды без префикса. Если не указать, берётся имя метода без суффикса `_cmd`
- `required` — уровень доступа (подробнее ниже)
- `aliases` — список псевдонимов, например `aliases=["ec", "e"]`

**`self.get_args(event)`** — возвращает всё, что идёт после команды, уже без префикса и самой команды.

---

## Уровни доступа

Импортируются из `kitsune.core.security`:

```python
from kitsune.core.security import OWNER, SUDO, SUPPORT, EVERYONE, GROUP_ADMIN
```

| Константа | Кто имеет доступ |
|---|---|
| `OWNER` | Только владелец юзербота (твой аккаунт). По умолчанию для всех встроенных команд. |
| `SUDO` | Доверенные пользователи из `.sudo add` |
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

## Watchers — слушатели входящих сообщений

Если нужно реагировать на сообщения без команды — используй `@watcher`. Это не команда, это обработчик, который срабатывает на каждое подходящее сообщение.

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

Будь аккуратен — вотчер без фильтра срабатывает на КАЖДОЕ сообщение. Это может замедлить работу, если делаешь там что-то тяжёлое.

---

## База данных

В каждом модуле есть `self.db`. Это простое хранилище ключ-значение, разбитое по неймспейсам.

```python
# Сохранить
await self.db.set("mymodule.data", "counter", 42)

# Прочитать (третий аргумент — дефолтное значение)
counter = self.db.get("mymodule.data", "counter", 0)
```

Данные сохраняются между перезапусками. Неймспейс лучше называть как-то уникальным — например `kitsune.<имя_модуля>` — чтобы не конфликтовать с другими модулями.

---

## Конфиг модуля

Если хочешь, чтобы пользователь мог настраивать параметры через `.config`, объяви `self.config` в `__init__`:

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

Читать значение просто:

```python
if self.config["enabled"]:
    count = self.config["max_count"]
```

Kitsune сам подтянет сохранённые значения из БД при загрузке — тебе не нужно об этом думать.

### Доступные валидаторы

Все из `kitsune.validators`:

- `Boolean()` — true/false, yes/no, 1/0
- `Integer(minimum=..., maximum=...)` — целое число с опциональными границами
- `Float(...)` — то же самое, но дробное
- `String(min_len=..., max_len=..., regex=...)` — строка с опциональными ограничениями
- `Choice(choices=["a", "b", "c"])` — одно значение из списка
- `MultiChoice(choices=[...])` — несколько значений из списка
- `Link()` — URL
- `TelegramID()` — Telegram ID пользователя или канала
- `Hidden()` — строка, которая не показывается в `.config` (для токенов и т.п.)
- `RegExp(pattern)` — строка по регулярке
- `Series(...)` — список однотипных значений
- `Union(validators=[...])` — одно из нескольких типов

---

## Локализация строк

Можно хранить тексты прямо в классе, и Kitsune сам выберет нужный язык:

```python
class MyModule(KitsuneModule):
    name = "mymod"

    strings_ru = {
        "done": "✅ Готово",
        "error": "❌ Ошибка: {msg}",
    }

    strings_en = {
        "done": "✅ Done",
        "error": "❌ Error: {msg}",
    }

    @command("test", required=OWNER)
    async def test_cmd(self, event) -> None:
        await event.reply(self.strings("done"))
        # Или с форматированием:
        # await event.reply(self.strings("error", msg="что-то пошло не так"))
```

Если строки для текущего языка не нашлись — упадёт на `strings_ru`, потом на `strings_en`. Если вообще ничего нет — вернёт ключ как есть.

---

## Хуки `on_load` и `on_unload`

```python
async def on_load(self) -> None:
    # Вызывается один раз после загрузки модуля
    # Хорошее место для инициализации, создания задач и т.д.
    self._task = asyncio.create_task(self._background_loop())

async def on_unload(self) -> None:
    # Вызывается перед выгрузкой
    # Чисти за собой: отменяй задачи, закрывай соединения
    if hasattr(self, "_task"):
        self._task.cancel()
```

Если модуль запускает фоновые задачи — **обязательно** отменяй их в `on_unload`. Иначе они будут висеть в памяти даже после выгрузки.

---

## События (EventBus)

Kitsune имеет внутреннюю шину событий. Можно слушать, например, загрузку других модулей:

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

Доступные события из `kitsune._types`:

- `ModuleLoadedEvent(module_name, is_builtin)` — модуль загружен
- `ModuleUnloadedEvent(module_name)` — модуль выгружен
- `ConfigChangedEvent(module_name, key, old_value, new_value)` — изменилась настройка
- `PrefixChangedEvent(old_prefix, new_prefix)` — сменился префикс команд
- `SecurityChangedEvent(action, user_id, role)` — изменились права пользователя

Если подписался в `on_load` — **не забудь** отписаться в `on_unload`. Иначе после перезагрузки модуля будут висеть сразу два обработчика.

---

## Зависимости между модулями

Если твой модуль зависит от другого — укажи это явно:

```python
class MyModule(KitsuneModule):
    name = "mymod"
    requires = ["ping", "someothermodule"]
```

Если нужные модули не загружены, загрузчик откажется загружать и твой, с понятной ошибкой. Это лучше, чем падать с `AttributeError` в рантайме.

---

## Безопасность и ограничения

Kitsune проверяет код модулей через AST-сканер перед загрузкой. Следующие штуки заблокированы:

**Запрещённые импорты:**
`subprocess`, `pty`, `ctypes`, `multiprocessing`, `socket`, `pickle`, `marshal`, `shelve`, `dbm`, `runpy`, `distutils` и ряд других.

**Запрещённые вызовы:**
- `os.system()`, `os.popen()`, `os.fork()`, `os.kill()` и другие опасные методы `os`
- `eval()`, `exec()`, `compile()` с динамическим или закодированным содержимым
- `__import__()` с динамическими аргументами
- Обращение к `__builtins__`, `__loader__`

Если в коде найдётся что-то из этого — модуль не загрузится, и в логах будет `ASTSecurityError` с указанием строки.

Если нужен HTTP-запрос — используй `aiohttp`. Если нужна работа с файлами — стандартный `open()` и `pathlib.Path` вполне доступны, просто не пытайся лезть куда не надо.

---

## Автоустановка зависимостей

Если в модуле нужна сторонняя библиотека, которой нет в системе — загрузчик попробует поставить её через pip автоматически. Просто импортируй как обычно:

```python
import aiohttp  # есть в требованиях Kitsune, всегда доступен
import PIL      # загрузчик сам поставит Pillow, если его нет
```

Для некоторых пакетов уже есть маппинг (`PIL` → `Pillow`, `cv2` → `opencv-python`, `yaml` → `PyYAML` и т.д.), остальные ставятся по имени модуля. На Termux добавляются флаги `--prefer-binary --no-build-isolation`, чтобы не падало на пакетах без колёс.

---

## Пример посложнее — модуль с конфигом и локализацией

```python
from __future__ import annotations
import aiohttp
from kitsune.core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from kitsune.core.security import OWNER
from kitsune.validators import String

class QuoteModule(KitsuneModule):
    name        = "quote"
    description = "Случайная цитата"
    author      = "me"
    version     = "1.0.0"
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

    @command("quote", required=OWNER)
    async def quote_cmd(self, event) -> None:
        """quote — случайная цитата."""
        msg = await event.reply(self.strings("loading"), parse_mode="html")
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get("https://api.quotable.io/random", timeout=aiohttp.ClientTimeout(total=10)) as r:
                    data = await r.json()
            text = self.strings("result", text=data["content"], author=data["author"])
        except Exception:
            text = self.strings("error")
        await msg.edit(text, parse_mode="html")
```

---

## Что доступно внутри модуля

- `self.client` — Telethon-клиент. Можно делать любые запросы к Telegram API.
- `self.db` — база данных (`.get()` / `.set()`)
- `self.config` — настройки модуля (если объявлены)
- `self.tg_id` — Telegram ID владельца
- `self.inline` — объект inline-движка (если нужен inline-режим)
- `self.get_args(event)` — аргументы команды строкой
- `self.strings(key, **kwargs)` — локализованная строка

---

## Совет напоследок

Смотри на встроенные модули в `kitsune/modules/` — там есть хорошие примеры на все случаи. `ping.py` — самый простой, `weather.py` — с конфигом и HTTP, `backup.py` — если нужна работа с файлами.

Если что-то не работает — проверь логи (`~/.kitsune/logs/` или запусти с `--debug`), там обычно всё написано достаточно внятно.
