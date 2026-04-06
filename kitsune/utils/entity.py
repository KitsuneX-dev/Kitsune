"""
kitsune/utils/entity.py — работа с Telegram-сущностями (пользователи, чаты).
"""

from __future__ import annotations

import typing


def get_display_name(entity: typing.Any) -> str:
    """
    Возвращает читаемое имя пользователя или чата.

    Для пользователей: "Имя Фамилия" или "@username".
    Для ботов/каналов: title или username.
    """
    if entity is None:
        return "Unknown"

    # Пользователь
    first = getattr(entity, "first_name", None) or ""
    last  = getattr(entity, "last_name", None) or ""
    name  = f"{first} {last}".strip()
    if name:
        return name

    # Чат / канал
    title = getattr(entity, "title", None)
    if title:
        return title

    # Fallback — username
    username = getattr(entity, "username", None)
    if username:
        return f"@{username}"

    # ID как последний вариант
    uid = getattr(entity, "id", None)
    return str(uid) if uid else "Unknown"


def get_entity_id(entity: typing.Any) -> int | None:
    """Безопасно получить числовой ID сущности."""
    return getattr(entity, "id", None)


def mention_html(entity: typing.Any, text: str | None = None) -> str:
    """
    Возвращает HTML-упоминание пользователя.
    mention_html(user) → '<a href="tg://user?id=123">Имя</a>'
    """
    uid  = get_entity_id(entity)
    name = text or get_display_name(entity)
    if uid:
        return f'<a href="tg://user?id={uid}">{name}</a>'
    return name


async def resolve_entity(client: typing.Any, peer: typing.Any) -> typing.Any:
    """
    Безопасно резолвит peer → entity.
    peer может быть: int, str (@username), TLObject.
    Возвращает entity или None при ошибке.
    """
    if peer is None:
        return None
    try:
        return await client.get_entity(peer)
    except Exception:
        return None


def is_bot(entity: typing.Any) -> bool:
    """Проверяет, является ли entity ботом."""
    return bool(getattr(entity, "bot", False))


def is_channel(entity: typing.Any) -> bool:
    """Проверяет, является ли entity каналом/супергруппой."""
    try:
        from telethon.tl.types import Channel
        return isinstance(entity, Channel)
    except ImportError:
        return hasattr(entity, "broadcast")


def is_group(entity: typing.Any) -> bool:
    """Проверяет, является ли entity группой."""
    try:
        from telethon.tl.types import Chat
        return isinstance(entity, Chat)
    except ImportError:
        return hasattr(entity, "participants_count") and not is_channel(entity)
