from __future__ import annotations
import asyncio
import typing
from dataclasses import dataclass, field

@dataclass

class InlineButton:
    text: str
    callback: typing.Callable | None = None
    url: str | None = None
    data: str | None = None
    args: tuple = field(default_factory=tuple)
    disable_security: bool = False
@dataclass

class InlineCall:
    id: str
    chat_id: int
    message_id: int
    data: str
    _answer: typing.Callable
    _edit:   typing.Callable | None = None
    from_user_id: int | None = None
    inline_message_id: str = ""
    unit_id: str = ""
    _manager: typing.Any = None
    async def answer(self, text: str = "", show_alert: bool = False) -> None:
        await self._answer(text=text, show_alert=show_alert)
    async def _manager_edit(
        self,
        text: str | None = None,
        reply_markup: typing.Any = None,
        **kwargs: typing.Any,
    ) -> typing.Any:
        manager = self._manager
        edit_unit = getattr(manager, "_edit_unit", None) if manager is not None else None
        if edit_unit is None:
            raise RuntimeError("InlineCall.edit: no edit backend available")
        return await edit_unit(
            text=text,
            reply_markup=reply_markup,
            unit_id=self.unit_id or None,
            inline_message_id=self.inline_message_id or None,
            chat_id=self.chat_id or None,
            message_id=self.message_id or None,
        )
    async def edit(
        self,
        text: str | None = None,
        reply_markup: typing.Any = None,
        parse_mode: str = "HTML",
    ) -> typing.Any:
        if callable(self._edit):
            return await self._edit(
                text=text, reply_markup=reply_markup, parse_mode=parse_mode,
            )
        return await self._manager_edit(
            text=text, reply_markup=reply_markup, parse_mode=parse_mode,
        )
def markup_from_buttons(
    buttons: list[InlineButton | list[InlineButton]],
) -> list[list[dict]]:
    rows: list[list[InlineButton]] = []
    for item in buttons:
        if isinstance(item, list):
            rows.append(item)
        else:
            rows.append([item])
    result = []
    for row in rows:
        result_row = []
        for btn in row:
            d: dict[str, typing.Any] = {"text": btn.text}
            if btn.url:
                d["url"] = btn.url
            elif btn.callback:
                d["callback"] = btn.callback
                d["args"] = btn.args
                d["disable_security"] = btn.disable_security
            elif btn.data:
                d["data"] = btn.data
            result_row.append(d)
        result.append(result_row)
    return result
class InlineMessage:

    def __init__(
        self,
        manager: typing.Any,
        unit_id: str,
        inline_message_id: str = "",
        telethon_msg: typing.Any = None,
    ) -> None:
        self.inline_manager = manager
        self.unit_id = unit_id
        self.inline_message_id = inline_message_id
        self._telethon_msg = telethon_msg

    @property
    def unit(self) -> dict:
        return self.inline_manager._units.get(self.unit_id, {})

    @property
    def form(self) -> dict:
        unit = self.unit
        return {"id": self.unit_id, **unit} if unit else {}

    @property
    def chat_id(self) -> int | None:
        unit = self.unit
        return (
            unit.get("chat")
            or unit.get("chat_id")
            or getattr(self._telethon_msg, "chat_id", None)
        )

    @property
    def message_id(self) -> int | None:
        return self.unit.get("message_id") or getattr(self._telethon_msg, "id", None)

    @property
    def id(self) -> int | None:
        return self.message_id
    async def edit(
        self,
        text: str | None = None,
        reply_markup: typing.Any = None,
        **kwargs: typing.Any,
    ) -> typing.Any:
        return await self.inline_manager._edit_unit(
            text=text,
            reply_markup=reply_markup,
            unit_id=self.unit_id,
            inline_message_id=self.inline_message_id,
            **kwargs,
        )
    async def delete(self) -> bool:
        return await self.inline_manager._delete_unit_message(unit_id=self.unit_id)
    async def unload(self) -> bool:
        return await self.inline_manager._unload_unit(self.unit_id)
    def __getattr__(self, item: str) -> typing.Any:
        msg = self.__dict__.get("_telethon_msg")
        if msg is not None and hasattr(msg, item):
            return getattr(msg, item)
        raise AttributeError(item)
    def __bool__(self) -> bool:
        return True
    def __repr__(self) -> str:
        return (
            f"InlineMessage(unit_id={self.unit_id!r},"
            f" inline_message_id={self.inline_message_id!r})"
        )
