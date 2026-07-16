# Writing Modules for Kitsune

This reference covers the full module development API. Read sequentially or jump to the relevant section.

---

## Table of Contents

1. [Module Location](#module-location)
2. [Minimal Module](#minimal-module)
3. [Class Attributes](#class-attributes)
4. [Commands — @command decorator](#commands--command-decorator)
5. [Access Levels](#access-levels)
6. [Custom Roles](#custom-roles)
7. [Incoming Commands — incoming=True](#incoming-commands--incomingtrue)
8. [Watchers](#watchers)
9. [Database](#database)
10. [Module Config](#module-config)
11. [Localization](#localization)
12. [Lifecycle Hooks — on_load and on_unload](#lifecycle-hooks--on_load-and-on_unload)
13. [EventBus](#eventbus)
14. [Module Dependencies](#module-dependencies)
15. [Automatic Dependency Installation](#automatic-dependency-installation)
16. [Security Restrictions](#security-restrictions)
17. [Available Module Attributes](#available-module-attributes)
18. [Examples](#examples)

---

## Module Location

User modules are stored in `~/.kitsune/modules/`. A module can be placed in one of three ways:

- Drop a `.py` file directly into the directory
- Install via `.loadmod` (from a URL or local file)
- Create a package — a directory containing `__init__.py`

Kitsune loads everything present in that directory at startup. The only requirement is that the file contains a class inheriting from `KitsuneModule`. Files without such a class are silently skipped.

---

## Minimal Module

```python
from kitsune.core.loader import KitsuneModule, command
from kitsune.core.security import OWNER

class HelloModule(KitsuneModule):
    name        = "hello"
    description = "A simple test module"
    author      = "you"
    version     = "1.0.0"

    @command("hello", required=OWNER)
    async def hello_cmd(self, event) -> None:
        await event.reply("Hello from Kitsune! 👋")
```

Save to `~/.kitsune/modules/hello.py` and load with `.loadmod`.

---

## Class Attributes

| Attribute | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | yes | Unique module identifier |
| `description` | `str` | recommended | Shown in `.help` |
| `author` | `str` | no | Informational |
| `version` | `str` | no | Any format; conventionally `"1.0.0"` |
| `icon` | `str` | no | Emoji icon; defaults to `📦` |
| `category` | `str` | no | `.help` category; defaults to `"other"` |
| `requires` | `list[str]` | no | Module names that must be loaded before this one |
| `role_db_owner` | `str` | no | Overrides the database namespace for custom roles |

If `name` is omitted, the class name is used.

---

## Commands — @command decorator

```python
from kitsune.core.loader import command
from kitsune.core.security import OWNER, SUDO

@command("say", required=OWNER, aliases=["echo"])
async def say_cmd(self, event) -> None:
    text = self.get_args(event)
    if not text:
        await event.reply("Provide text to repeat")
        return
    await event.reply(text)
```

**Decorator parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | method name without `_cmd` | Command name, without prefix |
| `required` | `int` or `str` | `0` | Access level (see below) |
| `aliases` | `list[str]` | `None` | Additional command aliases |
| `incoming` | `bool` | `False` | React to commands from other users |

**`self.get_args(event)`** returns everything after the command name, with the prefix and command itself stripped.

---

## Access Levels

Import from `kitsune.core.security`:

```python
from kitsune.core.security import OWNER, SUDO, SUPPORT, EVERYONE, GROUP_ADMIN
```

| Constant | Who has access |
|---|---|
| `OWNER` | Userbot owner only. Default for all built-in commands |
| `SUDO` | Trusted users added via `.sudoadd` |
| `SUPPORT` | Support-tier users |
| `GROUP_ADMIN` | Any administrator in a group |
| `GROUP_OWNER` | Group creator |
| `EVERYONE` | All users, including strangers |
| `PM` | Private messages only |

Levels can be combined with `|`:

```python
@command("modcmd", required=OWNER | SUDO)
```

---

## Custom Roles

Custom roles allow granting access to specific commands without issuing global sudo. A role is defined as a plain string passed to `required=`.

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
        await event.reply(f"✅ {target.first_name} can now use RP commands")

    @command("rpdel", required=OWNER)
    async def rpdel_cmd(self, event) -> None:
        target = await self.client.get_entity(event.message.mentioned_users[0])
        users = [u for u in self.db.get(self.name, "rp_user_users", []) if u != target.id]
        await self.db.set(self.name, "rp_user_users", users)
        await event.reply(f"✅ Access revoked for {target.first_name}")
```

**How it works internally:**

The dispatcher resolves the user list from the database using the key:

```
<module_db_owner>.<role_name>_users
```

By default, `module_db_owner` is `module.name`. For role `"rp_user"` in module `rpmod`, the key is `rpmod.rp_user_users`.

That is why `rpadd_cmd` uses:

```python
self.db.get(self.name, "rp_user_users", [])
#           ^^^^^^^^^ — module_db_owner
#                        ^^^^^^^^^^^^^^ — <role_name>_users
```

To share a role list across multiple modules, override `role_db_owner`:

```python
class RPModule(KitsuneModule):
    name          = "rpmod"
    role_db_owner = "shared_rp"
```

> Commands with a string `required` value automatically behave as `incoming=True` — without it, no one other than the owner could invoke them. Declaring `incoming=True` explicitly is not required, but valid.

---

## Incoming Commands — incoming=True

By default, Kitsune only reacts to the owner's outgoing messages. To allow other users (sudo, co-owner, or custom role holders) to trigger a command, add `incoming=True`:

```python
@command("ping", required=SUDO, incoming=True)
async def ping_cmd(self, event) -> None:
    await event.reply("🏓 Pong!")
```

The dispatcher checks the sender's permissions via `SecurityManager`. If the check fails, the message is silently ignored.

**When to use `incoming=True` explicitly:**
- `required=SUDO` or `required=OWNER` — to allow those roles to invoke the command
- `required=EVERYONE` — to make the command available to anyone in the chat

**When it is not needed:**
- `required="role_name"` — `incoming=True` is set automatically for string roles

---

## Watchers

Watchers react to messages without a command trigger. A watcher fires on every matching message.

```python
from kitsune.core.loader import watcher

@watcher()
async def on_message(self, event) -> None:
    text = event.message.raw_text or ""
    if "buy subscription" in text.lower():
        await event.reply("No.")
```

A filter function can be passed:

```python
def only_groups(event) -> bool:
    return event.is_group

@watcher(filter_func=only_groups)
async def group_watcher(self, event) -> None:
    ...
```

> A watcher without a filter runs on every single message. Avoid any heavy operations inside.

---

## Database

Each module has access to `self.db` — a key-value store partitioned by namespace.

```python
# Save (async)
await self.db.set("mymodule", "counter", 42)

# Save (sync — for on_load and other synchronous contexts)
self.db.set_sync("mymodule", "counter", 42)

# Read (third argument is the default value)
counter = self.db.get("mymodule", "counter", 0)
```

Data persists across restarts. Using `self.name` as the namespace is recommended to avoid key collisions with other modules.

**Supported value types:** any JSON-compatible type — `str`, `int`, `float`, `bool`, `list`, `dict`.

---

## Module Config

To expose user-configurable parameters via `.config`, declare `self.config` in `__init__`:

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
                doc="Enable or disable the module",
                validator=Boolean(),
            ),
            ConfigValue(
                "max_count",
                default=10,
                doc="Maximum repeat count (1–100)",
                validator=Integer(minimum=1, maximum=100),
            ),
            ConfigValue(
                "prefix_text",
                default="",
                doc="Text prepended to each response",
                validator=String(max_len=50),
            ),
        )
```

Read a value:

```python
if self.config["enabled"]:
    count = self.config["max_count"]
```

Kitsune automatically restores saved config values from the database on load.

**Available validators** from `kitsune.validators`:

| Validator | Description |
|---|---|
| `Boolean()` | Accepts true/false, yes/no, 1/0 |
| `Integer(minimum=..., maximum=...)` | Integer with optional bounds |
| `Float(...)` | Floating-point number |
| `String(min_len=..., max_len=..., regex=...)` | String with optional constraints |
| `Choice(choices=[...])` | Single value from a fixed list |
| `MultiChoice(choices=[...])` | Multiple values from a fixed list |
| `Link()` | URL |
| `TelegramID()` | Telegram user or channel ID |
| `Hidden()` | String not displayed in `.config` — for tokens and secrets |
| `RegExp(pattern)` | String matching a regular expression |
| `Series(...)` | List of uniform values |
| `Union(validators=[...])` | Accepts any one of multiple types |

---

## Localization

Store strings in the class — Kitsune selects the appropriate language automatically:

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
        # With substitution:
        # await event.reply(self.strings("error", msg="something went wrong"))
```

If strings for the current language are missing, Kitsune falls back to `strings_ru`, then `strings_en`. If neither is defined, the key itself is returned.

---

## Lifecycle Hooks — on_load and on_unload

```python
async def on_load(self) -> None:
    # Called once after the module is loaded.
    # Use for initialization and starting background tasks.
    self._task = asyncio.create_task(self._background_loop())

async def on_unload(self) -> None:
    # Called before the module is unloaded.
    # Cancel tasks and close connections here.
    if hasattr(self, "_task"):
        self._task.cancel()
```

> If a module starts background tasks, they **must** be cancelled in `on_unload`. Tasks that are not cleaned up continue running after the module is unloaded.

---

## EventBus

Kitsune exposes an internal event bus for inter-module communication:

```python
from kitsune.events import bus
from kitsune._types import ModuleLoadedEvent

async def on_load(self) -> None:
    bus.subscribe(ModuleLoadedEvent, self._on_module_loaded)

async def on_unload(self) -> None:
    bus.unsubscribe(ModuleLoadedEvent, self._on_module_loaded)
    # Or unsubscribe all handlers registered by this module:
    # bus.unsubscribe_all(self)

async def _on_module_loaded(self, event: ModuleLoadedEvent) -> None:
    print(f"Module loaded: {event.module_name}")
```

**Available events** from `kitsune._types`:

| Event | Fields | Description |
|---|---|---|
| `ModuleLoadedEvent` | `module_name`, `is_builtin` | A module was loaded |
| `ModuleUnloadedEvent` | `module_name` | A module was unloaded |
| `ConfigChangedEvent` | `module_name`, `key`, `old_value`, `new_value` | A config value changed |
| `PrefixChangedEvent` | `old_prefix`, `new_prefix` | The command prefix changed |
| `SecurityChangedEvent` | `action`, `user_id`, `role` | User permissions changed |

> If you subscribe in `on_load`, you **must** unsubscribe in `on_unload`. Otherwise, reloading the module results in duplicate event handlers.

---

## Module Dependencies

If your module depends on another, declare it explicitly:

```python
class MyModule(KitsuneModule):
    name     = "mymod"
    requires = ["ping", "someothermodule"]
```

If the required modules are not loaded, the loader refuses to load yours and logs a clear error. This is preferable to an `AttributeError` at runtime.

---

## Automatic Dependency Installation

If a module requires a third-party library, the loader attempts to install it via pip automatically. Import as usual:

```python
import aiohttp  # included in Kitsune's dependencies; always available
import PIL      # the loader installs Pillow automatically if missing
```

Common package name mappings are built in (`PIL` → `Pillow`, `cv2` → `opencv-python`, `yaml` → `PyYAML`, etc.). Other packages are installed by their import name. On Termux, `--prefer-binary --no-build-isolation` flags are added automatically.

---

## Security Restrictions

Kitsune runs an AST scanner on every module before loading it.

**Blocked imports:**
`subprocess`, `pty`, `ctypes`, `multiprocessing`, `socket`, `pickle`, `marshal`, `shelve`, `dbm`, `runpy`, `distutils`, and others.

**Blocked calls:**
- `os.system()`, `os.popen()`, `os.fork()`, `os.kill()`, and other dangerous `os` methods
- `eval()`, `exec()`, `compile()` with dynamic or encoded content
- `__import__()` with dynamic arguments
- `globals()["os"]` and any dynamic key resolving to a blocked name
- Access to `__builtins__`, `__loader__`

If a violation is found, the module is rejected and `ASTSecurityError` is logged with the offending line number.

For HTTP requests, use `aiohttp`. Standard `open()` and `pathlib.Path` are available for file operations.

---

## Available Module Attributes

| Attribute | Description |
|---|---|
| `self.client` | Telethon client. Use for all Telegram API calls |
| `self.db` | Database (`.get()` / `.set()` / `.set_sync()`) |
| `self.config` | Module config values (if declared) |
| `self.tg_id` | Telegram ID of the userbot owner |
| `self.inline` | Inline engine (for inline mode) |
| `self.get_args(event)` | Arguments string, everything after the command |
| `self.strings(key, **kwargs)` | Localized string with optional substitution |
| `self.name` | Module name — convenient as a database namespace |

---

## Examples

### Simple command with arguments

```python
from kitsune.core.loader import KitsuneModule, command
from kitsune.core.security import OWNER

class EchoModule(KitsuneModule):
    name        = "echo"
    description = "Repeats text"

    @command("echo", required=OWNER, aliases=["say"])
    async def echo_cmd(self, event) -> None:
        text = self.get_args(event)
        if not text:
            await event.reply("Provide text to echo")
            return
        await event.edit(text)
```

---

### Module with a custom role

```python
from kitsune.core.loader import KitsuneModule, command
from kitsune.core.security import OWNER

GREETER = "greeter"

class GreetModule(KitsuneModule):
    name        = "greet"
    description = "Greeting from trusted users"

    @command("greet", required=GREETER)
    async def greet_cmd(self, event) -> None:
        await event.reply("Hello from a trusted user! 👋")

    @command("greetadd", required=OWNER)
    async def greetadd_cmd(self, event) -> None:
        reply = await event.get_reply_message()
        if not reply:
            await event.reply("Reply to a user's message")
            return
        uid = reply.sender_id
        users = self.db.get(self.name, "greeter_users", [])
        if uid not in users:
            users.append(uid)
            await self.db.set(self.name, "greeter_users", users)
        await event.reply("✅ Access granted")

    @command("greetdel", required=OWNER)
    async def greetdel_cmd(self, event) -> None:
        reply = await event.get_reply_message()
        if not reply:
            await event.reply("Reply to a user's message")
            return
        uid = reply.sender_id
        users = [u for u in self.db.get(self.name, "greeter_users", []) if u != uid]
        await self.db.set(self.name, "greeter_users", users)
        await event.reply("✅ Access revoked")
```

---

### Module with config, localization, and HTTP

```python
from __future__ import annotations
import aiohttp
from kitsune.core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from kitsune.core.security import OWNER
from kitsune.validators import String

class QuoteModule(KitsuneModule):
    name        = "quote"
    description = "Random quote"
    icon        = "💬"
    category    = "fun"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = ModuleConfig(
            ConfigValue(
                "lang",
                default="en",
                doc="Quote language: en or ru",
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

### Module with a background task

```python
import asyncio
from kitsune.core.loader import KitsuneModule, command
from kitsune.core.security import OWNER

class WatcherModule(KitsuneModule):
    name        = "watcher"
    description = "Background task example"

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
        await event.reply("✅ Task is running" if alive else "❌ Task is not running")
```

---

## Reference Modules

The built-in modules in `kitsune/modules/` cover all common patterns:

| Module | What to learn from it |
|---|---|
| `ping.py` | Simplest possible command — good starting point |
| `weather.py` | Config values and HTTP requests |
| `backup.py` | File operations and custom roles |
| `kitsune_security.py` | User permission management |

For debugging, check the logs at `~/.kitsune/logs/` or run Kitsune with `--debug`.
