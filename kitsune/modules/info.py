from __future__ import annotations
import copy
import logging
import re
import time
from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER


try:
    from telethon.errors import WebpageCurlFailedError, WebpageMediaEmptyError
except Exception:
    class WebpageCurlFailedError(Exception): pass
    class WebpageMediaEmptyError(Exception): pass

logger = logging.getLogger(__name__)

_DB_OWNER = "kitsune.info"
_DB_CONFIG = "kitsune.config.kitsuneinfo"


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_format(template: str, mapping: dict) -> str:
    if not template:
        return template
    result = template
    for key, value in mapping.items():
        result = result.replace("{" + key + "}", str(value))
    return result


def _extract_html_with_entities(raw_value: str, full_raw: str, entities: list) -> str:
    if not raw_value or not entities:
        return raw_value
    try:
        from telethon.extensions import html as tl_html
        from telethon.tl.types import MessageEntityCustomEmoji
    except Exception:
        return raw_value
    val_start = full_raw.find(raw_value)
    if val_start < 0:
        return raw_value
    val_end = val_start + len(raw_value)
    relevant = sorted(
        [e for e in entities if e.offset >= val_start and (e.offset + e.length) <= val_end],
        key=lambda x: x.offset,
    )
    if not relevant:
        return raw_value
    custom_emojis = [e for e in relevant if isinstance(e, MessageEntityCustomEmoji)]
    other_entities = [e for e in relevant if not isinstance(e, MessageEntityCustomEmoji)]
    if not custom_emojis:
        shifted = []
        for e in other_entities:
            ec = copy.copy(e)
            ec.offset = e.offset - val_start
            shifted.append(ec)
        return tl_html.unparse(raw_value, shifted)
    result_html = ""
    cursor = 0
    for ce in sorted(custom_emojis, key=lambda x: x.offset):
        ce_off = ce.offset - val_start
        if ce_off > cursor:
            before = raw_value[cursor:ce_off]
            before_ents = []
            for oe in other_entities:
                oe_off = oe.offset - val_start
                if oe_off >= cursor and (oe_off + oe.length) <= ce_off:
                    ec = copy.copy(oe)
                    ec.offset = oe_off - cursor
                    before_ents.append(ec)
            result_html += tl_html.unparse(before, before_ents)
        inner = raw_value[ce_off:ce_off + ce.length]
        result_html += f'<tg-emoji emoji-id="{ce.document_id}">{inner}</tg-emoji>'
        cursor = ce_off + ce.length
    if cursor < len(raw_value):
        tail = raw_value[cursor:]
        tail_ents = []
        for oe in other_entities:
            oe_off = oe.offset - val_start
            if oe_off >= cursor:
                ec = copy.copy(oe)
                ec.offset = oe_off - cursor
                tail_ents.append(ec)
        result_html += tl_html.unparse(tail, tail_ents)
    return result_html


class InfoModule(KitsuneModule):
    name        = "KitsuneInfo"
    description = "Информация о UserBot с кастомизацией"
    version     = "1.4.3"
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
                default="https://cdn.jsdelivr.net/gh/KitsuneX-dev/Kitsune@main/banner.gif",
                doc="Ссылка на баннер (видео/гифка/фото). Используй прямую ссылку. Для GitHub: используй команду .cdn чтобы конвертировать ссылку в CDN.",
            ),
            ConfigValue(
                "quote_media",
                default=True,
                doc=(
                    "Цитирование (web-preview) для баннера. "
                    "True — баннер отображается как превью-цитата над/под текстом, лимит текста 4096 (по умолчанию). "
                    "False — баннер отправляется как обычное медиа с подписью, лимит 1024 символа."
                ),
            ),
            ConfigValue(
                "invert_media",
                default=True,
                doc=(
                    "Положение баннера относительно текста (только при quote_media = True). "
                    "True — баннер сверху, текст снизу (по умолчанию). "
                    "False — текст сверху, баннер снизу."
                ),
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

    _CAPTION_LIMIT = 1024
    _MESSAGE_LIMIT = 4096

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
            tpl = self.config["custom_message"]
            return _safe_format(tpl, {
                "me": me_link,
                "version": version,
                "build": build,
                "prefix": f"«<code>{_esc(prefix)}</code>»",
                "platform": platform,
                "upd": upd,
                "uptime": uptime,
                "cpu_usage": cpu,
                "ram_usage": ram,
                "branch": branch,
            })
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
        from telethon.extensions import html as tl_html
        from telethon.tl.types import MessageEntityCustomEmoji
        tg_pattern = re.compile(
            r'<tg-emoji\s+emoji-id=["\'](\d+)["\']>(.*?)</tg-emoji>',
            re.DOTALL,
        )
        if not tg_pattern.search(html_text):
            return tl_html.parse(html_text)
        result_text     = ""
        result_entities = []
        cursor          = 0
        pos_in_html     = 0
        for m in tg_pattern.finditer(html_text):
            before_html = html_text[pos_in_html:m.start()]
            if before_html:
                plain_before, ents_before = tl_html.parse(before_html)
                for e in (ents_before or []):
                    e.offset += cursor
                result_text     += plain_before
                result_entities += list(ents_before or [])
                cursor          += len(plain_before)
            emoji_id    = m.group(1)
            inner_html  = m.group(2)
            inner_plain, inner_ents = tl_html.parse(inner_html)
            for e in (inner_ents or []):
                e.offset += cursor
            result_entities.append(
                MessageEntityCustomEmoji(
                    offset=cursor,
                    length=len(inner_plain),
                    document_id=int(emoji_id),
                )
            )
            result_entities += list(inner_ents or [])
            result_text     += inner_plain
            cursor          += len(inner_plain)
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

    @staticmethod
    def _is_photo_url(url: str) -> bool:
        if not url:
            return False
        try:
            from urllib.parse import urlparse
            path = urlparse(str(url)).path.lower()
        except Exception:
            path = str(url).lower()
        photo_exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif")
        video_or_gif_exts = (".gif", ".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v")
        if path.endswith(video_or_gif_exts):
            return False
        if path.endswith(photo_exts):
            return True
        return False

    @staticmethod
    def _is_http_url(url: str) -> bool:
        if not url:
            return False
        s = str(url).strip().lower()
        return s.startswith("http://") or s.startswith("https://")

    @staticmethod
    def _utf16_len(text: str) -> int:
        if not text:
            return 0
        return sum(2 if ord(c) > 0xFFFF else 1 for c in text)

    async def _send_webpage_quote(self, peer, banner_url, caption, entities, markup, invert_media: bool = True):
        from telethon.tl import functions
        from telethon.tl.types import InputMediaWebPage
        input_peer = await self.client.get_input_entity(peer)
        media = InputMediaWebPage(
            url=str(banner_url),
            force_large_media=True,
            optional=True,
        )
        request = functions.messages.SendMediaRequest(
            peer=input_peer,
            media=media,
            message=caption or "",
            entities=entities,
            reply_markup=markup,
            invert_media=invert_media,
            noforwards=True,
        )
        result = await self.client(request)
        return self.client._get_response_message(request, result, input_peer)

    async def _send_banner_protected(self, peer, banner, caption, entities, markup):
        return await self.client.send_file(
            peer,
            banner,
            caption=caption or "",
            formatting_entities=entities,
            buttons=markup,
            noforwards=True,
        )

    async def _send_long_text_protected(self, peer, text, entities, markup):
        return await self.client.send_message(
            peer,
            message=text or "",
            formatting_entities=entities,
            buttons=markup,
            no_webpage=True,
            noforwards=True,
        )

    async def _send_banner_no_caption(self, peer, banner):
        return await self.client.send_file(
            peer,
            banner,
            noforwards=True,
        )

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
                is_http = self._is_http_url(banner)
                use_quote = bool(self.config["quote_media"]) and is_http
                text_len = self._utf16_len(parsed_text)
                try:
                    if use_quote and text_len <= self._MESSAGE_LIMIT:
                        try:
                            await self._send_webpage_quote(
                                event.peer_id,
                                banner,
                                parsed_text,
                                entities,
                                markup,
                                invert_media=bool(self.config["invert_media"]),
                            )
                            await event.message.delete()
                            return
                        except (WebpageCurlFailedError, WebpageMediaEmptyError) as e:
                            logger.warning(
                                "info: webpage preview failed (%s), fallback to media with caption",
                                type(e).__name__,
                            )
                    if text_len <= self._CAPTION_LIMIT:
                        try:
                            await self._send_banner_protected(
                                event.peer_id,
                                banner,
                                parsed_text,
                                entities,
                                markup,
                            )
                            await event.message.delete()
                            return
                        except (WebpageCurlFailedError, WebpageMediaEmptyError) as e:
                            logger.warning(
                                "info: media with caption failed (%s), fallback to separate send",
                                type(e).__name__,
                            )
                    logger.info(
                        "info: text_len=%d exceeds caption limit, splitting into media + message",
                        text_len,
                    )
                    try:
                        await self._send_banner_no_caption(event.peer_id, banner)
                    except (WebpageCurlFailedError, WebpageMediaEmptyError) as e:
                        logger.warning(
                            "info: banner send failed (%s), skipping media",
                            type(e).__name__,
                        )
                    except Exception:
                        logger.exception("info: banner without caption failed")
                    safe_text = parsed_text
                    safe_entities = entities
                    if self._utf16_len(parsed_text) > self._MESSAGE_LIMIT:
                        safe_text = parsed_text[: self._MESSAGE_LIMIT]
                        safe_entities = [
                            e for e in entities
                            if e.offset + e.length <= self._MESSAGE_LIMIT
                        ]
                    await self._send_long_text_protected(
                        event.peer_id,
                        safe_text,
                        safe_entities,
                        markup,
                    )
                    await event.message.delete()
                    return
                except (WebpageCurlFailedError, WebpageMediaEmptyError) as e:
                    logger.warning(
                        "info: all banner attempts failed (%s), showing text only",
                        type(e).__name__,
                    )
                except Exception:
                    logger.exception("info: banner with caption failed")
            text_len = self._utf16_len(parsed_text)
            if text_len <= self._MESSAGE_LIMIT:
                await event.message.edit(parsed_text, formatting_entities=entities, buttons=markup)
            else:
                trimmed = parsed_text[: self._MESSAGE_LIMIT]
                trimmed_entities = [
                    e for e in entities
                    if e.offset + e.length <= self._MESSAGE_LIMIT
                ]
                await event.message.edit(
                    trimmed,
                    formatting_entities=trimmed_entities,
                    buttons=markup,
                )
            return
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

    @command("cdn", required=OWNER)
    async def cdn_cmd(self, event) -> None:
        args = self.get_args(event).strip()
        if not args:
            await event.message.edit(
                "❌ Укажи GitHub ссылку:\n"
                "<code>.cdn https://github.com/user/repo/blob/main/file.mp4</code>\n\n"
                "Результат:\n"
                "<code>https://cdn.jsdelivr.net/gh/user/repo@main/file.mp4</code>",
                parse_mode="html",
            )
            return
        m = re.match(
            r"https://github\.com/([^/]+)/([^/]+)/(?:blob|raw)/([^/]+)/(.*)",
            args,
        )
        if not m:
            await event.message.edit(
                "❌ Некорректная ссылка. Ожидается:\n"
                "<code>https://github.com/user/repo/blob/branch/path/to/file</code>",
                parse_mode="html",
            )
            return
        user, repo, branch, filepath = m.groups()
        cdn_url = f"https://cdn.jsdelivr.net/gh/{user}/{repo}@{branch}/{filepath}"
        await event.message.edit(
            f"✅ CDN ссылка:\n<code>{cdn_url}</code>",
            parse_mode="html",
        )

    @command("setinfo", required=OWNER)
    async def setinfo_cmd(self, event) -> None:
        args = self.get_args(event)
        if not args:
            await event.message.edit(self.strings("setinfo_no_args"), parse_mode="html")
            return
        msg = event.message
        full_raw = msg.raw_text or ""
        entities = list(msg.entities or [])
        value_html = _extract_html_with_entities(args, full_raw, entities)
        if isinstance(value_html, str):
            value_html = re.sub(r"<br\s*/?>", "\n", value_html)
        self.config["custom_message"] = value_html
        await self.db.set(_DB_CONFIG, "custom_message", value_html)
        try:
            await self.db.force_save()
        except Exception:
            pass
        await event.message.edit(self.strings("setinfo_success"), parse_mode="html")

    @command("resetinfo", required=OWNER)
    async def resetinfo_cmd(self, event) -> None:
        self.config["custom_message"] = None
        await self.db.delete(_DB_CONFIG, "custom_message")
        try:
            await self.db.force_save()
        except Exception:
            pass
        await event.reply("✅ Info-сообщение сброшено.", parse_mode="html")

    @command("fmt", required=OWNER)
    async def fmt_cmd(self, event) -> None:
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
            f"✅ Скопируй и вставь в fcfg kitsuneinfo custom_message:\n\n{result}",
        )

    async def emoji_cmd(self, event) -> None:
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
        def utf16_to_py(text: str, utf16_offset: int) -> int:
            py_idx = 0
            utf16_counted = 0
            while utf16_counted < utf16_offset and py_idx < len(text):
                cp = ord(text[py_idx])
                utf16_counted += 2 if cp > 0xFFFF else 1
                py_idx += 1
            return py_idx
        def utf16_slice(text: str, utf16_offset: int, utf16_length: int) -> tuple[int, int]:
            start = utf16_to_py(text, utf16_offset)
            end   = utf16_to_py(text, utf16_offset + utf16_length)
            return start, end
        replacements = sorted(
            [(e.offset - skip, e.length, e.document_id) for e in relevant],
            key=lambda x: x[0], reverse=True,
        )
        result = after_subcmd
        for utf16_off, utf16_len, doc_id in replacements:
            py_start, py_end = utf16_slice(result, utf16_off, utf16_len)
            emoji_char = result[py_start:py_end]
            tag = f'<tg-emoji emoji-id="{doc_id}">{emoji_char}</tg-emoji>'
            result = result[:py_start] + tag + result[py_end:]
        await event.message.edit(
            f"<code>{_esc(result)}</code>",
            parse_mode="html",
        )
