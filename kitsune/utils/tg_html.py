
from __future__ import annotations

import re

_TG_EMOJI_RE = re.compile(
    r'<tg-emoji\s+emoji-id=["\'](\d+)["\']>(.*?)</tg-emoji>',
    re.DOTALL,
)


def parse_html_with_tg_emoji(html_text: str):
    from telethon.extensions import html as tl_html
    from telethon.tl.types import MessageEntityCustomEmoji

    if not _TG_EMOJI_RE.search(html_text):
        return tl_html.parse(html_text)

    result_text = ""
    result_entities = []
    cursor = 0
    pos_in_html = 0

    for m in _TG_EMOJI_RE.finditer(html_text):
        before_html = html_text[pos_in_html:m.start()]
        if before_html:
            plain_before, ents_before = tl_html.parse(before_html)
            for e in (ents_before or []):
                e.offset += cursor
            result_text += plain_before
            result_entities += list(ents_before or [])
            cursor += len(plain_before)

        emoji_id = m.group(1)
        inner_html = m.group(2)
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
        result_text += inner_plain
        cursor += len(inner_plain)
        pos_in_html = m.end()

    tail_html = html_text[pos_in_html:]
    if tail_html:
        plain_tail, ents_tail = tl_html.parse(tail_html)
        for e in (ents_tail or []):
            e.offset += cursor
        result_text += plain_tail
        result_entities += list(ents_tail or [])

    result_entities.sort(key=lambda e: e.offset)
    return result_text, result_entities
