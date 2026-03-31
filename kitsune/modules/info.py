# meta developer: @Mikasu32
# Kitsune — Info module (based on Hikka HikkaInfo approach)

from __future__ import annotations

import logging
import time

from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER

logger = logging.getLogger(__name__)

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
                doc="Кастомная кнопка в сообщении info [текст, url]. Оставь пустым чтобы убрать.",
            ),
            ConfigValue(
                "banner_url",
                default="https://github.com/hikariatama/assets/raw/master/hikka_banner.mp4",
                doc="Ссылка на баннер (видео/гифка). Используй прямую ссылку (raw). Для GitHub: замени /blob/ на /raw/ в URL.",
            ),
        )

    strings_ru = {
        "owner":           "Владелец",
        "version":         "Версия",
        "branch":          "Ветка",
        "prefix":          "Префикс",
        "uptime":          "Аптайм",
        "platform":        "Хост",
        "up-to-date":      "",
        "update_required": "⬆️ Доступно обновление",
        "setinfo_no_args": "❌ Укажи текст: <code>.setinfo текст</code>",
        "setinfo_success": "✅ Info-сообщение обновлено.",
    }

    # ── helpers ───────────────────────────────────────────────────────────

    def _fmt_uptime(self) -> str:
        stored = self.db.get("kitsune.ping", "start_time", None)
        secs   = int(time.time() - (float(stored) if stored else time.time()))
        days, rem   = divmod(secs, 86400)
        hours, rem  = divmod(rem, 3600)
        minutes, _  = divmod(rem, 60)
        parts = []
        if days:   parts.append(f"{days}д")
        if hours:  parts.append(f"{hours}ч")
        parts.append(f"{minutes}м")
        return " ".join(parts)

    def _get_platform(self) -> str:
        import platform as pf
        s = pf.system()
        return {"Linux": "🐧 Linux", "Windows": "🪟 Windows", "Darwin": "🍎 macOS"}.get(s, f"❓ {s}")

    def _get_cpu_usage(self) -> str:
        try:
            import psutil
            return f"{psutil.cpu_percent(interval=None):.1f}%"
        except Exception:
            return "—"

    def _get_ram_usage(self) -> str:
        try:
            import psutil
            return f"{psutil.virtual_memory().used // 1024 // 1024} MB"
        except Exception:
            return "—"

    def _get_version(self) -> str:
        try:
            from ..version import __version_str__
            return __version_str__
        except Exception:
            return "?.?.?"

    def _get_git_info(self) -> tuple:
        """Открываем repo ОДИН раз -> (build, branch, upd)."""
        try:
            import git
            from ..version import branch as vbranch
            repo   = git.Repo(search_parent_directories=True)
            hexsha = repo.head.commit.hexsha
            build  = f'<a href="https://github.com/KitsuneX-dev/Kitsune/commit/{hexsha}">{hexsha[:7]}</a>'
            try:
                branch = repo.active_branch.name
            except Exception:
                branch = vbranch
            try:
                remote = repo.commit(f"origin/{vbranch}").hexsha
                upd    = self.strings("update_required") if hexsha != remote else self.strings("up-to-date")
            except Exception:
                upd = ""
            return build, branch, upd
        except Exception:
            return "", "unknown", ""

    def _render_info(self, me, git_info: tuple | None = None) -> str:
        if hasattr(me, "first_name"):
            name = " ".join(filter(None, [me.first_name, getattr(me, "last_name", None)]))
        else:
            name = str(me)
        me_link = f'<b><a href="tg://user?id={me.id}">{_esc(name)}</a></b>'

        build, branch, upd = git_info if git_info else self._get_git_info()
        version  = self._get_version()
        prefix   = self.db.get("kitsune.dispatcher", "prefix", ".")
        platform = self._get_platform()
        uptime   = self._fmt_uptime()
        cpu      = self._get_cpu_usage()
        ram      = self._get_ram_usage()

        if self.config["custom_message"]:
            return self.config["custom_message"].format(
                me=me_link, version=version, build=build,
                prefix=f"«<code>{_esc(prefix)}</code>»",
                platform=platform, upd=upd, uptime=uptime,
                cpu_usage=cpu, ram_usage=ram, branch=branch,
            )

        return (
            f"🦊 <b>Kitsune</b>\n\n"
            f"<b>😎 {self.strings('owner')}:</b> {me_link}\n\n"
            f"<b>💫 {self.strings('version')}:</b> <i>{version}</i> {build}\n"
            f"<b>🌳 {self.strings('branch')}:</b> <code>{branch}</code>\n"
            f"{upd}\n\n"
            f"<b>⌨️ {self.strings('prefix')}:</b> «<code>{_esc(prefix)}</code>»\n"
            f"<b>⌛️ {self.strings('uptime')}:</b> {uptime}\n\n"
            f"<b>⚡️ CPU | RAM:</b> {cpu} | {ram}\n"
            f"<b>💼 {self.strings('platform')}:</b> {platform}"
        )

    def _get_mark(self) -> dict | None:
        btn = self.config["custom_button"]
        if not btn:
            return None
        if isinstance(btn, (list, tuple)) and len(btn) == 2:
            return {"text": btn[0], "url": btn[1]}
        return None

    # ── commands ──────────────────────────────────────────────────────────

    @command("info", required=OWNER)
    async def info_cmd(self, event) -> None:
        """.info — показать информацию о UserBot."""
        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()

        # get_me() и git (блокирующий) — параллельно
        me, git_info = await _asyncio.gather(
            self.client.get_me(),
            loop.run_in_executor(None, self._get_git_info),
        )

        text   = self._render_info(me, git_info)
        mark   = self._get_mark()
        banner = self.config["banner_url"]
        inline = getattr(self.client, "_kitsune_inline", None)

        # Проверяем что ссылка прямая (raw), а не страница GitHub (/blob/)
        if banner and "/blob/" in banner and "github.com" in banner:
            banner = banner.replace("/blob/", "/raw/")
            logger.warning(
                "info_cmd: banner_url содержит /blob/ — автоматически исправлено на /raw/. "
                "Обнови ссылку в конфиге на: %s", banner
            )

        if inline and inline._bot:
            markup = [[mark]] if mark else []
            # Передаём как gif= — InlineManager сам определит тип по расширению (.mp4/.gif)
            kwargs = {"gif": banner} if banner else {}
            await inline.form(
                text=text,
                message=event.message,
                reply_markup=markup,
                **kwargs,
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
        await event.reply(self.strings("setinfo_success"), parse_mode="html")

    @command("resetinfo", required=OWNER)
    async def resetinfo_cmd(self, event) -> None:
        """.resetinfo — сбросить кастомный текст info."""
        self.config["custom_message"] = None
        await self.db.set(_DB_OWNER, "custom_message", None)
        await event.reply("✅ Info-сообщение сброшено.", parse_mode="html")
