
from __future__ import annotations

import logging
import time
import typing
import uuid

logger = logging.getLogger(__name__)

_QUERY_TTL = 60 * 60 * 6

class QueryGallery:

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
        return self._query_galleries.pop(key.lower(), None) is not None

    async def _handle_query_gallery(self, inline_query: typing.Any) -> bool:
        q = inline_query.query.strip().lower()
        if not q:
            return False

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
        for i, (url, cap) in enumerate(zip(items[:50], captions)):
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
