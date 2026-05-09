from __future__ import annotations
import asyncio
import logging
import re
import typing

logger = logging.getLogger(__name__)

_BOTFATHER = "BotFather"

_TOKEN_RE  = re.compile(r"\d+:[A-Za-z0-9_-]{35,}")

async def obtain_token(client: typing.Any, bot_name: str | None = None) -> str | None:
    """Создаёт нового бота через @BotFather.

    ВАЖНО: username бота строится из tg_id владельца, а не из его имени —
    так мы потом сможем надёжно найти этот бот при переустановке Kitsune.
    """

    me = await client.get_me()

    if bot_name is None:

        bot_name = f"kitsune_{me.id}_bot"

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
