
import asyncio
import logging
import os
import typing
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class ListGalleryHelper:

    def __init__(self, urls: typing.List[str]):
        self.urls = urls
        self._index = -1

    def __call__(self) -> str:
        self._index += 1
        return self.urls[self._index % len(self.urls)]

    def by_index(self, index: int) -> str:
        return self.urls[index % len(self.urls)]

    def __len__(self) -> int:
        return len(self.urls)

class Gallery:

    async def gallery(
        self,
        message,
        next_handler: typing.Union[callable, typing.List[str]],
        caption: typing.Union[str, typing.List[str], callable] = "",
        *,
        force_me: bool = False,
        always_allow: typing.Optional[typing.List[int]] = None,
        ttl: typing.Union[int, bool] = False,
        on_unload: typing.Optional[callable] = None,
        preload: int = 3,
        gif: bool = False,
        silent: bool = False,
    ) -> typing.Union[bool, "InlineMessage"]:
        if always_allow is None:
            always_allow = []

        if isinstance(next_handler, list):
            if not all(isinstance(u, str) for u in next_handler):
                logger.error("gallery: next_handler список должен содержать только строки")
                return False
            next_handler = ListGalleryHelper(next_handler)

        if isinstance(caption, list):
            caption = ListGalleryHelper(caption)

        try:
            first_url = await self._resolve_url(next_handler)
        except Exception:
            logger.exception("gallery: ошибка получения первого URL")
            return False

        if not first_url:
            return False

        unit_id = self._rand(16)
        btn_call_data = self._rand(10)

        import time
        self._units[unit_id] = {
            "type": "gallery",
            "photos": [first_url] if isinstance(first_url, str) else list(first_url),
            "current_index": 0,
            "next_handler": next_handler,
            "caption": caption,
            "gif": gif,
            "force_me": force_me,
            "always_allow": always_allow,
            "on_unload": on_unload if callable(on_unload) else None,
            "preload": preload,
            "btn_call_data": btn_call_data,
            "uid": unit_id,
            "future": asyncio.Event(),
            **({"ttl": int(time.time()) + ttl} if ttl else {}),
        }

        self._custom_map[btn_call_data] = {
            "handler": self._make_page_handler(unit_id),
            **({"force_me": force_me} if force_me else {}),
            **({"always_allow": always_allow} if always_allow else {}),
        }

        status_message = None
        if not silent and hasattr(message, "out"):
            try:
                fn = message.edit if message.out else message.respond
                status_message = await fn("🌘 Открываю галерею...")
            except Exception:
                pass

        try:
            m = await self._invoke_unit(unit_id, message)
        except Exception:
            logger.exception("gallery: ошибка отправки inline unit")
            del self._units[unit_id]
            return False

        await self._units[unit_id]["future"].wait()
        del self._units[unit_id]["future"]

        if hasattr(m, "id"):
            self._units[unit_id]["message_id"] = m.id
        if hasattr(m, "chat_id"):
            self._units[unit_id]["chat"] = m.chat_id

        if status_message:
            try:
                await status_message.delete()
            except Exception:
                pass

        if preload and not isinstance(next_handler, ListGalleryHelper):
            asyncio.ensure_future(self._preload_photos(unit_id))

        return m

    def _make_page_handler(self, unit_id: str):
        async def handler(call, page):
            await self._gallery_page(call, page, unit_id=unit_id)
        return handler

    async def _resolve_url(
        self,
        handler: typing.Union[ListGalleryHelper, callable, str, list],
    ) -> typing.Union[str, typing.List[str], bool]:
        if isinstance(handler, str):
            return handler
        if isinstance(handler, list):
            return handler[0] if handler else False
        if isinstance(handler, ListGalleryHelper):
            return handler.urls
        if asyncio.iscoroutinefunction(handler):
            return await handler()
        if callable(handler):
            return handler()
        return False

    async def _preload_photos(self, unit_id: str):
        if unit_id not in self._units:
            return

        unit = self._units[unit_id]
        handler = unit["next_handler"]

        try:
            url = await self._resolve_url(handler)
            if url:
                if isinstance(url, list):
                    self._units[unit_id]["photos"].extend(url)
                else:
                    self._units[unit_id]["photos"].append(url)
        except Exception:
            logger.debug("gallery: ошибка предзагрузки", exc_info=True)

        unit = self._units.get(unit_id)
        if unit and len(unit["photos"]) - unit["current_index"] < unit["preload"]:
            asyncio.ensure_future(self._preload_photos(unit_id))

    def _get_caption(self, unit_id: str) -> str:
        caption = self._units[unit_id].get("caption", "")
        idx = self._units[unit_id]["current_index"]

        if isinstance(caption, ListGalleryHelper):
            return caption.by_index(idx)
        if callable(caption):
            try:
                result = caption()
                if asyncio.iscoroutine(result):
                    return ""
                return result
            except Exception:
                return ""
        return caption if isinstance(caption, str) else ""

    def _is_gif(self, unit_id: str, url: str) -> bool:
        if self._units[unit_id].get("gif", False):
            return True
        try:
            ext = os.path.splitext(urlparse(url).path)[1].lower()
            return ext in {".gif", ".mp4", ".webm"}
        except Exception:
            return False

    def _gallery_markup(self, unit_id: str):
        unit = self._units[unit_id]
        idx = unit["current_index"]
        total = len(unit["photos"])
        callback = self._make_page_handler(unit_id)

        nav_row = []

        if idx > 0:
            nav_row.append({
                "text": "⬅️",
                "callback": callback,
                "args": (idx - 1,),
            })

        nav_row.append({
            "text": f"{idx + 1} / {total}",
            "callback": callback,
            "args": ("noop",),
        })

        has_more = (
            idx < total - 1
            or not isinstance(unit["next_handler"], ListGalleryHelper)
        )
        if has_more:
            nav_row.append({
                "text": "➡️",
                "callback": callback,
                "args": (idx + 1,),
            })

        close_row = [{
            "text": "🗑 Закрыть",
            "callback": callback,
            "args": ("close",),
        }]

        return self.generate_markup([nav_row, close_row])

    async def _gallery_page(
        self,
        call,
        page: typing.Union[int, str],
        unit_id: typing.Optional[str] = None,
    ):
        if unit_id not in self._units:
            await call.answer("Галерея устарела", show_alert=True)
            return

        if page == "close":
            unit = self._units[unit_id]
            if unit.get("on_unload"):
                try:
                    await unit["on_unload"]()
                except Exception:
                    pass
            await self._delete_unit_message(call, unit_id=unit_id)
            del self._units[unit_id]
            return

        if page == "noop":
            await call.answer()
            return

        unit = self._units[unit_id]
        idx = int(page)

        if idx < 0:
            await call.answer("Это первое фото")
            return

        if idx >= len(unit["photos"]):
            if isinstance(unit["next_handler"], ListGalleryHelper):
                await call.answer("Это последнее фото")
                return
            await self._preload_photos(unit_id)
            if idx >= len(self._units[unit_id]["photos"]):
                await call.answer("Не удалось загрузить следующее фото")
                return

        self._units[unit_id]["current_index"] = idx
        photo_url = unit["photos"][idx]

        try:
            from aiogram.types import InputMediaPhoto, InputMediaAnimation

            media_cls = InputMediaAnimation if self._is_gif(unit_id, photo_url) else InputMediaPhoto
            await self.bot.edit_message_media(
                inline_message_id=call.inline_message_id,
                media=media_cls(
                    media=photo_url,
                    caption=self._get_caption(unit_id),
                    parse_mode="HTML",
                ),
                reply_markup=self._gallery_markup(unit_id),
            )
        except Exception as e:
            err = str(e)
            if "message is not modified" in err.lower():
                await call.answer()
                return
            if "retry" in err.lower():
                await call.answer("Подожди немного и попробуй снова", show_alert=True)
                return
            logger.exception("gallery: ошибка обновления медиа")
            await call.answer("Ошибка при переключении фото", show_alert=True)
            return

        await call.answer()

        if (
            unit.get("preload")
            and not isinstance(unit["next_handler"], ListGalleryHelper)
            and len(unit["photos"]) - idx < unit["preload"]
        ):
            asyncio.ensure_future(self._preload_photos(unit_id))

    async def _gallery_inline_handler(self, inline_query):
        for unit in self._units.copy().values():
            if (
                inline_query.from_user.id == self._me
                and inline_query.query == unit.get("uid")
                and unit.get("type") == "gallery"
            ):
                photo_url = unit["photos"][0]
                is_gif = self._is_gif(unit["uid"], photo_url)
                caption = self._get_caption(unit["uid"])

                try:
                    from aiogram.types import (
                        InlineQueryResultPhoto,
                        InlineQueryResultGif,
                    )
                    import uuid

                    common = {
                        "id": str(uuid.uuid4()),
                        "title": "Kitsune Gallery",
                        "caption": caption,
                        "parse_mode": "HTML",
                        "reply_markup": self._gallery_markup(unit["uid"]),
                        "thumb_url": "https://img.icons8.com/fluency/344/loading.png",
                    }

                    if is_gif:
                        result = InlineQueryResultGif(gif_url=photo_url, **common)
                    else:
                        result = InlineQueryResultPhoto(photo_url=photo_url, **common)

                    await inline_query.answer([result], cache_time=0)

                    if "future" in unit:
                        unit["future"].set()

                except Exception:
                    logger.exception("gallery: ошибка ответа на inline query")

                return

