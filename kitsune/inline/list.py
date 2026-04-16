from __future__ import annotations

import asyncio
import logging
import time
import typing

logger = logging.getLogger(__name__)

_UNIT_TTL = 60 * 60 * 12

class InlineList:

    async def list(
        self,
        message: typing.Any,
        items: typing.Union[typing.List[str], typing.Callable],
        *,
        title: str = "",
        page_size: int = 10,
        force_me: bool = True,
        always_allow: typing.Optional[typing.List[int]] = None,
        ttl: typing.Union[int, bool] = False,
        on_unload: typing.Optional[typing.Callable] = None,
        silent: bool = False,
    ) -> typing.Union[bool, typing.Any]:
        if always_allow is None:
            always_allow = []

        if callable(items) and asyncio.iscoroutinefunction(items):
            try:
                resolved = await items()
            except Exception:
                logger.exception("InlineList: ошибка получения элементов")
                return False
        elif callable(items):
            try:
                resolved = items()
            except Exception:
                logger.exception("InlineList: ошибка получения элементов")
                return False
        else:
            resolved = list(items)

        if not resolved:
            return False

        unit_id = self._rand(16)

        self._units[unit_id] = {
            "type":         "list",
            "items":        resolved,
            "title":        title,
            "page_size":    page_size,
            "current_page": 0,
            "force_me":     force_me,
            "always_allow": always_allow,
            "on_unload":    on_unload if callable(on_unload) else None,
            "uid":          unit_id,
            "ttl":          int(time.time()) + (ttl if ttl else _UNIT_TTL),
        }

        status_msg = None
        if not silent and hasattr(message, "out"):
            try:
                fn = message.edit if message.out else message.respond
                status_msg = await fn("📋 Загружаю список...")
            except Exception:
                pass

        text, markup = self._build_list_page(unit_id)

        self._units[unit_id]["_pending_text"]   = text
        self._units[unit_id]["_pending_markup"]  = markup

        try:
            m = await self._invoke_unit(unit_id, message)
        except Exception:
            logger.exception("InlineList: ошибка отправки unit")
            del self._units[unit_id]
            return False

        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass

        return m

    def _build_list_page(self, unit_id: str) -> tuple[str, list]:
        unit      = self._units[unit_id]
        items     = unit["items"]
        page      = unit["current_page"]
        size      = unit["page_size"]
        title     = unit["title"]

        total_pages = max(1, -(-len(items) // size))
        page        = max(0, min(page, total_pages - 1))
        unit["current_page"] = page

        start = page * size
        chunk = items[start : start + size]

        lines = "\n".join(f"{start + i + 1}. {item}" for i, item in enumerate(chunk))
        text  = (f"{title}\n\n" if title else "") + lines
        text += f"\n\n<i>Страница {page + 1} / {total_pages}</i>"

        nav = []
        handler = self._make_list_handler(unit_id)

        if page > 0:
            nav.append({"text": "◀️", "callback": handler, "args": (page - 1,)})

        nav.append({
            "text":     f"{page + 1}/{total_pages}",
            "callback": handler,
            "args":     ("noop",),
        })

        if page < total_pages - 1:
            nav.append({"text": "▶️", "callback": handler, "args": (page + 1,)})

        close_row = [{"text": "🗑 Закрыть", "callback": handler, "args": ("close",)}]

        return text, ([nav, close_row] if len(nav) > 1 else [close_row])

    def _make_list_handler(self, unit_id: str) -> typing.Callable:
        async def handler(call: typing.Any, page: typing.Union[int, str]) -> None:
            await self._list_page(call, page, unit_id=unit_id)
        return handler

    async def _list_page(
        self,
        call: typing.Any,
        page: typing.Union[int, str],
        unit_id: str,
    ) -> None:
        if unit_id not in self._units:
            await call.answer("⏰ Список устарел", show_alert=True)
            return

        unit = self._units[unit_id]

        caller_id = getattr(call, "from_user", None)
        caller_id = caller_id.id if caller_id else 0
        owner_id  = getattr(self, "_me", 0) or getattr(self._client, "tg_id", 0)

        if unit["force_me"] and caller_id != owner_id and caller_id not in unit["always_allow"]:
            await call.answer("🚫 Нет доступа", show_alert=True)
            return

        if page == "close":
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

        unit["current_page"] = int(page)
        text, markup = self._build_list_page(unit_id)

        try:
            await self.edit(call, text, markup)
            await call.answer()
        except Exception as exc:
            err = str(exc)
            if "message is not modified" in err.lower():
                await call.answer()
                return
            logger.exception("InlineList: ошибка обновления страницы")
            await call.answer("❌ Ошибка", show_alert=True)

    def _get_pending_list_content(self, unit_id: str) -> tuple[str, list]:
        unit  = self._units.get(unit_id, {})
        text  = unit.pop("_pending_text",  "")
        markup = unit.pop("_pending_markup", [])
        return text, markup
