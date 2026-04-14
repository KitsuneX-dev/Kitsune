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
        import os
        if os.environ.get("TERMUX_VERSION") or os.path.isdir("/data/data/com.termux"):
            return "📱 Termux — Android"
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
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        prefix   = dispatcher._prefix if dispatcher else self.db.get("kitsune.core", "prefix", ".")
        platform = self._get_platform()
        uptime   = self._fmt_uptime()
        cpu      = self._get_cpu_usage()
        ram      = self._get_ram_usage()

        if self.config["custom_message"]:
            import re
            # Убираем переносы строк внутри <tg-emoji ...>\n текст</tg-emoji>
            tpl = re.sub(r'(<tg-emoji[^>]+>)\s*\n\s*', r'\1', self.config["custom_message"])
            return tpl.format(
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

    @staticmethod
    def _parse_html_with_tg_emoji(html_text: str):
        """Парсит HTML с поддержкой <tg-emoji emoji-id="..."> тегов."""
        import re
        from telethon.extensions import html as tl_html
        from telethon.tl.types import MessageEntityCustomEmoji

        def _u16len(s: str) -> int:
            """Длина строки в UTF-16 code units (именно так считает Telethon)."""
            return len(s.encode("utf-16-le")) // 2

        # Telethon не понимает <br> — заменяем на перенос строки до парсинга
        html_text = re.sub(r'<br\s*/?>', '\n', html_text)

        tg_pattern = re.compile(
            r'<tg-emoji\s+emoji-id=(?:["\'])?(\d+)(?:["\'])?>(.*?)</tg-emoji>',
            re.DOTALL,
        )

        if not tg_pattern.search(html_text):
            return tl_html.parse(html_text)

        result_text     = ""
        result_entities = []
        cursor          = 0   # в UTF-16 code units
        pos_in_html     = 0

        for m in tg_pattern.finditer(html_text):
            before_html = html_text[pos_in_html:m.start()]
            if before_html:
                plain_before, ents_before = tl_html.parse(before_html)
                for e in (ents_before or []):
                    e.offset += cursor
                result_text     += plain_before
                result_entities += list(ents_before or [])
                cursor          += _u16len(plain_before)

            emoji_id    = m.group(1)
            inner_html  = m.group(2)
            inner_plain, inner_ents = tl_html.parse(inner_html)

            for e in (inner_ents or []):
                e.offset += cursor

            result_entities.append(
                MessageEntityCustomEmoji(
                    offset=cursor,
                    length=_u16len(inner_plain),
                    document_id=int(emoji_id),
                )
            )
            result_entities += list(inner_ents or [])
            result_text     += inner_plain
            cursor          += _u16len(inner_plain)
            pos_in_html      = m.end()

        tail_html = html_text[pos_in_html:]
        if tail_html:
            plain_tail, ents_tail = tl_html.parse(tail_html)
            for e in (ents_tail or []):
                e.offset += cursor
            result_text     += plain_tail
            result_entities += list(ents_tail or [])

        result_entities.sort(key=lambda e: e.offset)
        return result_text, result_entities

    @command("info", required=OWNER)
    async def info_cmd(self, event) -> None:
        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()

        me, git_info = await _asyncio.gather(
            self.client.get_me(),
            loop.run_in_executor(None, self._get_git_info),
        )

        text   = self._render_info(me, git_info)
        mark   = self._get_mark()
        banner = self.config["banner_url"]
        inline = getattr(self.client, "_kitsune_inline", None)

        if banner and "/blob/" in banner and "github.com" in banner:
            banner = banner.replace("/blob/", "/raw/")
            logger.warning(
                "info_cmd: banner_url содержит /blob/ — автоматически исправлено на /raw/. "
                "Обнови ссылку в конфиге на: %s", banner
            )

        # Если есть custom_message — используем Telethon + премиум-эмодзи
        if self.config["custom_message"]:
            from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonUrl, KeyboardButtonRow

            parsed_text, entities = self._parse_html_with_tg_emoji(text)

            markup = None
            if mark:
                markup = ReplyInlineMarkup(rows=[
                    KeyboardButtonRow(buttons=[
                        KeyboardButtonUrl(text=mark["text"], url=mark["url"])
                    ])
                ])

            if banner:
                try:
                    # Отправляем баннер СРАЗУ с подписью и эмодзи
                    await self.client.send_file(
                        event.peer_id,
                        banner,
                        caption=parsed_text,
                        formatting_entities=entities,
                        buttons=markup,
                    )
                    await event.message.delete()
                    return
                except Exception:
                    logger.exception("info: не удалось отправить баннер с подписью")

            # Если баннера нет или он упал — просто редактируем сообщение
            await event.message.edit(parsed_text, formatting_entities=entities, buttons=markup)
            return

        # Старый режим (без custom_message)
        if inline and inline._bot:
            markup = [[mark]] if mark else []
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
        args = self.get_args(event)
        if not args:
            await event.reply(self.strings("setinfo_no_args"), parse_mode="html")
            return
        self.config["custom_message"] = args
        await self.db.set(_DB_OWNER, "custom_message", args)
        await event.reply(self.strings("setinfo_success"), parse_mode="html")

    @command("resetinfo", required=OWNER)
    async def resetinfo_cmd(self, event) -> None:
        self.config["custom_message"] = None
        await self.db.set(_DB_OWNER, "custom_message", None)
        await event.reply("✅ Info-сообщение сброшено.", parse_mode="html")

    @command("fmt", required=OWNER)
    async def fmt_cmd(self, event) -> None:
        """Форматирует текст в HTML-теги для custom_message"""
        args = self.get_args(event).strip()

        if not args:
            await event.message.edit(
                "❌ Использование:\n"
                "<code>.fmt b текст</code> — <b>жирный</b>\n"
                "<code>.fmt i текст</code> — <i>курсив</i>\n"
                "<code>.fmt code текст</code> — <code>моноширинный</code>\n"
                "<code>.fmt quote текст</code> — цитата\n"
                "<code>.fmt qe текст</code> — сворачиваемая цитата",
                parse_mode="html",
            )
            return

        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            await event.message.edit("❌ Укажи тип и текст: <code>.fmt b мой текст</code>", parse_mode="html")
            return

        tag, content = parts[0].lower(), parts[1]

        tag_map = {
            "b":     ("<b>", "</b>"),
            "bold":  ("<b>", "</b>"),
            "i":     ("<i>", "</i>"),
            "italic":("<i>", "</i>"),
            "u":     ("<u>", "</u>"),
            "s":     ("<s>", "</s>"),
            "code":  ("<code>", "</code>"),
            "quote": ("<blockquote>", "</blockquote>"),
            "q":     ("<blockquote>", "</blockquote>"),
            "qe":    ("<blockquote expandable>", "</blockquote>"),
        }

        if tag not in tag_map:
            await event.message.edit(
                f"❌ Неизвестный тип <code>{_esc(tag)}</code>. Доступные: b, i, u, s, code, quote, qe",
                parse_mode="html",
            )
            return

        open_tag, close_tag = tag_map[tag]
        result = f"{open_tag}{content}{close_tag}"

        await event.message.edit(
            f"✅ Скопируй и вставь в <code>fcfg kitsuneinfo custom_message</code>:\n\n"
            f"<code>{_esc(result)}</code>",
            parse_mode="html",
        )


    async def emoji_cmd(self, event) -> None:
        """Субкоманда .e r.text — вытаскивает ID премиум-эмодзи"""
        from telethon.tl.types import MessageEntityCustomEmoji

        args = self.get_args(event).strip()

        if not args.startswith("r.text"):
            await event.message.edit(
                "\u274c Использование: <code>.e r.text &lt;текст с прем-эмодзи&gt;</code>",
                parse_mode="html",
            )
            return

        after_subcmd = args[len("r.text"):].lstrip()
        if not after_subcmd:
            await event.message.edit(
                "\u274c Напиши текст с прем-эмодзи после команды:\n"
                "<code>.e r.text ✨ Мой статус ✨</code>",
                parse_mode="html",
            )
            return

        raw_full = event.message.raw_text or ""
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        prefix = dispatcher._prefix if dispatcher else "."
        skip = len(raw_full) - len(after_subcmd)

        entities = list(event.message.entities or [])
        relevant = [
            e for e in entities
            if isinstance(e, MessageEntityCustomEmoji) and e.offset >= skip
        ]

        if not relevant:
            await event.message.edit(
                "\u2139\ufe0f Премиум-эмодзи не найдены в тексте.",
                parse_mode="html",
            )
            return

        replacements = sorted(
            [(e.offset - skip, e.length, e.document_id) for e in relevant],
            key=lambda x: x[0], reverse=True,
        )

        result = after_subcmd
        for offset, length, doc_id in replacements:
            emoji_char = result[offset:offset + length]
            tag = f'<tg-emoji emoji-id={doc_id}>{emoji_char}</tg-emoji>'
            result = result[:offset] + tag + result[offset + length:]

        # Заменяем переносы строк на <br> — для корректной вставки в custom_message
        result_for_copy = result.replace('\n', '<br>\n')

        await event.message.edit(
            f"<code>{_esc(result_for_copy)}</code>",
            parse_mode="html",
        )