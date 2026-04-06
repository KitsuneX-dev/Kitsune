"""
kitsune/inline/query_gallery.py — галерея через inline query в любом чате.

В отличие от обычной gallery (которая отправляется в текущий чат),
query_gallery позволяет пользователю вставить галерею в любой чат
через @bot_name запрос.

Использование:
    # Регистрируем набор фотографий под ключом
    await inline.register_query_gallery(
        key="cats",
        items=["https://...jpg", "https://...jpg"],
        title="🐱 Котики",
    )

    # Теперь пользователь может написать @bot cats в любом чате
    # и вставить галерею туда
"""

from __future__ import annotations

import logging
import time
import typing
import uuid

logger = logging.getLogger(__name__)

_QUERY_TTL = 60 * 60 * 6  # 6 часов


class QueryGallery:
    """
    Mixin — регистрация inline-галерей доступных через @bot query.

    Требует в классе:
        self._query_galleries — dict (инициализируется ниже)
        self.generate_markup(buttons)
        self._rand(n)
    """

    # Словарь key → данные галереи
    _query_galleries: dict[str, dict] = {}

    def register_query_gallery(
        self,
        key: str,
        items: typing.List[str],
        *,
        title: str = "Kitsune Gallery",
        caption: str | typing.List[str] = "",
        gif: bool = False,
        ttl: int = _QUERY_TTL,
    ) -> None:
        """
        Зарегистрировать набор медиа под ключом.

        После регистрации пользователь может написать @bot <key>
        в любом чате и выбрать медиа для вставки.

        :param key:     Ключ поиска (что пишет пользователь после @bot).
        :param items:   Список URL медиафайлов.
        :param title:   Заголовок в списке inline-результатов.
        :param caption: Подпись(и) к медиа.
        :param gif:     True если медиа — GIF/видео.
        :param ttl:     Через сколько секунд галерея устаревает.
        """
        self._query_galleries[key.lower()] = {
            "key":     key.lower(),
            "items":   list(items),
            "title":   title,
            "caption": caption,
            "gif":     gif,
            "expires": time.time() + ttl,
        }
        logger.debug("QueryGallery: registered key=%r (%d items)", key, len(items))

    def unregister_query_gallery(self, key: str) -> bool:
        """Удалить зарегистрированную галерею."""
        return self._query_galleries.pop(key.lower(), None) is not None

    async def _handle_query_gallery(self, inline_query: typing.Any) -> bool:
        """
        Обрабатывает inline query если он совпадает с зарегистрированным ключом.
        Возвращает True если запрос был обработан.

        Вызывается из _on_inline_query в InlineManager ПЕРЕД стандартной обработкой.
        """
        q = inline_query.query.strip().lower()
        if not q:
            return False

        # Удаляем протухшие
        now = time.time()
        expired = [k for k, v in self._query_galleries.items() if v["expires"] < now]
        for k in expired:
            del self._query_galleries[k]

        gallery = None
        for key, data in self._query_galleries.items():
            if q.startswith(key):
                gallery = data
                break

        if gallery is None:
            return False

        items   = gallery["items"]
        gif     = gallery["gif"]
        title   = gallery["title"]
        captions = gallery["caption"]

        if isinstance(captions, str):
            captions = [captions] * len(items)
        elif len(captions) < len(items):
            captions = list(captions) + [""] * (len(items) - len(captions))

        try:
            from aiogram.types import (
                InlineQueryResultPhoto,
                InlineQueryResultGif,
                InlineQueryResultVideo,
            )
        except ImportError:
            return False

        results = []
        for i, (url, cap) in enumerate(zip(items[:50], captions)):  # Telegram лимит 50
            result_id = str(uuid.uuid4())
            common = {
                "id":          result_id,
                "title":       f"{title} [{i + 1}/{len(items)}]",
                "caption":     cap,
                "parse_mode":  "HTML",
            }
            try:
                if gif:
                    results.append(InlineQueryResultGif(
                        gif_url=url,
                        thumbnail_url=url,
                        **common,
                    ))
                else:
                    results.append(InlineQueryResultPhoto(
                        photo_url=url,
                        thumbnail_url=url,
                        **common,
                    ))
            except Exception:
                logger.debug("QueryGallery: ошибка создания результата для %s", url, exc_info=True)

        if not results:
            return False

        try:
            await inline_query.answer(results, cache_time=30)
            return True
        except Exception:
            logger.exception("QueryGallery: ошибка ответа на inline query")
            return False
