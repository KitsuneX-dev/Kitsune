# Как писать модули для Kitsune

Простое руководство по написанию собственных модулей. Без лишней теории — только
то, что реально нужно, чтобы твой модуль заработал в версии 1.4.4.

Сначала прочитай первые три раздела, этого уже хватит для простого модуля.
Остальное — по мере надобности.

---

## Куда класть модуль

Два способа:

1. **Через Telegram** — команды `.loadmod` (ответь на `.py`-файл) или `.dlmod`
   (по ссылке или имени модуля из репозитория).
2. **Вручную** — положи файл `мой_модуль.py` в папку `~/.kitsune/modules/`.
   Можно и папку с файлом `__init__.py` внутри, если модуль большой.

Kitsune при запуске подхватывает всё, что лежит в этой папке. Единственное
обязательное условие — в файле должен быть класс-наследник `KitsuneModule`.
Файл без такого класса просто пропускается, ошибок не будет.

---

## Самый простой модуль

```python
from kitsune.core.loader import KitsuneModule, command
from kitsune.core.security import OWNER

class HelloModule(KitsuneModule):
    name = "hello"
    description = "Приветствие"
    author = "ты"
    version = "1.0.0"

    @command("hello", required=OWNER)
    async def hello_cmd(self, event):
        await event.reply("Привет от Kitsune! 👋")
```

Что тут важно:

- класс наследуется от `KitsuneModule`;
- `name` — короткое и уникальное имя, по нему модуль виден в `.help`;
- `@command("hello")` — создаёт команду `.hello`;
- `required=OWNER` — команду можешь вызывать только ты.

Сохрани файл и загрузи через `.loadmod`.

---

## Атрибуты класса

Можно задать прямо в классе:

| Атрибут | Зачем | Обязателен? |
|---|---|---|
| `name` | Имя модуля, должно быть уникальным | да |
| `description` | Описание, показывается в `.help` | желательно |
| `author` | Автор | нет |
| `version` | Версия, например `"1.0.0"` | нет |
| `icon` | Эмодзи-иконка, по умолчанию 📦 | нет |
| `category` | Группа в `.help`, по умолчанию `"other"` | нет |
| `requires` | Имена модулей, которые должны быть загружены раньше | нет |
| `role_db_owner` | Хранилище для кастомных ролей (см. ниже) | нет |
| `pip_requires` | Питоновские библиотеки для автоустановки | нет |
| `system_requires` | Системные утилиты (например `"ffmpeg"`) | нет |

Если `name` не написать, Kitsune возьмёт имя класса.

---

## Команды

Команда делается декоратором `@command`:

```python
@command("repeat", required=OWNER, aliases=["r"])
async def repeat_cmd(self, event):
    text = self.get_args(event)
    if not text:
        await event.reply("Напиши текст после команды")
        return
    await event.reply(text)
```

- **Первый аргумент** — имя команды без точки. Если не указать, возьмётся имя
  метода без окончания `_cmd`.
- **`required`** — кто может вызывать. Почти всегда ставь `OWNER`.
- **`aliases`** — дополнительные имена, тут `.r` тоже сработает.
- **`get_args(event)`** — всё, что написано после имени команды.

---

## Кто может вызывать команду

Уровни доступа лежат в `kitsune.core.security`:

| Константа | Кто |
|---|---|
| `OWNER` | Владелец юзербота (ты) |
| `SUDO` | Доверенные, добавленные через `.sudoadd` |
| `SUPPORT` | Уровень поддержки |
| `GROUP_OWNER` | Создатель чата |
| `GROUP_ADMIN` | Администратор чата |
| `GROUP_MEMBER` | Любой участник чата |
| `PM` | Личные сообщения |
| `EVERYONE` | Вообще все |

Можно комбинировать через `|`:

```python
@command("kick", required=OWNER | SUDO)
```

По умолчанию Kitsune реагирует только на **твои** сообщения. Чтобы команду мог
вызвать кто-то ещё, добавь `incoming=True`:

```python
@command("ping", required=SUDO, incoming=True)
async def ping_cmd(self, event):
    await event.reply("🏓 Понг!")
```

---

## Кастомные роли

Иногда не хочется давать человеку весь sudo, а нужен доступ только к паре
команд. Для этого есть текстовые роли — просто напиши строку в `required`:

```python
GAMER = "gamer"

class GameModule(KitsuneModule):
    name = "gamemod"

    @command("play", required=GAMER)
    async def play_cmd(self, event):
        await event.reply("Играем! 🎮")

    @command("gameradd", required=OWNER)
    async def gameradd_cmd(self, event):
        reply = await event.message.get_reply_message()
        if not reply or not reply.sender_id:
            await event.reply("Ответь на сообщение нужного пользователя")
            return
        uid = reply.sender_id
        users = self.db.get(self.name, "gamer_users", [])
        if uid not in users:
            users.append(uid)
            await self.db.set(self.name, "gamer_users", users)
        await event.reply("✅ Доступ выдан")
```

Тут `self.name` — это `"gamemod"`, поэтому список пользователей роли `gamer`
хранится под ключом `gamemod.gamer_users`. Именно так Kitsune сам ищет роли, так
что ничего дополнительно настраивать не надо.

Если хочешь, чтобы одна роль была общей для нескольких модулей, задай
`role_db_owner = "общее_имя"` — тогда роли будут лежать в этом общем хранилище.

---

## Watchers — реакция без команды

Watcher срабатывает на сообщения, в которых нет команды:

```python
from kitsune.core.loader import watcher

@watcher()
async def hello_watcher(self, event):
    text = event.message.raw_text or ""
    if "привет" in text.lower():
        await event.reply("Привет! 👋")
```

Watcher без условия будет срабатывать на **каждое** сообщение, поэтому внутри
всегда проверяй текст сам и не делай ничего тяжёлого.

---

## База данных

У модуля есть `self.db` — простое хранилище «ключ → значение», которое переживает
перезапуск:

```python
# прочитать (третий аргумент — значение по умолчанию)
count = self.db.get(self.name, "count", 0)

# записать
await self.db.set(self.name, "count", count + 1)
```

- Первый аргумент — «владелец» записи. Удобно использовать `self.name`, чтобы не
  пересечься с другими модулями.
- Значения можно хранить любые простые: строку, число, true/false, список, словарь.

```python
class CounterModule(KitsuneModule):
    name = "counter"

    @command("count", required=OWNER)
    async def count_cmd(self, event):
        n = self.db.get(self.name, "count", 0) + 1
        await self.db.set(self.name, "count", n)
        await event.reply("Счётчик: " + str(n))
```

---

## Настройки модуля

Если хочешь, чтобы пользователь менял что-то через `.config`, опиши настройки:

```python
from kitsune.core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from kitsune.core.security import OWNER
from kitsune.validators import Boolean, Integer, String

class GreetModule(KitsuneModule):
    name = "greetmod"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = ModuleConfig(
            ConfigValue("name", default="друг", doc="Кого приветствовать",
                        validator=String(max_len=50)),
            ConfigValue("times", default=1, doc="Сколько раз поздороваться",
                        validator=Integer(minimum=1, maximum=5)),
            ConfigValue("silent", default=False, doc="Не отвечать совсем",
                        validator=Boolean()),
        )

    @command("hello", required=OWNER)
    async def hello_cmd(self, event):
        if self.config["silent"]:
            return
        times = self.config["times"]
        name = self.config["name"]
        await event.reply(("Привет, " + name + "! 👋\n") * times)
```

Значения читаются через `self.config["ключ"]`, а сами настройки сохраняются в БД
автоматически.

Что можно использовать как `validator` (из `kitsune.validators`):

- `Boolean()` — да/нет, true/false, 1/0, on/off
- `Integer(minimum=..., maximum=...)` — целое число
- `Float(minimum=..., maximum=...)` — дробное число
- `String(min_len=..., max_len=...)` — строка
- `Choice([...])` — одно значение из списка
- `MultiChoice([...])` — несколько значений из списка
- `Link()` — ссылка http/https
- `TelegramID()` — ID пользователя или чата
- `Hidden()` — секрет, который не видно в `.config` (токены и пароли)
- `RegExp("образец")` — строка, подходящая под регулярное выражение
- `Series(...)` — список однотипных значений
- `Union(...)` — любое из нескольких проверяемых значений

---

## Локализация

Храни тексты отдельно для языков, а выводи через `self.strings`:

```python
class HelloModule(KitsuneModule):
    name = "hello"

    strings_ru = {"hello": "Привет, {name}!"}
    strings_en = {"hello": "Hello, {name}!"}

    @command("hello", required=OWNER)
    async def hello_cmd(self, event):
        await event.reply(self.strings("hello", name="друг"))
```

Kitsune сам возьмёт нужный язык, а `{name}` подставится из аргументов. Если языка
нет — откат на русский, потом на английский.

---

## on_load и on_unload

`on_load` вызывается один раз после загрузки модуля, `on_unload` — перед выгрузкой:

```python
import asyncio

async def on_load(self):
    self._task = asyncio.create_task(self._loop())

async def on_unload(self):
    self._task.cancel()

async def _loop(self):
    while True:
        await asyncio.sleep(60)
        # что-то раз в минуту
```

Правило простое: всё, что запустил в `on_load`, погаси в `on_unload`. Иначе после
перезагрузки модуля останутся висеть фоновые задачи.

---

## Зависимости

Если модулю нужен другой модуль — укажи явно, и Kitsune выдаст понятную ошибку,
а не молча упадёт:

```python
class MyModule(KitsuneModule):
    name = "mymod"
    requires = ["ping"]
```

Если нужна сторонняя библиотека — просто импортируй её как обычно. Загрузчик
попробует поставить её через pip сам:

```python
import PIL  # поставится как Pillow, если её нет
```

Для известных библиотек маппинг уже есть (`PIL` → `Pillow`, `cv2` →
`opencv-python`, `yaml` → `PyYAML` и т.д.). Если чего-то с системного уровня
(например `ffmpeg`), укажи его отдельно:

```python
class MyModule(KitsuneModule):
    name = "mymod"
    system_requires = ["ffmpeg"]
```

---

## Безопасность

Перед запуском модуля Kitsune прогоняет его код через статический сканер.
Запомни главное: это **дополнительный защитный слой, а не песочница**. Он не даёт
стопроцентной гарантии.

Сканер отсекает очевидно вредоносные вещи:

- запуск внешних процессов (`subprocess`, `os.system` и похожее);
- `eval` / `exec` / `compile` с непонятным содержимым;
- доступ к внутренностям Python вроде `__subclasses__`, `__globals__`,
  `__builtins__` и обходные пути через них;
- чтение чужих сессий и ключей.

Но хитрый код, который прячет свои действия, сканер может пропустить. Поэтому:

- ставь модули только из источников, которым доверяешь;
- чужие модули сперва читай глазами;
- не раздавай свою сессию и токены.

Для запросов в интернет можно пользоваться общей сессией:

```python
from kitsune.net import get_shared_session

sess = get_shared_session()
# не закрывай её сам — это общая сессия на весь бот
```

---

## Что ещё есть у модуля

| Атрибут/метод | Что это |
|---|---|
| `self.client` | Клиент Telegram, через него все обращения к API |
| `self.db` | База данных: `.get()`, `.set()`, `.set_sync()` |
| `self.config` | Настройки модуля, если объявлены |
| `self.tg_id` | Твой Telegram ID |
| `self.inline` | Движок inline-режима |
| `self.get_args(event)` | Текст после команды |
| `self.strings(key, **kwargs)` | Локализованная строка |
| `self.name` | Имя модуля |
| `self.lookup(name)` | Найти другой загруженный модуль |
| `self.get_prefix()` | Текущий префикс команд |

---

## Готовые примеры

Смотри встроенные модули в `kitsune/modules/`:

| Модуль | Что показывает |
|---|---|
| `ping.py` | Самая простая команда — начать отсюда |
| `weather.py` | Настройки и запросы в интернет |
| `backup.py` | Работа с файлами и ролями |
| `kitsune_security.py` | Управление правами пользователей |

Логи для отладки лежат в `~/.kitsune/logs/`.
