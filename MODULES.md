# How to write modules for Kitsune

A plain-language guide to writing your own modules. No needless jargon — just
what actually matters to get a module running on version 1.4.4.

Read the first three sections and you can already ship a simple module. The rest
is here for when you need it.

---

## Where modules live

Two ways to install:

1. **From Telegram** — `.loadmod` (reply to a `.py` file) or `.dlmod` (by URL or
   by module name from a repository).
2. **By hand** — drop `my_module.py` into `~/.kitsune/modules/`. For bigger
   modules you can also use a folder with an `__init__.py` inside.

At startup Kitsune loads everything in that folder. The only hard requirement is
that the file contains a class inheriting from `KitsuneModule`. Files without such
a class are simply skipped — no errors.

---

## The smallest module

```python
from kitsune.core.loader import KitsuneModule, command
from kitsune.core.security import OWNER

class HelloModule(KitsuneModule):
    name = "hello"
    description = "A greeting"
    author = "you"
    version = "1.0.0"

    @command("hello", required=OWNER)
    async def hello_cmd(self, event):
        await event.reply("Hello from Kitsune! 👋")
```

What matters here:

- the class inherits from `KitsuneModule`;
- `name` is a short, unique identifier shown in `.help`;
- `@command("hello")` creates the `.hello` command;
- `required=OWNER` means only you can call it.

Save the file and load it with `.loadmod`.

---

## Class attributes

Set these directly on the class:

| Attribute | Purpose | Required? |
|---|---|---|
| `name` | Unique module name | yes |
| `description` | Shown in `.help` | recommended |
| `author` | Author | no |
| `version` | Version, e.g. `"1.0.0"` | no |
| `icon` | Emoji icon, defaults to 📦 | no |
| `category` | `.help` group, defaults to `"other"` | no |
| `requires` | Modules that must be loaded first | no |
| `role_db_owner` | Storage for custom roles (see below) | no |
| `pip_requires` | Python libraries to auto-install | no |
| `system_requires` | System utilities, e.g. `"ffmpeg"` | no |

If you omit `name`, Kitsune uses the class name.

---

## Commands

Commands are made with the `@command` decorator:

```python
@command("repeat", required=OWNER, aliases=["r"])
async def repeat_cmd(self, event):
    text = self.get_args(event)
    if not text:
        await event.reply("Type some text after the command")
        return
    await event.reply(text)
```

- **First argument** — the command name without the dot. If omitted, it is taken
  from the method name with `_cmd` stripped.
- **`required`** — who may call it. Almost always use `OWNER`.
- **`aliases`** — extra names, so `.r` also works here.
- **`get_args(event)`** — everything written after the command name.

---

## Who can call a command

Access levels live in `kitsune.core.security`:

| Constant | Who |
|---|---|
| `OWNER` | The userbot owner (you) |
| `SUDO` | Trusted users added via `.sudoadd` |
| `SUPPORT` | Support-tier users |
| `GROUP_OWNER` | Group creator |
| `GROUP_ADMIN` | Group administrator |
| `GROUP_MEMBER` | Any group member |
| `PM` | Private messages |
| `EVERYONE` | Anyone at all |

Combine them with `|`:

```python
@command("kick", required=OWNER | SUDO)
```

By default Kitsune only reacts to **your** messages. To let someone else trigger
a command, add `incoming=True`:

```python
@command("ping", required=SUDO, incoming=True)
async def ping_cmd(self, event):
    await event.reply("🏓 Pong!")
```

---

## Custom roles

Sometimes you don't want to give someone full sudo — just access to a couple of
commands. Text roles do exactly that: write a string in `required`:

```python
GAMER = "gamer"

class GameModule(KitsuneModule):
    name = "gamemod"

    @command("play", required=GAMER)
    async def play_cmd(self, event):
        await event.reply("Let's play! 🎮")

    @command("gameradd", required=OWNER)
    async def gameradd_cmd(self, event):
        reply = await event.message.get_reply_message()
        if not reply or not reply.sender_id:
            await event.reply("Reply to the user you want to add")
            return
        uid = reply.sender_id
        users = self.db.get(self.name, "gamer_users", [])
        if uid not in users:
            users.append(uid)
            await self.db.set(self.name, "gamer_users", users)
        await event.reply("✅ Access granted")
```

Here `self.name` is `"gamemod"`, so the user list for the `gamer` role is stored
under the key `gamemod.gamer_users`. That is exactly how Kitsune looks roles up,
so there is nothing extra to configure.

To share one role across several modules, set `role_db_owner = "shared_name"`.

---

## Watchers — reacting without a command

A watcher fires on messages that contain no command:

```python
from kitsune.core.loader import watcher

@watcher()
async def hello_watcher(self, event):
    text = event.message.raw_text or ""
    if "hello" in text.lower():
        await event.reply("Hi! 👋")
```

A watcher with no condition runs on **every** message, so always check the text
yourself and keep it light.

---

## Database

Every module has `self.db` — a simple key-value store that survives restarts:

```python
# read (third argument is the default)
count = self.db.get(self.name, "count", 0)

# write
await self.db.set(self.name, "count", count + 1)
```

- The first argument is the "owner" of the record. Using `self.name` is the
  recommended way to avoid collisions with other modules.
- Values may be any simple type: string, number, true/false, list, dict.

```python
class CounterModule(KitsuneModule):
    name = "counter"

    @command("count", required=OWNER)
    async def count_cmd(self, event):
        n = self.db.get(self.name, "count", 0) + 1
        await self.db.set(self.name, "count", n)
        await event.reply("Counter: " + str(n))
```

---

## Module config

If you want users to tweak things via `.config`, declare settings:

```python
from kitsune.core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from kitsune.core.security import OWNER
from kitsune.validators import Boolean, Integer, String

class GreetModule(KitsuneModule):
    name = "greetmod"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = ModuleConfig(
            ConfigValue("name", default="friend", doc="Who to greet",
                        validator=String(max_len=50)),
            ConfigValue("times", default=1, doc="How many times to greet",
                        validator=Integer(minimum=1, maximum=5)),
            ConfigValue("silent", default=False, doc="Don't reply at all",
                        validator=Boolean()),
        )

    @command("hello", required=OWNER)
    async def hello_cmd(self, event):
        if self.config["silent"]:
            return
        times = self.config["times"]
        name = self.config["name"]
        await event.reply(("Hello, " + name + "! 👋\n") * times)
```

Read values with `self.config["key"]`; saved values are restored from the
database automatically.

Useful `validator`s (from `kitsune.validators`):

- `Boolean()` — yes/no, true/false, 1/0, on/off
- `Integer(minimum=..., maximum=...)` — integer
- `Float(minimum=..., maximum=...)` — floating-point number
- `String(min_len=..., max_len=...)` — string
- `Choice([...])` — one value from a list
- `MultiChoice([...])` — several values from a list
- `Link()` — http/https URL
- `TelegramID()` — user or chat ID
- `Hidden()` — a secret hidden in `.config` (tokens, passwords)
- `RegExp("pattern")` — a string matching a regex
- `Series(...)` — list of uniform values
- `Union(...)` — any one of several validators

---

## Localization

Keep per-language strings and output them via `self.strings`:

```python
class HelloModule(KitsuneModule):
    name = "hello"

    strings_ru = {"hello": "Привет, {name}!"}
    strings_en = {"hello": "Hello, {name}!"}

    @command("hello", required=OWNER)
    async def hello_cmd(self, event):
        await event.reply(self.strings("hello", name="friend"))
```

Kitsune picks the right language and substitutes `{name}` from the arguments.
Missing languages fall back to Russian, then English.

---

## on_load and on_unload

`on_load` runs once after the module loads, `on_unload` before it unloads:

```python
import asyncio

async def on_load(self):
    self._task = asyncio.create_task(self._loop())

async def on_unload(self):
    self._task.cancel()

async def _loop(self):
    while True:
        await asyncio.sleep(60)
        # do something every minute
```

Simple rule: cancel in `on_unload` everything you started in `on_load`. Otherwise
background tasks keep running after a reload.

---

## Dependencies

If your module needs another module, declare it explicitly — Kitsune will give a
clear error instead of failing silently:

```python
class MyModule(KitsuneModule):
    name = "mymod"
    requires = ["ping"]
```

If a third-party library is needed, just import it as usual. The loader tries to
install it via pip automatically:

```python
import PIL  # installed as Pillow if missing
```

Common mappings are built in (`PIL` → `Pillow`, `cv2` → `opencv-python`, `yaml` →
`PyYAML`, etc.). For a system-level utility like `ffmpeg`, list it separately:

```python
class MyModule(KitsuneModule):
    name = "mymod"
    system_requires = ["ffmpeg"]
```

---

## Security

Before running a module, Kitsune passes its code through a static scanner.
Remember the key point: it is an **extra layer of protection, not a sandbox**. It
gives no 100% guarantee.

The scanner blocks obviously dangerous things:

- spawning external processes (`subprocess`, `os.system` and similar);
- `eval` / `exec` / `compile` with dynamic content;
- access to Python internals like `__subclasses__`, `__globals__`,
  `__builtins__` and bypass routes through them;
- reading other sessions and keys.

But clever code that hides its intentions can still slip through. Therefore:

- install modules only from sources you trust;
- read third-party modules with your own eyes first;
- never hand out your session or tokens.

For HTTP requests you can use the shared session:

```python
from kitsune.net import get_shared_session

sess = get_shared_session()
# don't close it yourself — it is shared across the whole bot
```

---

## Other things a module has

| Attribute/method | What it is |
|---|---|
| `self.client` | Telegram client, used for all API calls |
| `self.db` | Database: `.get()`, `.set()`, `.set_sync()` |
| `self.config` | Module config, if declared |
| `self.tg_id` | Your Telegram ID |
| `self.inline` | Inline-mode engine |
| `self.get_args(event)` | Text after the command |
| `self.strings(key, **kwargs)` | Localized string |
| `self.name` | Module name |
| `self.lookup(name)` | Find another loaded module |
| `self.get_prefix()` | Current command prefix |

---

## Ready-made examples

See the built-in modules in `kitsune/modules/`:

| Module | What it shows |
|---|---|
| `ping.py` | The simplest command — start here |
| `weather.py` | Config and HTTP requests |
| `backup.py` | File operations and roles |
| `kitsune_security.py` | User permission management |

Logs for debugging live in `~/.kitsune/logs/`.
