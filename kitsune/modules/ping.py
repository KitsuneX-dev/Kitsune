from __future__ import annotations
import logging
import re
import time
from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER


try:
    from telethon.errors import WebpageCurlFailedError, WebpageMediaEmptyError
except Exception:  # pragma: no cover
    class WebpageCurlFailedError(Exception): pass  # type: ignore
    class WebpageMediaEmptyError(Exception): pass  # type: ignore

logger = logging.getLogger(__name__)

_DEFAULT_PONG = (
    "━━━━━━━━━━━━━━\n"
    " \n"
    "🛰 Задержка: <code>{ms:.0f} мс</code>\n"
    "⏱ Аптайм: <code>{uptime}</code>\n"
    "💠 Версия: <code>{version}</code>\n"
    "✅ Статус: <code>Stable Release</code>\n"
    " \n"
    "━━━━━━━━━━━━━━"
)

_EMOJI_TAG  = re.compile(r'<emoji\s+id=["\']?(\d+)["\']?>(.*?)</emoji>', re.DOTALL)

_EMOJI_BRACE = re.compile(r'\{emoji:(\d+):([^}]*)\}')

def _resolve_custom_emoji(text: str) -> str:
    def _to_tg(eid: str, fallback: str) -> str:
        return '<tg-emoji emoji-id="' + eid + '">' + fallback + '</tg-emoji>'
    text = _EMOJI_TAG.sub(lambda m: _to_tg(m.group(1), m.group(2)), text)
    text = _EMOJI_BRACE.sub(lambda m: _to_tg(m.group(1), m.group(2)), text)
    return text
def _fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:    parts.append(f"{days}д")
    if hours:   parts.append(f"{hours}ч")
    parts.append(f"{minutes}м")
    return " ".join(parts)
class PingModule(KitsuneModule):
    name        = "ping"
    description = "Пинг и базовая информация"
    author      = "Yushi"
    version     = "1.4.0"
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.config = ModuleConfig(
            ConfigValue(
                "custom_message",
                default=None,
                doc=(
                    "Кастомный текст сообщения ping. "
                    "Ключевые слова: {ms}, {uptime}, {version}, {prefix}, {platform}, {cpu}, {ram}. "
                    "Поддерживает premium-эмодзи: <emoji id=XXXXXXXXX>⭐</emoji> "
                    "или {emoji:XXXXXXXXX:⭐}. "
                    "Оставь пустым для стандартного вида."
                ),
            ),
            ConfigValue(
                "media_url",
                default=None,
                doc=(
                    "Ссылка на медиа (фото/видео/гифка), которое будет прикреплено к сообщению ping. "
                    "Используй прямую ссылку. Для GitHub: команда .cdn конвертирует в CDN. "
                    "Оставь пустым чтобы отправлять только текст."
                ),
            ),
        )
    strings_ru = {
        "me": (
            "👤 <b>Профиль</b>\n\n"
            "  ID: <code>{id}</code>\n"
            "  Имя: {name}\n"
            "  Username: {username}\n"
            "  Phone: <code>{phone}</code>\n"
            "  Premium: {premium}"
        ),
        "id_msg":   "🆔 ID сообщения: <code>{mid}</code>\n👤 ID чата: <code>{cid}</code>",
        "id_reply": (
            "🆔 ID сообщения: <code>{mid}</code>\n"
            "↩️ ID ответа: <code>{rid}</code>\n"
            "👤 ID отправителя: <code>{sid}</code>"
        ),
    }
    _start_time: float = time.time()
    async def on_load(self) -> None:
        PingModule._start_time = time.time()
        await self.db.set("kitsune.ping", "start_time", PingModule._start_time)
    def _get_platform(self) -> str:
        import platform as pf, os
        if os.environ.get("TERMUX_VERSION") or os.path.isdir("/data/data/com.termux"):
            return "📱 Termux"
        s = pf.system()
        return {"Linux": "🐧 Linux", "Windows": "🪟 Windows", "Darwin": "🍎 macOS"}.get(s, s)
    def _get_cpu_ram(self) -> tuple[str, str]:
        try:
            import psutil
            cpu = f"{psutil.cpu_percent(interval=0.1):.1f}%"
            mem = psutil.virtual_memory()
            ram = f"{mem.used//1024//1024}/{mem.total//1024//1024} MB"
            return cpu, ram
        except Exception:
            return "—", "—"
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
    @command("ping", required=OWNER)
    async def ping_cmd(self, event) -> None:
        from ..version import __version_str__
        start = time.perf_counter()
        msg = await event.reply("⏳", parse_mode="html")
        ms = round((time.perf_counter() - start) * 1000)
        stored_start = self.db.get("kitsune.ping", "start_time", None)
        uptime_sec   = time.time() - (float(stored_start) if stored_start else self._start_time)
        uptime_str   = _fmt_uptime(uptime_sec)
        custom = self.config["custom_message"] if self.config else None
        if custom:
            dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
            prefix = dispatcher._prefix if dispatcher else "."
            cpu, ram = self._get_cpu_ram()
            try:
                text = custom.format(
                    ms=ms,
                    uptime=uptime_str,
                    version=__version_str__,
                    prefix=prefix,
                    platform=self._get_platform(),
                    cpu=cpu,
                    ram=ram,
                )
            except KeyError:
                text = custom
        else:
            text = _DEFAULT_PONG.format(ms=ms, uptime=uptime_str, version=__version_str__)
        text = _resolve_custom_emoji(text)
        media_url = self.config["media_url"] if self.config else None
        if media_url:
            try:
                parsed_text, entities = self._parse_html_with_tg_emoji(text)


                text_len = sum(2 if ord(c) > 0xFFFF else 1 for c in parsed_text)
                has_blockquote = bool(re.search(r"<\s*blockquote\b", text, re.IGNORECASE))
                _CAPTION_LIMIT = 1024
                fits_caption = (text_len <= _CAPTION_LIMIT) and not has_blockquote
                try:
                    if fits_caption:
                        await self.client.send_file(
                            event.peer_id,
                            media_url,
                            caption=parsed_text,
                            formatting_entities=entities,
                        )
                    else:

                        logger.info(
                            "ping: text_len=%d has_blockquote=%s — раздельная отправка",
                            text_len, has_blockquote,
                        )
                        await self.client.send_file(event.peer_id, media_url)
                        await self.client.send_message(
                            event.peer_id,
                            parsed_text,
                            formatting_entities=entities,
                        )
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    return
                except (WebpageCurlFailedError, WebpageMediaEmptyError) as e:


                    logger.warning(
                        "ping: Telegram не смог загрузить медиа по ссылке (%s), отправляю только текст",
                        type(e).__name__,
                    )
            except Exception:
                logger.exception("ping: не удалось отправить медиа, отправляю текст")
        await msg.edit(text, parse_mode="html")
    @command("setpingmedia", required=OWNER)
    async def setpingmedia_cmd(self, event) -> None:
        args = self.get_args(event).strip()
        if not args:
            await event.reply(
                "❌ Укажи ссылку на медиа:\n"
                "<code>.setpingmedia https://...</code>\n\n"
                "Поддерживается фото, видео и гифки. "
                "Для GitHub-ссылок используй <code>.cdn</code>.",
                parse_mode="html",
            )
            return
        self.config["media_url"] = args
        await self.db.set("kitsune.config.ping", "media_url", args)
        await event.reply("✅ Медиа для .ping установлено.", parse_mode="html")
    @command("resetpingmedia", required=OWNER)
    async def resetpingmedia_cmd(self, event) -> None:
        self.config["media_url"] = None
        await self.db.delete("kitsune.config.ping", "media_url")
        await event.reply("✅ Медиа для .ping удалено.", parse_mode="html")
    @command("me", required=OWNER)
    async def me_cmd(self, event) -> None:
        me = await self.client.get_me()
        name = me.first_name
        if me.last_name:
            name += f" {me.last_name}"
        await event.reply(
            self.strings("me").format(
                id=me.id, name=name,
                username=f"@{me.username}" if me.username else "—",
                phone=me.phone or "—",
                premium="✅" if getattr(me, "premium", False) else "❌",
            ),
            parse_mode="html",
        )
    @command("id", required=OWNER)
    async def id_cmd(self, event) -> None:
        reply = await event.message.get_reply_message()
        if reply:
            await event.reply(
                self.strings("id_reply").format(
                    mid=event.message.id,
                    rid=reply.id,
                    sid=reply.sender_id or "—",
                ),
                parse_mode="html",
            )
        else:
            await event.reply(
                self.strings("id_msg").format(mid=event.message.id, cid=event.chat_id),
                parse_mode="html",
            )
