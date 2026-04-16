from __future__ import annotations

import asyncio
import logging
import re
import typing

logger = logging.getLogger(__name__)

_BOTFATHER = "BotFather"
_TOKEN_RE  = re.compile(r"\d+:[A-Za-z0-9_-]{35,}")

async def obtain_token(client: typing.Any, bot_name: str | None = None) -> str | None:
    import typing

    if bot_name is None:
        me = await client.get_me()
        safe = re.sub(r"[^a-zA-Z0-9]", "", me.first_name or "kitsune").lower()
        bot_name = f"{safe}_kitsune_bot"
        if len(bot_name) < 5:
            bot_name = "kitsune_userbot_bot"

    logger.info("token_obtainment: requesting token for @%s from BotFather", bot_name)

    try:
        await client.send_message(_BOTFATHER, "/cancel")
        await asyncio.sleep(1)
        await client.send_message(_BOTFATHER, "/newbot")
        await asyncio.sleep(2)

        await client.send_message(_BOTFATHER, "Kitsune Userbot")
        await asyncio.sleep(2)

        await client.send_message(_BOTFATHER, bot_name)
        await asyncio.sleep(3)

        msgs = await client.get_messages(_BOTFATHER, limit=3)
        for msg in msgs:
            if msg.text:
                match = _TOKEN_RE.search(msg.text)
                if match:
                    token = match.group(0)
                    logger.info("token_obtainment: token obtained")
                    return token

        logger.warning("token_obtainment: token not found in BotFather reply")
        return None
    except Exception:
        logger.exception("token_obtainment: failed")
        return None
