from __future__ import annotations
import asyncio
import logging
import random
import re
import time
from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER
from ..utils.platform import (
    get_cpu_model_cores,
    get_hostname,
    get_kernel_release,
    get_named_platform_label,
    get_os_pretty_name,
    get_run_environment,
    get_username,
)
from ..utils.tg_html import parse_html_with_tg_emoji


try:
    from telethon.errors import WebpageCurlFailedError, WebpageMediaEmptyError
except Exception:
    class WebpageCurlFailedError(Exception): pass
    class WebpageMediaEmptyError(Exception): pass

try:
    from telethon.tl.functions import PingRequest
except Exception:
    PingRequest = None

try:
    from telethon.tl.functions.updates import GetStateRequest
except Exception:
    GetStateRequest = None

logger = logging.getLogger(__name__)

_DEFAULT_PONG = (
    "⛩ <b>𝙆𝙞𝙩𝙨𝙪𝙣𝙚 𝙋𝙞𝙣𝙜</b>\n"
    "<blockquote> 🏮 <b>Отклик:</b> <code>{ms:.0f} мс</code>\n"
    " 🌀 <b>Аптайм:</b> <code>{uptime}</code></blockquote>"
)

_EMOJI_TAG   = re.compile(r'<emoji\s+id=["\']?(\d+)["\']?>(.*?)</emoji>', re.DOTALL)
_EMOJI_BRACE = re.compile(r'\{emoji:(\d+):([^}]*)\}')


def _resolve_custom_emoji(text: str) -> str:
    def _to_tg(eid: str, fallback: str) -> str:
        return '<tg-emoji emoji-id="' + eid + '">' + fallback + '</tg-emoji>'
    text = _EMOJI_TAG.sub(lambda m: _to_tg(m.group(1), m.group(2)), text)
    text = _EMOJI_BRACE.sub(lambda m: _to_tg(m.group(1), m.group(2)), text)
    return text


def _fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, rem  = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    parts.append(f"{minutes}м")
    return " ".join(parts)


async def _measure_latency(client) -> float:
    samples = []
    if PingRequest is not None:
        for _ in range(3):
            try:
                ping_id = random.randint(1, 2**62)
                t0 = time.perf_counter()
                await asyncio.wait_for(client(PingRequest(ping_id=ping_id)), timeout=5.0)
                samples.append((time.perf_counter() - t0) * 1000.0)
            except Exception:
                break
    if not samples and GetStateRequest is not None:
        for _ in range(3):
            try:
                t0 = time.perf_counter()
                await asyncio.wait_for(client(GetStateRequest()), timeout=5.0)
                samples.append((time.perf_counter() - t0) * 1000.0)
            except Exception:
                break
    if not samples:
        return float("nan")
    samples.sort()
    return samples[len(samples) // 2]


class PingModule(KitsuneModule):
    name        = "ping"
    description = "Пинг и базовая информация"
    author      = "Yushi"
    version     = "1.5.0"

    _CAPTION_LIMIT = 1024
    _MESSAGE_LIMIT = 4096

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._start_time = time.time()
        self.config = ModuleConfig(
            ConfigValue(
                "custom_message",
                default=None,
                doc=(
                    "Кастомный текст сообщения ping. "
                    "Ключевые слова: {ms}, {uptime}, {version}, {prefix}, {platform}, "
                    "{cpu_usage}, {ram}, {os}, {kernel}, {hostname}, {user}, {cpu}, {env}. "
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

    _start_time: float

    async def on_load(self) -> None:
        self._start_time = time.time()
        await self.db.set("kitsune.ping", "start_time", self._start_time)

    def _get_platform(self) -> str:
        return get_named_platform_label(termux_suffix=False)

    def _get_os(self) -> str:
        return get_os_pretty_name()

    def _get_kernel(self) -> str:
        return get_kernel_release()

    def _get_hostname(self) -> str:
        return get_hostname()

    def _get_user(self) -> str:
        return get_username()

    def _get_cpu(self) -> str:
        return get_cpu_model_cores()

    def _get_env(self) -> str:
        return get_run_environment()

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
    def _utf16_len(text: str) -> int:
        if not text:
            return 0
        return sum(2 if ord(c) > 0xFFFF else 1 for c in text)

    @staticmethod
    def _parse_html_with_tg_emoji(html_text: str):
        return parse_html_with_tg_emoji(html_text)

    async def _send_media_with_caption(self, peer, media_url, caption, entities):
        return await self.client.send_file(
            peer,
            media_url,
            caption=caption or "",
            formatting_entities=entities,
        )

    async def _send_media_no_caption(self, peer, media_url):
        return await self.client.send_file(
            peer,
            media_url,
        )

    async def _send_message_only(self, peer, text, entities):
        return await self.client.send_message(
            peer,
            message=text or "",
            formatting_entities=entities,
            no_webpage=True,
        )

    @command("ping", required=OWNER)
    async def ping_cmd(self, event) -> None:
        from ..version import __version_str__
        msg = await event.reply("⏳", parse_mode="html")
        latency_ms = await _measure_latency(self.client)
        if latency_ms != latency_ms:
            latency_ms = 0.0
        latency_int = int(round(latency_ms))
        stored_start = self.db.get("kitsune.ping", "start_time", None)
        uptime_sec   = time.time() - (float(stored_start) if stored_start else self._start_time)
        uptime_str   = _fmt_uptime(uptime_sec)
        custom = self.config["custom_message"] if self.config else None
        if custom:
            dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
            prefix = dispatcher._prefix if dispatcher else "."
            cpu_usage, ram = self._get_cpu_ram()
            try:
                text = custom.format(
                    ms=latency_int,
                    uptime=uptime_str,
                    version=__version_str__,
                    prefix=prefix,
                    platform=self._get_platform(),
                    cpu=self._get_cpu(),
                    cpu_usage=cpu_usage,
                    ram=ram,
                    os=self._get_os(),
                    kernel=self._get_kernel(),
                    hostname=self._get_hostname(),
                    user=self._get_user(),
                    env=self._get_env(),
                )
            except KeyError:
                text = custom
        else:
            text = _DEFAULT_PONG.format(
                ms=latency_ms,
                uptime=uptime_str,
                version=__version_str__,
            )
        text = _resolve_custom_emoji(text)
        media_url = self.config["media_url"] if self.config else None
        if media_url:
            try:
                parsed_text, entities = self._parse_html_with_tg_emoji(text)
                text_len = self._utf16_len(parsed_text)
                try:
                    if text_len <= self._CAPTION_LIMIT:
                        await self._send_media_with_caption(
                            event.peer_id,
                            media_url,
                            parsed_text,
                            entities,
                        )
                    else:
                        logger.info(
                            "ping: text_len=%d exceeds caption limit, splitting",
                            text_len,
                        )
                        try:
                            await self._send_media_no_caption(event.peer_id, media_url)
                        except (WebpageCurlFailedError, WebpageMediaEmptyError) as e:
                            logger.warning(
                                "ping: media send failed (%s), continuing with text only",
                                type(e).__name__,
                            )
                        safe_text = parsed_text
                        safe_entities = entities
                        if text_len > self._MESSAGE_LIMIT:
                            safe_text = parsed_text[: self._MESSAGE_LIMIT]
                            safe_entities = [
                                e for e in entities
                                if e.offset + e.length <= self._MESSAGE_LIMIT
                            ]
                        await self._send_message_only(
                            event.peer_id,
                            safe_text,
                            safe_entities,
                        )
                    try:
                        await msg.delete()
                    except Exception:
                        logger.debug("ping: не удалось удалить временное сообщение", exc_info=True)
                    return
                except (WebpageCurlFailedError, WebpageMediaEmptyError) as e:
                    logger.warning(
                        "ping: Telegram media load failed (%s), sending text only",
                        type(e).__name__,
                    )
            except Exception:
                logger.exception("ping: media send failed, fallback to text")
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
