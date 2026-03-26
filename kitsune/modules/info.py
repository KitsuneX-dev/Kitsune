# meta developer: @Mikasu32
# Kitsune — HikkaInfo-style info module

from __future__ import annotations

import time

from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER

_DB_OWNER = "kitsune.info"


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class InfoModule(KitsuneModule):
    """Информация об аккаунте и UserBot."""

    name        = "KitsuneInfo"
    description = "Информация о UserBot с кастомизацией"
    author      = "@Mikasu32"
    _builtin    = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.config = ModuleConfig(
            ConfigValue(
                "custom_message",
                default=None,
                doc=(
                    "Кастомный текст сообщения в info. "
                    "Может содержать ключевые слова {me}, {version}, {build}, "
                    "{prefix}, {platform}, {upd}, {uptime}, {cpu_usage}, "
                    "{ram_usage}, {branch}"
                ),
            ),
            ConfigValue(
                "custom_button",
                default=None,
                doc=(
                    "Кастомная кнопка в сообщении в info. "
                    "Оставь пустым, чтобы убрать кнопку"
                ),
            ),
            ConfigValue(
                "banner_url",
                default="https://github.com/hikariatama/assets/raw/master/hikka_banner.mp4",
                doc="Ссылка на баннер-картинку",
            ),
        )

    strings_ru = {
        "owner":      "Владелец",
        "version":    "Версия",
        "branch":     "Ветка",
        "prefix":     "Префикс",
        "uptime":     "Аптайм",
        "cpu_usage":  "CPU|RAM|",
        "ram_usage":  "RAM",
        "platform":   "Хост",
        "up-to-date": "",
        "update_required": "⬆️ Доступно обновление",
        "send_info":  "Отправить инфо",
        "description": "Информация о Kitsune UserBot",
        "setinfo_no_args": "❌ Укажи текст: <code>.setinfo текст</code>",
        "setinfo_success": "✅ Info-сообщение обновлено.",
    }

    def _fmt_uptime(self) -> str:
        stored = self.db.get("kitsune.ping", "start_time", None)
        secs = int(time.time() - (float(stored) if stored else time.time()))
        days, rem = divmod(secs, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        parts = []
        if days:    parts.append(f"{days}д")
        if hours:   parts.append(f"{hours}ч")
        parts.append(f"{minutes}м")
        return " ".join(parts)

    def _get_platform(self) -> str:
        import platform as pf
        system = pf.system()
        if system == "Linux":
            return "🐧 Linux"
        if system == "Windows":
            return "🪟 Windows"
        if system == "Darwin":
            return "🍎 macOS"
        return f"❓ {system}"

    def _get_cpu_usage(self) -> str:
        try:
            import psutil
            return f"{psutil.cpu_percent(interval=None):.1f}%"
        except Exception:
            return "—"

    def _get_ram_usage(self) -> str:
        try:
            import psutil
            mem = psutil.virtual_memory()
            return f"{mem.used // 1024 // 1024} MB"
        except Exception:
            return "—"

    def _get_version(self) -> str:
        try:
            from ..version import __version_str__
            return __version_str__
        except Exception:
            return "?.?.?"

    def _get_build(self) -> str:
        try:
            import git
            repo = git.Repo(search_parent_directories=True)
            return f'<a href="https://github.com/commit/{repo.head.commit.hexsha}">{repo.head.commit.hexsha[:7]}</a>'
        except Exception:
            return ""

    def _get_branch(self) -> str:
        try:
            from ..version import branch
            return branch
        except Exception:
            try:
                import git
                repo = git.Repo(search_parent_directories=True)
                return repo.active_branch.name
            except Exception:
                return "unknown"

    def _get_upd(self) -> str:
        # Только локальное сравнение, без git fetch (он блокирует event loop)
        try:
            import git
            from ..version import branch as vbranch
            repo = git.Repo(search_parent_directories=True)
            local = repo.head.commit.hexsha
            try:
                remote = repo.commit(f"origin/{vbranch}").hexsha
            except Exception:
                return ""
            return self.strings("update_required") if local != remote else self.strings("up-to-date")
        except Exception:
            return ""

    def _render_info(self, me) -> str:
        if hasattr(me, "first_name"):
            name = " ".join(filter(None, [me.first_name, getattr(me, "last_name", None)]))
        else:
            name = str(me)
        me_link = f'<b><a href="tg://user?id={me.id}">{_esc(name)}</a></b>'

        version  = self._get_version()
        build    = self._get_build()
        prefix   = self.db.get("kitsune.dispatcher", "prefix", ".")
        platform = self._get_platform()
        uptime   = self._fmt_uptime()
        cpu      = self._get_cpu_usage()
        ram      = self._get_ram_usage()
        branch   = self._get_branch()
        upd      = self._get_upd()

        custom_msg = self.config["custom_message"]

        if custom_msg:
            return custom_msg.format(
                me=me_link,
                version=version,
                build=build,
                prefix=f"«<code>{_esc(prefix)}</code>»",
                platform=platform,
                upd=upd,
                uptime=uptime,
                cpu_usage=cpu,
                ram_usage=ram,
                branch=branch,
            )

        # Дефолтное сообщение в стиле Hikka
        return (
            f"🦊 <b>Kitsune</b>\n\n"
            f"<b>😎 {self.strings('owner')}:</b> {me_link}\n\n"
            f"<b>💫 {self.strings('version')}:</b> <i>{version}</i> {build}\n"
            f"<b>🌳 {self.strings('branch')}:</b> <code>{branch}</code>\n"
            f"{upd}\n\n"
            f"<b>⌨️ {self.strings('prefix')}:</b> «<code>{_esc(prefix)}</code>»\n"
            f"<b>⌛️ {self.strings('uptime')}:</b> {uptime}\n\n"
            f"<b>⚡️ CPU|RAM|</b> {cpu} | {ram}\n"
            f"<b>💼 {self.strings('platform')}:</b> {platform}"
        )

    def _get_mark(self) -> dict | None:
        btn = self.config["custom_button"]
        if not btn:
            return None
        if isinstance(btn, (list, tuple)) and len(btn) == 2:
            return {"text": btn[0], "url": btn[1]}
        return None

    @command("info", required=OWNER)
    async def info_cmd(self, event) -> None:
        """.info — показать информацию о UserBot."""
        inline = getattr(self.client, "_kitsune_inline", None)
        me     = await self.client.get_me()
        text   = self._render_info(me)
        mark   = self._get_mark()
        banner = self.config["banner_url"]

        if inline and inline._bot:
            markup = [[mark]] if mark else []
            await inline.form(text, event.message, markup)
        elif banner:
            # Удаляем команду и отправляем видео/гифку с текстом как caption
            await event.delete()
            await self.client.send_file(
                event.chat_id,
                banner,
                caption=text,
                parse_mode="html",
            )
        else:
            await event.edit(text, parse_mode="html")

    @command("setinfo", required=OWNER)
    async def setinfo_cmd(self, event) -> None:
        """.setinfo <текст> — установить кастомный текст info."""
        args = self.get_args(event)
        if not args:
            await event.reply(self.strings("setinfo_no_args"), parse_mode="html")
            return
        self.config["custom_message"] = args
        await self.db.set(_DB_OWNER, "custom_message", args)
        m = await event.reply(self.strings("setinfo_success"), parse_mode="html")

    @command("resetinfo", required=OWNER)
    async def resetinfo_cmd(self, event) -> None:
        """.resetinfo — сбросить кастомный текст info."""
        self.config["custom_message"] = None
        await self.db.set(_DB_OWNER, "custom_message", None)
        m = await event.reply("✅ Info-сообщение сброшено.", parse_mode="html")
