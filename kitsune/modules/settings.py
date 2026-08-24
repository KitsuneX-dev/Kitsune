import inspect

from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER

_DB_OWNER = "kitsune.core"

class SettingsModule(KitsuneModule):
    name        = "settings"
    description = "Настройки Kitsune"
    version     = "1.5.0"
    author      = "Yushi"
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.config = ModuleConfig(
            ConfigValue("prefix",   default=".",  doc="Префикс команд"),
            ConfigValue("lang",     default="ru", doc="Язык интерфейса (ru/en/de)"),
            ConfigValue("autodel",  default=True, doc="Авто-удаление сервисных сообщений"),
        )
    strings_ru = {
        "prefix_set":    "✅ Префикс изменён на <code>{p}</code>",
        "prefix_same":   "ℹ️ Префикс уже <code>{p}</code>",
        "prefix_usage":  "Использование: <code>{pfx}prefix &lt;символ&gt;</code> или <code>{pfx}setprefix &lt;символ&gt;</code>",
        "lang_set":      "✅ Язык изменён на <code>{lang}</code>",
        "lang_usage":    "Использование: <code>.lang &lt;ru|en|de|...&gt;</code>",
        "info_header":   "🦊 <b>Kitsune Userbot</b>\n\n",
        "info_line":     "<b>{key}:</b> <code>{val}</code>\n",
        "alias_emoji":   "🦊",
        "aliases_empty": "🦊 <b>Алиасы не заданы.</b>\n\nСоздать: <code>.addalias &lt;алиас&gt; &lt;команда&gt;</code>",
        "aliases_list":  "🦊 <b>Список алиасов:</b>\n",
        "alias_args":    (
            "❌ <b>Неверные аргументы.</b>\n\n"
            "Использование:\n"
            "<code>.addalias &lt;алиас&gt; &lt;команда&gt;</code>\n"
            "<code>.addalias длм, dl dlm</code>\n\n"
            "Можно указывать несколько строк — по одному алиасу на строку."
        ),
        "no_command":    "❌ Команда <code>{}</code> не найдена.",
        "alias_exists":  "⚠️ Алиас <code>{alias}</code> уже занят: <code>{command}</code>",
        "alias_created": "✅ Алиас <code>{}</code> создан.",
        "aliases_created": "✅ Создано алиасов: <b>{count}</b>\n<blockquote expandable>{aliases}</blockquote>",
        "aliases_created_line": "🦊 <code>{aliases}</code> → <code>{command}</code>",
        "delalias_args": (
            "❌ <b>Укажи алиас(ы) для удаления.</b>\n\n"
            "Использование: <code>.delalias &lt;алиас&gt;</code>\n"
            "Очистить все: <code>.delalias -c</code>"
        ),
        "alias_removed":  "✅ Алиас <code>{}</code> удалён.",
        "aliases_removed": "✅ Удалено алиасов: <b>{count}</b>\n<code>{aliases}</code>",
        "no_alias":       "⚠️ Алиас <code>{}</code> не найден.",
        "aliases_cleared": "🗑 Все алиасы удалены.",
        "la_no_file":     "❌ Пришли <b>.json</b>-файл с командой или ответом на него.",
        "la_bad_file":    "❌ Не удалось прочитать файл. Ожидается JSON-массив вида <code>[{{\"alias\": \"длм\", \"command\": \"dlm\"}}]</code>.",
        "la_loaded":      "✅ Загружено алиасов: <b>{count}</b>\n<blockquote expandable>{aliases}</blockquote>",
        "la_none":        "⚠️ Ни один алиас не загружен (пусто, дубликаты или неизвестные команды).",
        "al_export":      "🦊 Экспорт алиасов Kitsune ({count} шт.)",
        "al_empty":       "🦊 <b>Алиасы не заданы</b> — нечего экспортировать.",
        "tc_usage":       (
            "❌ <b>Неверные аргументы.</b>\n\n"
            "Использование:\n"
            "<code>.togglecmd &lt;команда&gt;</code>\n"
            "<code>.togglecmd &lt;модуль&gt; &lt;команда&gt;</code>"
        ),
        "tc_no_command":  "❌ Команда <code>{}</code> не найдена.",
        "tc_no_module":   "❌ Модуль <code>{}</code> не найден.",
        "tc_disabled":    "🚫 Команда <code>{cmd}</code> отключена.",
        "tc_enabled":     "✅ Команда <code>{cmd}</code> включена.",
        "tc_list_empty":  "🦊 <b>Отключённых команд нет.</b>",
        "tc_list":        "🚫 <b>Отключённые команды:</b>\n<blockquote expandable>{items}</blockquote>",
    }
    @command("prefix", required=OWNER)
    async def prefix_cmd(self, event) -> None:
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        current_prefix = dispatcher._prefix if dispatcher else "."
        raw = event.message.text[len(current_prefix):].split(maxsplit=1)
        if len(raw) < 2 or not raw[1].strip():
            await event.reply(
                self.strings("prefix_usage").format(pfx=current_prefix),
                parse_mode="html",
            )
            return
        new_prefix = raw[1].strip()[:3]
        old_prefix = dispatcher._prefix if dispatcher else self.db.get(_DB_OWNER, "prefix", ".")
        if new_prefix == old_prefix:
            await event.reply(
                self.strings("prefix_same").format(p=new_prefix), parse_mode="html"
            )
            return
        await self.db.set(_DB_OWNER, "prefix", new_prefix)
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        if dispatcher:
            dispatcher.set_prefix(new_prefix)
        try:
            import toml
            from ..paths import effective_config_path
            cfg_path = effective_config_path()
            if cfg_path.exists():
                cfg = toml.loads(cfg_path.read_text(encoding="utf-8"))
                cfg["prefix"] = new_prefix
                cfg_path.write_text(toml.dumps(cfg), encoding="utf-8")
        except Exception:
            pass
        await event.reply(self.strings("prefix_set").format(p=new_prefix), parse_mode="html")
    @command("setprefix", required=OWNER)
    async def setprefix_cmd(self, event) -> None:
        await self.prefix_cmd(event)
    @command("assetcheck", required=OWNER)
    async def assetcheck_cmd(self, event) -> None:
        try:
            from ..assets import diagnose, setup_all_avatars
            report = await diagnose(self.client, self.db)
            await event.reply(report, parse_mode="html")
            await setup_all_avatars(self.client, self.db)
            await event.reply("✅ Установка аватарок запущена. Смотри логи.", parse_mode="html")
        except Exception as exc:
            await event.reply(f"❌ Ошибка: <code>{exc}</code>", parse_mode="html")
    @command("lang", required=OWNER)
    async def lang_cmd(self, event) -> None:
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        current_prefix = dispatcher._prefix if dispatcher else "."
        raw = event.message.text[len(current_prefix):].split(maxsplit=1)
        if len(raw) < 2 or not raw[1].strip():
            await event.reply(self.strings("lang_usage"), parse_mode="html")
            return
        lang = raw[1].strip().lower()[:5]
        await self.db.set(_DB_OWNER, "lang", lang)
        await event.reply(self.strings("lang_set").format(lang=lang), parse_mode="html")
    def _dispatcher(self):
        return getattr(self.client, "_kitsune_dispatcher", None)
    async def _save_aliases(self) -> None:
        dispatcher = self._dispatcher()
        if dispatcher is not None:
            await self.db.set(_DB_OWNER, "aliases", dispatcher.get_aliases())
    @command("aliases", required=OWNER)
    async def aliases_cmd(self, event) -> None:
        from ..utils import escape_html
        dispatcher = self._dispatcher()
        current = dispatcher.get_aliases() if dispatcher else {}
        if not current:
            await event.reply(self.strings("aliases_empty"), parse_mode="html")
            return
        emoji = self.strings("alias_emoji")
        body = "\n".join(
            f"{emoji} <code>{escape_html(alias)}</code> ← <code>{escape_html(target)}</code>"
            for alias, target in sorted(current.items())
        )
        await event.reply(
            self.strings("aliases_list") + f"<blockquote expandable>{body}</blockquote>",
            parse_mode="html",
        )
    @command("addalias", required=OWNER)
    async def addalias_cmd(self, event) -> None:
        from ..utils import escape_html
        dispatcher = self._dispatcher()
        args_raw = self.get_args(event)
        if not args_raw or dispatcher is None:
            await event.reply(self.strings("alias_args"), parse_mode="html")
            return
        alias_lines: list[tuple[list[str], str, str | None]] = []
        for line in args_raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if "," in line:
                parts = [p.strip() for p in line.split(",")]
                last = parts[-1].split(maxsplit=1)
                if len(last) < 2:
                    await event.reply(self.strings("alias_args"), parse_mode="html")
                    return
                aliases = [p.lower() for p in parts[:-1] if p]
                aliases.append(last[0].lower())
                command_str = last[1]
            else:
                pair = line.split(maxsplit=1)
                if len(pair) < 2:
                    await event.reply(self.strings("alias_args"), parse_mode="html")
                    return
                aliases = [pair[0].lower()]
                command_str = pair[1]
            command_parts = command_str.split(maxsplit=1)
            cmd = command_parts[0].lower()
            rest = command_parts[1] if len(command_parts) > 1 else None
            if cmd not in dispatcher._commands:
                await event.reply(
                    self.strings("no_command").format(escape_html(cmd)), parse_mode="html"
                )
                return
            alias_lines.append((aliases, cmd, rest))
        if not alias_lines:
            await event.reply(self.strings("alias_args"), parse_mode="html")
            return
        added_lines: list[tuple[list[str], str]] = []
        skipped_lines: list[str] = []
        planned: dict[str, str] = {}
        existing = dispatcher.get_aliases()
        for aliases, cmd, rest in alias_lines:
            target = f"{cmd} {rest}" if rest else cmd
            added_here: list[str] = []
            for alias in aliases:
                clash = existing.get(alias) or planned.get(alias)
                if clash:
                    skipped_lines.append(
                        self.strings("alias_exists").format(
                            alias=escape_html(alias), command=escape_html(clash)
                        )
                    )
                    continue
                if not dispatcher.add_alias(alias, cmd, rest):
                    await event.reply(
                        self.strings("no_command").format(escape_html(cmd)),
                        parse_mode="html",
                    )
                    return
                planned[alias] = target
                added_here.append(alias)
            if added_here:
                added_lines.append((added_here, target))
        if added_lines:
            await self._save_aliases()
        if len(added_lines) == 1 and len(added_lines[0][0]) == 1 and not skipped_lines:
            await event.reply(
                self.strings("alias_created").format(escape_html(added_lines[0][0][0])),
                parse_mode="html",
            )
            return
        response: list[str] = []
        if added_lines:
            added_count = sum(len(a) for a, _ in added_lines)
            response.append(
                self.strings("aliases_created").format(
                    count=added_count,
                    aliases="\n".join(
                        self.strings("aliases_created_line").format(
                            aliases=escape_html(", ".join(a)), command=escape_html(t)
                        )
                        for a, t in added_lines
                    ),
                )
            )
        response.extend(skipped_lines)
        await event.reply("\n\n".join(response) or self.strings("alias_args"), parse_mode="html")
    @command("delalias", required=OWNER)
    async def delalias_cmd(self, event) -> None:
        from ..utils import escape_html
        dispatcher = self._dispatcher()
        args_raw = self.get_args(event).strip()
        if not args_raw or dispatcher is None:
            await event.reply(self.strings("delalias_args"), parse_mode="html")
            return
        if args_raw in ("-c", "--clear", "все", "all"):
            for alias in list(dispatcher.get_aliases()):
                dispatcher.remove_alias(alias)
            await self._save_aliases()
            await event.reply(self.strings("aliases_cleared"), parse_mode="html")
            return
        seen: set[str] = set()
        aliases: list[str] = []
        for line in args_raw.splitlines():
            for alias in line.split(","):
                alias = alias.lower().strip()
                if alias and alias not in seen:
                    aliases.append(alias)
                    seen.add(alias)
        if not aliases:
            await event.reply(self.strings("delalias_args"), parse_mode="html")
            return
        removed: list[str] = []
        missed: list[str] = []
        for alias in aliases:
            if dispatcher.remove_alias(alias):
                removed.append(alias)
            else:
                missed.append(alias)
        if removed:
            await self._save_aliases()
        if len(removed) == 1 and not missed:
            await event.reply(
                self.strings("alias_removed").format(escape_html(removed[0])),
                parse_mode="html",
            )
            return
        response: list[str] = []
        if removed:
            response.append(
                self.strings("aliases_removed").format(
                    count=len(removed), aliases=escape_html(", ".join(removed))
                )
            )
        response.extend(self.strings("no_alias").format(escape_html(a)) for a in missed)
        await event.reply("\n\n".join(response), parse_mode="html")
    @command("loadaliases", required=OWNER, aliases=["la"])
    async def loadaliases_cmd(self, event) -> None:
        import json
        from ..utils import escape_html
        dispatcher = self._dispatcher()
        if dispatcher is None:
            await event.reply(self.strings("la_no_file"), parse_mode="html")
            return
        reply = await event.message.get_reply_message()
        msg = reply if (reply and reply.file) else (event.message if event.message.file else None)
        if not msg or not msg.file:
            await event.reply(self.strings("la_no_file"), parse_mode="html")
            return
        try:
            raw = await msg.download_media(bytes)
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            await event.reply(self.strings("la_bad_file"), parse_mode="html")
            return
        if not isinstance(data, list) or not all(
            isinstance(item, dict) and "alias" in item and "command" in item
            for item in data
        ):
            await event.reply(self.strings("la_bad_file"), parse_mode="html")
            return
        loaded: list[tuple[str, str]] = []
        for item in data:
            alias = str(item["alias"]).lower().strip()
            cmd_str = str(item["command"]).strip()
            if not alias or not cmd_str:
                continue
            parts = cmd_str.split(maxsplit=1)
            cmd = parts[0].lower()
            rest = parts[1] if len(parts) > 1 else None
            if alias in dispatcher.get_aliases():
                continue
            if dispatcher.add_alias(alias, cmd, rest):
                loaded.append((alias, f"{cmd} {rest}" if rest else cmd))
        if not loaded:
            await event.reply(self.strings("la_none"), parse_mode="html")
            return
        await self._save_aliases()
        body = "\n".join(
            f"🦊 <code>{escape_html(a)}</code> → <code>{escape_html(t)}</code>"
            for a, t in loaded
        )
        await event.reply(
            self.strings("la_loaded").format(count=len(loaded), aliases=body),
            parse_mode="html",
        )
    @command("aliasload", required=OWNER, aliases=["al"])
    async def aliasload_cmd(self, event) -> None:
        import io, json
        dispatcher = self._dispatcher()
        current = dispatcher.get_aliases() if dispatcher else {}
        if not current:
            await event.reply(self.strings("al_empty"), parse_mode="html")
            return
        payload = [{"alias": alias, "command": target} for alias, target in sorted(current.items())]
        buf = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
        buf.name = "kitsune_aliases.json"
        await self.client.send_file(
            event.message.chat_id,
            buf,
            caption=self.strings("al_export").format(count=len(current)),
            reply_to=getattr(event.message, "reply_to_msg_id", None),
        )
    async def _save_disabled(self) -> None:
        dispatcher = self._dispatcher()
        if dispatcher is not None:
            await self.db.set(_DB_OWNER, "disabled_commands", dispatcher.get_disabled_commands())
    @command("togglecmd", required=OWNER)
    async def togglecmd_cmd(self, event) -> None:
        from ..utils import escape_html
        dispatcher = self._dispatcher()
        if dispatcher is None:
            await event.reply(self.strings("tc_usage"), parse_mode="html")
            return
        args = self.get_args(event).split()
        if not args:
            await event.reply(self.strings("tc_usage"), parse_mode="html")
            return
        if len(args) >= 2:
            mod_arg, cmd = args[0], args[1].lower()
            mod = self.lookup(mod_arg)
            if mod is None:
                await event.reply(
                    self.strings("tc_no_module").format(escape_html(mod_arg)),
                    parse_mode="html",
                )
                return
            mod_cmds = {
                getattr(m, "_command_name", "").lower()
                for _, m in inspect.getmembers(mod, predicate=callable)
                if getattr(m, "_is_command", False)
            }
            if cmd not in mod_cmds:
                await event.reply(
                    self.strings("tc_no_command").format(escape_html(cmd)),
                    parse_mode="html",
                )
                return
        else:
            cmd = args[0].lower()
            if cmd not in dispatcher._commands:
                await event.reply(
                    self.strings("tc_no_command").format(escape_html(cmd)),
                    parse_mode="html",
                )
                return
        if dispatcher.is_command_disabled(cmd):
            dispatcher.enable_command(cmd)
            await self._save_disabled()
            await event.reply(
                self.strings("tc_enabled").format(cmd=escape_html(cmd)),
                parse_mode="html",
            )
        else:
            dispatcher.disable_command(cmd)
            await self._save_disabled()
            await event.reply(
                self.strings("tc_disabled").format(cmd=escape_html(cmd)),
                parse_mode="html",
            )
    @command("disabledcmds", required=OWNER)
    async def disabledcmds_cmd(self, event) -> None:
        from ..utils import escape_html
        dispatcher = self._dispatcher()
        disabled = dispatcher.get_disabled_commands() if dispatcher else []
        if not disabled:
            await event.reply(self.strings("tc_list_empty"), parse_mode="html")
            return
        prefix = dispatcher._prefix if dispatcher else "."
        items = "\n".join(f"🚫 <code>{prefix}{escape_html(c)}</code>" for c in disabled)
        await event.reply(self.strings("tc_list").format(items=items), parse_mode="html")
    @command("autodel", required=OWNER)
    async def autodel_cmd(self, event) -> None:
        arg = self.get_args(event).strip().lower()
        if not arg:
            current = self.db.get(_DB_OWNER, "auto_delete_delay", 0)
            status = f"<code>{current} сек</code>" if current else "выключено"
            await event.reply(
                f"🗑 Авто-удаление сервисных сообщений: {status}\n\n"
                "Использование: <code>.autodel 5</code> или <code>.autodel off</code>",
                parse_mode="html",
            )
            return
        if arg in ("off", "0", "нет", "выкл"):
            await self.db.set(_DB_OWNER, "auto_delete_delay", 0)
            await event.reply("🗑 Авто-удаление выключено.", parse_mode="html")
            return
        try:
            delay = float(arg)
            if delay < 1 or delay > 300:
                raise ValueError
        except ValueError:
            await event.reply(
                "❌ Укажи число секунд от 1 до 300, или <code>off</code>.",
                parse_mode="html",
            )
            return
        await self.db.set(_DB_OWNER, "auto_delete_delay", delay)
        self.client._kitsune_db = self.db
        await event.reply(
            f"🗑 Авто-удаление сервисных сообщений через <b>{delay:.0f} сек</b>.",
            parse_mode="html",
        )
    @command("sysinfo", required=OWNER)
    async def sysinfo_cmd(self, event) -> None:
        import platform, sys, psutil
        from ..version import __version_str__
        from ..utils import IS_TERMUX, IS_DOCKER
        try:
            import psutil as _ps
            mem = _ps.virtual_memory()
            cpu = _ps.cpu_percent(interval=0.2)
        except ImportError:
            mem = None
            cpu = 0.0
        env_tag = (
            "Termux" if IS_TERMUX
            else "Docker" if IS_DOCKER
            else platform.system()
        )
        loader = getattr(self.client, "_kitsune_loader", None)
        mod_count = len(loader.modules) if loader else 0
        lines = [
            self.strings("info_header"),
            self.strings("info_line").format(key="Версия",   val=__version_str__),
            self.strings("info_line").format(key="Python",   val=sys.version.split()[0]),
            self.strings("info_line").format(key="Среда",    val=env_tag),
            self.strings("info_line").format(key="Модули",   val=mod_count),
            self.strings("info_line").format(key="ОЗУ",      val=f"{(mem.used // 1024 // 1024) if mem else 0} / {(mem.total // 1024 // 1024) if mem else 0} МБ"),
            self.strings("info_line").format(key="CPU",      val=f"{cpu:.1f}%"),
        ]
        await event.reply("".join(lines), parse_mode="html")
