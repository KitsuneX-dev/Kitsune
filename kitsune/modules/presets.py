from __future__ import annotations

import asyncio
import io
from ..hydro_media import send_file as _hydro_send_file
import json
import logging
from pathlib import Path

from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER

logger = logging.getLogger(__name__)

_DB_OWNER = "kitsune.presets"

PRESETS: dict[str, dict] = {
    "fun": {
        "title": "🎮 Развлечения",
        "desc": "Игры, квоты, генераторы контента",
        "modules": [
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/aniquotes.py",
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/tictactoe.py",
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/trashguy.py",
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/magictext.py",
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/quotes.py",
        ],
    },
    "chat": {
        "title": "💬 Чат",
        "desc": "Управление чатами и участниками",
        "modules": [
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/tagall.py",
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/keyword.py",
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/inactive.py",
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/filter.py",
        ],
    },
    "service": {
        "title": "🛠 Сервис",
        "desc": "Полезные утилиты",
        "modules": [
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/surl.py",
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/httpsc.py",
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/latex.py",
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/vtt.py",
        ],
    },
    "downloaders": {
        "title": "⬇️ Загрузчики",
        "desc": "Загрузка медиа из соцсетей",
        "modules": [
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/instsave.py",
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/tikcock.py",
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/downloader.py",
            "https://github.com/amm1edev/ame_repo/raw/refs/heads/main/web2file.py",
        ],
    },
}

class PresetsModule(KitsuneModule):

    name        = "presets"
    description = "Наборы модулей"
    author      = "@Mikasu32"
    version     = "1.0"
    _builtin    = True

    strings_ru = {
        "presets_list":     "📦 <b>Доступные наборы модулей:</b>\n\n{list}\n\n"
                            "Установить: <code>.presets &lt;название&gt;</code>",
        "preset_info":      "📦 <b>{title}</b>\n"
                            "<i>{desc}</i>\n\n"
                            "<b>Модули ({count}):</b>\n{modules}\n\n"
                            "Установить: <code>.presets {name}</code>",
        "installing":       "⏳ Устанавливаю набор <b>{name}</b>...\n({cur}/{total})",
        "installed":        "✅ Набор <b>{name}</b> установлен!\n"
                            "✔ Успешно: {ok}\n"
                            "✘ Ошибки: {fail}",
        "preset_not_found": "❌ Набор <code>{name}</code> не найден.\n"
                            "Доступные: {avail}",
        "no_file":          "❌ Ответь на файл JSON с пресетом или прикрепи его.",
        "bad_file":         "❌ Неверный формат файла пресета.",
        "no_args":          "Использование: <code>.presets</code> или <code>.presets &lt;набор&gt;</code>",
        "folder_usage":     "Использование: <code>.addtofolder &lt;папка&gt; &lt;модуль&gt;</code>",
        "folder_added":     "✅ Модуль <code>{mod}</code> добавлен в папку <code>{folder}</code>.",
        "folder_already":   "ℹ️ Модуль уже в папке <code>{folder}</code>.",
        "folder_not_found": "❌ Папка <code>{folder}</code> не существует.",
        "mod_not_found":    "❌ Модуль <code>{mod}</code> не найден.",
        "removed_from":     "✅ Модуль <code>{mod}</code> удалён из папки <code>{folder}</code>.",
        "not_in_folder":    "❌ Модуль <code>{mod}</code> не в папке <code>{folder}</code>.",
        "rm_usage":         "Использование: <code>.removefromfolder &lt;папка&gt; &lt;модуль&gt;</code>",
        "fl_usage":         "Использование: <code>.folderload &lt;папка&gt;</code>",
        "fl_empty":         "❌ В папке <code>{folder}</code> нет модулей с известным URL.",
        "fl_done":          "📁 Файл пресета папки <b>{folder}</b> отправлен.\n"
                            "Установить: <code>.loadpreset</code> (ответь на файл)",
        "no_aliases":       "ℹ️ Нет сохранённых алиасов.",
        "aliases_saved":    "✅ Загружено алиасов: {count}",
        "aliases_file":     "📄 Файл алиасов отправлен.",
        "al_usage":         "❌ Нет алиасов для экспорта.",
        "la_bad":           "❌ Неверный формат файла алиасов.",
    }

    def _get_loader(self):
        return getattr(self.client, "_kitsune_loader", None)

    def _get_dispatcher(self):
        return getattr(self.client, "_kitsune_dispatcher", None)

    def _is_installed(self, url: str) -> bool:
        loader = self._get_loader()
        if not loader:
            return False
        installed_urls = self.db.get("kitsune.loader", "user_modules", [])
        return any(url.strip().lower() == u.strip().lower() for u in installed_urls)

    def _mod_name(self, url: str) -> str:
        return url.rstrip("/").split("/")[-1].rsplit(".", 1)[0]

    def _folders(self) -> dict:
        return self.db.get(_DB_OWNER, "folders", {})

    def _save_folders(self, folders: dict) -> None:
        import asyncio
        asyncio.ensure_future(self.db.set(_DB_OWNER, "folders", folders))

    @command("presets", required=OWNER)
    async def presets_cmd(self, event) -> None:
        arg = self.get_args(event).strip().lower()

        if not arg:
            lines = []
            for key, preset in PRESETS.items():
                lines.append(
                    f"▫️ <b>{preset['title']}</b> (<code>{key}</code>)\n"
                    f"   <i>{preset['desc']}</i>"
                )
            await event.message.edit(
                self.strings("presets_list").format(list="\n\n".join(lines)),
                parse_mode="html",
            )
            return

        if arg not in PRESETS:
            await event.message.edit(
                self.strings("preset_not_found").format(
                    name=arg,
                    avail=", ".join(f"<code>{k}</code>" for k in PRESETS),
                ),
                parse_mode="html",
            )
            return

        preset = PRESETS[arg]
        mod_lines = []
        for url in preset["modules"]:
            mark = "✔" if self._is_installed(url) else "▫️"
            mod_lines.append(f"{mark} <code>{self._mod_name(url)}</code>")

        await event.message.edit(
            self.strings("preset_info").format(
                title=preset["title"],
                desc=preset["desc"],
                count=len(preset["modules"]),
                modules="\n".join(mod_lines),
                name=arg,
            ),
            parse_mode="html",
        )

        await asyncio.sleep(2)
        loader = self._get_loader()
        if not loader:
            await event.message.edit("❌ Загрузчик модулей недоступен.", parse_mode="html")
            return

        modules = [u for u in preset["modules"] if not self._is_installed(u)]
        if not modules:
            await event.message.edit(
                f"✅ Все модули набора <b>{preset['title']}</b> уже установлены.",
                parse_mode="html",
            )
            return

        ok, fail = 0, 0
        for i, url in enumerate(modules, 1):
            await event.message.edit(
                self.strings("installing").format(
                    name=preset["title"], cur=i, total=len(modules)
                ),
                parse_mode="html",
            )
            try:
                await loader.load_from_url(url)
                ok += 1
            except Exception as exc:
                logger.warning("presets: failed to install %s — %s", url, exc)
                fail += 1
            await asyncio.sleep(0.5)

        await event.message.edit(
            self.strings("installed").format(name=preset["title"], ok=ok, fail=fail),
            parse_mode="html",
        )

    @command("loadpreset", required=OWNER)
    async def loadpreset_cmd(self, event) -> None:
        reply = await event.message.get_reply_message()
        msg = reply if (reply and reply.file) else (event.message if event.message.file else None)

        if not msg or not msg.file:
            await event.message.edit(self.strings("no_file"), parse_mode="html")
            return

        raw = await msg.download_media(bytes)
        try:
            data = json.loads(raw.decode())
            if not isinstance(data, dict) or "modules" not in data:
                raise ValueError
        except Exception:
            await event.message.edit(self.strings("bad_file"), parse_mode="html")
            return

        name = data.get("name", "Custom")
        urls = data.get("modules", [])
        loader = self._get_loader()
        if not loader:
            return

        ok, fail = 0, 0
        for i, url in enumerate(urls, 1):
            await event.message.edit(
                self.strings("installing").format(name=name, cur=i, total=len(urls)),
                parse_mode="html",
            )
            try:
                await loader.load_from_url(url)
                ok += 1
            except Exception:
                fail += 1
            await asyncio.sleep(0.5)

        await event.message.edit(
            self.strings("installed").format(name=name, ok=ok, fail=fail),
            parse_mode="html",
        )

    @command("addtofolder", required=OWNER)
    async def addtofolder_cmd(self, event) -> None:
        args = self.get_args(event).split()
        if len(args) < 2:
            await event.message.edit(self.strings("folder_usage"), parse_mode="html")
            return

        folder_name, mod_name = args[0], args[1]
        loader = self._get_loader()
        if not loader:
            return

        mod = loader.get_module(mod_name)
        if not mod:
            await event.message.edit(
                self.strings("mod_not_found").format(mod=mod_name), parse_mode="html"
            )
            return

        folders = self._folders()
        folder_list = folders.get(folder_name, [])

        if mod_name.lower() in [m.lower() for m in folder_list]:
            await event.message.edit(
                self.strings("folder_already").format(folder=folder_name), parse_mode="html"
            )
            return

        folder_list.append(mod_name)
        folders[folder_name] = folder_list
        await self.db.set(_DB_OWNER, "folders", folders)
        await event.message.edit(
            self.strings("folder_added").format(mod=mod_name, folder=folder_name),
            parse_mode="html",
        )

    @command("removefromfolder", required=OWNER)
    async def removefromfolder_cmd(self, event) -> None:
        args = self.get_args(event).split()
        if len(args) < 2:
            await event.message.edit(self.strings("rm_usage"), parse_mode="html")
            return

        folder_name, mod_name = args[0], args[1]
        folders = self._folders()

        if folder_name not in folders:
            await event.message.edit(
                self.strings("folder_not_found").format(folder=folder_name), parse_mode="html"
            )
            return

        folder_list = folders[folder_name]
        match = next((m for m in folder_list if m.lower() == mod_name.lower()), None)
        if not match:
            await event.message.edit(
                self.strings("not_in_folder").format(mod=mod_name, folder=folder_name),
                parse_mode="html",
            )
            return

        folder_list.remove(match)
        if not folder_list:
            del folders[folder_name]
        else:
            folders[folder_name] = folder_list

        await self.db.set(_DB_OWNER, "folders", folders)
        await event.message.edit(
            self.strings("removed_from").format(mod=mod_name, folder=folder_name),
            parse_mode="html",
        )

    @command("folderload", required=OWNER)
    async def folderload_cmd(self, event) -> None:
        args = self.get_args(event).split()
        if not args:
            await event.message.edit(self.strings("fl_usage"), parse_mode="html")
            return

        folder_name = args[0]
        folders = self._folders()

        if folder_name not in folders:
            await event.message.edit(
                self.strings("folder_not_found").format(folder=folder_name), parse_mode="html"
            )
            return

        loader = self._get_loader()
        urls = []
        for mod_name in folders[folder_name]:
            mod = loader.get_module(mod_name) if loader else None
            origin = getattr(mod, "_source_url", None) or getattr(mod, "_source_path", None)
            if origin and origin.startswith("http"):
                urls.append(origin)

        if not urls:
            await event.message.edit(
                self.strings("fl_empty").format(folder=folder_name), parse_mode="html"
            )
            return

        payload = {"name": folder_name, "description": folder_name, "modules": urls}
        buf = io.BytesIO(json.dumps(payload, ensure_ascii=False).encode())
        buf.name = f"{folder_name}.json"
        buf.seek(0)

        await _hydro_send_file(
            self.client,
            event.message.peer_id,
            buf,
            caption=self.strings("fl_done").format(folder=folder_name),
            reply_to=event.message.id,
        )
        await event.message.delete()

    @command("aliasload", required=OWNER)
    async def aliasload_cmd(self, event) -> None:
        dispatcher = self._get_dispatcher()
        if not dispatcher:
            return

        aliases = getattr(dispatcher, "_aliases", {})
        if not aliases:
            await event.message.edit(self.strings("al_usage"), parse_mode="html")
            return

        data = [{"alias": a, "command": c} for a, c in aliases.items()]
        buf = io.BytesIO(json.dumps(data, ensure_ascii=False).encode())
        buf.name = "aliases.json"
        buf.seek(0)

        await _hydro_send_file(
            self.client,
            event.message.peer_id,
            buf,
            caption=self.strings("aliases_file"),
            reply_to=event.message.id,
        )
        await event.message.delete()

    @command("loadaliases", required=OWNER)
    async def loadaliases_cmd(self, event) -> None:
        reply = await event.message.get_reply_message()
        msg = reply if (reply and reply.file) else (event.message if event.message.file else None)

        if not msg or not msg.file:
            await event.message.edit(self.strings("no_file"), parse_mode="html")
            return

        raw = await msg.download_media(bytes)
        try:
            data = json.loads(raw.decode())
            if not isinstance(data, list):
                raise ValueError
        except Exception:
            await event.message.edit(self.strings("la_bad"), parse_mode="html")
            return

        dispatcher = self._get_dispatcher()
        if not dispatcher:
            return

        loaded = 0
        for item in data:
            alias = item.get("alias", "")
            command_str = item.get("command", "")
            if alias and command_str:
                parts = command_str.split(maxsplit=1)
                cmd = parts[0]
                rest = parts[1] if len(parts) > 1 else None
                if cmd in getattr(dispatcher, "_commands", {}):
                    if not hasattr(dispatcher, "_aliases"):
                        dispatcher._aliases = {}
                    dispatcher._aliases[alias] = f"{cmd} {rest}" if rest else cmd
                    handler, required = dispatcher._commands[cmd]
                    dispatcher.register_command(alias, handler, required)
                    loaded += 1

        await event.message.edit(
            self.strings("aliases_saved").format(count=loaded), parse_mode="html"
        )
