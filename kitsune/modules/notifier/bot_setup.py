from __future__ import annotations
import asyncio
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_KEY = "kitsune.notifier"

# Глобальный лок, чтобы две (и более) корутины не открывали `conversation`
# с @BotFather одновременно — иначе Telethon бросает
# "Cannot open exclusive conversation in a chat that already has one open conversation".
_BOTFATHER_LOCK: asyncio.Lock = asyncio.Lock()


def _extract_buttons(message) -> list[str]:

    result = []

    try:

        markup = getattr(message, "reply_markup", None)

        if markup is None:

            return result

        rows = getattr(markup, "rows", []) or []

        for row in rows:

            for btn in getattr(row, "buttons", []) or []:

                text = getattr(btn, "text", "") or ""

                if text:

                    result.append(text)

    except Exception:

        pass

    return result

class BotSetup:

    def __init__(self, client, db) -> None:

        self._client = client

        self._db = db

    def load_token_from_config(self) -> str | None:

        try:

            import toml

            cfg_path = Path(__file__).parent.parent.parent.parent / "config.toml"

            if cfg_path.exists():

                val = toml.loads(cfg_path.read_text(encoding="utf-8")).get("bot_token")

                return str(val) if val else None

        except Exception:

            pass

        return None

    def save_token_to_config(self, token: str) -> None:

        try:

            import toml

            cfg_path = Path(__file__).parent.parent.parent.parent / "config.toml"

            if cfg_path.exists():

                cfg = toml.loads(cfg_path.read_text(encoding="utf-8"))

                cfg["bot_token"] = token

                cfg_path.write_text(toml.dumps(cfg), encoding="utf-8")

        except Exception:

            logger.warning("BotSetup: could not write token to config.toml")

    async def find_existing_bot(self, tg_id: int) -> tuple[str | None, str | None]:

        try:

            async with _BOTFATHER_LOCK:

                async with self._client.conversation("@BotFather", timeout=40) as conv:

                    await conv.send_message("/mybots")

                    resp = await conv.get_response()

                    text    = resp.text or ""

                    buttons = _extract_buttons(resp)

                    pattern = re.compile(rf"kitsune_{tg_id}[a-z0-9_]*_bot", re.IGNORECASE)

                    raw_candidates: list[str] = []

                    for m in pattern.finditer(text):

                        uname = m.group(0).lstrip("@")

                        if uname not in raw_candidates:

                            raw_candidates.append(uname)

                    for b in buttons:

                        b_clean = b.lstrip("@").lower()

                        if f"kitsune_{tg_id}" in b_clean or "kitsune" in b_clean:

                            uname = b.lstrip("@")

                            if uname not in raw_candidates:

                                raw_candidates.append(uname)

                    exact = f"kitsune_{tg_id}_bot"

                    def _sort_key(u: str) -> tuple:

                        u_low = u.lower()

                        return (0 if u_low == exact else 1, len(u_low))

                    candidates = sorted(raw_candidates, key=_sort_key)

                    logger.debug("BotSetup: find_existing_bot candidates: %s", candidates)

                    for username in candidates:

                        token = await self._get_token_via_conv(conv, username, buttons)

                        if token:

                            logger.info("BotSetup: found existing bot @%s", username)

                            return token, username

        except Exception as exc:

            logger.debug("BotSetup: find_existing_bot failed — %s", exc)

        return None, None

    async def _bot_already_has_avatar(self, uname: str) -> bool:
        """Проверяет, установлена ли уже аватарка у бота.

        Сначала смотрит флаг в БД (быстро, без обращения к Telegram).
        Если флаг не выставлен — реально проверяет наличие фото у бота через
        get_entity (telethon вернёт photo=ChatPhotoEmpty, если фото нет).
        """
        try:
            from ...assets import _DB_NS as _ASSETS_NS  # type: ignore
        except Exception:
            _ASSETS_NS = "kitsune.assets"

        flag_key = f"bot_photo_{uname.lower()}"
        try:
            if self._db.get(_ASSETS_NS, flag_key, False):
                return True
        except Exception:
            pass

        try:
            entity = await self._client.get_entity(f"@{uname}")
            photo = getattr(entity, "photo", None)
            if photo is not None:
                cls_name = type(photo).__name__
                if "Empty" not in cls_name:
                    try:
                        self._db.force_set(_ASSETS_NS, flag_key, True)
                    except Exception:
                        pass
                    return True
        except Exception as exc:
            logger.debug("BotSetup: _bot_already_has_avatar(%s) failed — %s", uname, exc)
        return False

    async def _set_bot_avatar(self, uname: str) -> None:
        """Устанавливает аватарку боту через @BotFather.

        Защищён от:
          • неправильного импорта (исправлен путь `kitsune.assets`);
          • повторной установки, если фото уже есть;
          • параллельных диалогов с @BotFather (через _BOTFATHER_LOCK).
        """
        try:
            # ВАЖНО: правильный путь — kitsune.assets, а не kitsune.modules.assets.
            from ...assets import BOT_AVATAR, _DB_NS  # type: ignore
        except Exception as imp_exc:
            logger.warning("BotSetup: аватарка бота не установлена: %s", imp_exc)
            return

        if not BOT_AVATAR.exists():
            logger.warning(
                "BotSetup: файл аватарки %s не найден — пропускаю установку",
                BOT_AVATAR,
            )
            return

        # Если аватарка уже стоит — даже не лезем к BotFather.
        if await self._bot_already_has_avatar(uname):
            logger.info("BotSetup: у бота @%s уже стоит аватарка — пропускаю", uname)
            try:
                self._db.force_set(_DB_NS, f"bot_photo_{uname.lower()}", True)
            except Exception:
                pass
            return

        try:
            async with _BOTFATHER_LOCK:
                # Небольшая пауза, чтобы предыдущий диалог BotFather
                # точно успел закрыться на стороне Telethon.
                await asyncio.sleep(1.0)
                async with self._client.conversation("@BotFather", timeout=60) as conv:
                    await conv.send_message("/setuserpic")
                    await conv.get_response()
                    await conv.send_message(f"@{uname}")
                    r = await conv.get_response()
                    if any(w in (r.text or "").lower()
                           for w in ("photo", "фото", "pic", "send")):
                        await conv.send_file(str(BOT_AVATAR))
                        r2 = await conv.get_response()
                        if any(w in (r2.text or "").lower()
                               for w in ("updated", "установлено", "success", "saved", "done")):
                            try:
                                self._db.force_set(
                                    _DB_NS, f"bot_photo_{uname.lower()}", True,
                                )
                            except Exception:
                                pass
                            logger.info("BotSetup: аватарка бота @%s установлена", uname)
                            return
                    logger.debug("BotSetup: BotFather неожиданный ответ при /setuserpic — %r", r2 if 'r2' in locals() else r)
        except Exception as _ae:
            logger.warning("BotSetup: аватарка бота не установлена: %s", _ae)

    async def create_bot(self, me, bot_name: str) -> tuple[str | None, str | None]:

        try:

            async with _BOTFATHER_LOCK:

                async with self._client.conversation("@BotFather", timeout=30) as conv:

                    await conv.send_message("/start")

                    await conv.get_response()

                    await conv.send_message("/newbot")

                    await conv.get_response()

                    await conv.send_message(bot_name)

                    await conv.get_response()

                    for suffix in ["", f"_{me.id % 10000}", "_ub", "_kitsune_ub"]:

                        uname = f"kitsune_{me.id}{suffix}_bot"

                        await conv.send_message(uname)

                        resp = await conv.get_response()

                        text = resp.text or ""

                        m = re.search(r"(\d{8,}:[A-Za-z0-9_-]{35,})", text)

                        if m:

                            token = m.group(1)

                            # выходим из conversation перед тем как делать
                            # вложенные звонки в BotFather (enable_inline_mode,
                            # _set_bot_avatar) — они откроют свои диалоги.
                            return_uname = uname
                            return_token = token

                            # Покидаем conversation/lock — даём вложенным
                            # обработчикам возможность открыть свои диалоги
                            # с @BotFather без коллизии.
                            break

                    else:

                        return None, None

            # Вне БотFather-лока: подключаем inline-mode и ставим аватарку.
            try:
                await self.enable_inline_mode(return_uname)
            except Exception as _ie:
                logger.warning("BotSetup: enable_inline_mode wrapper — %s", _ie)

            try:
                await self._set_bot_avatar(return_uname)
            except Exception as _ae:
                logger.warning("BotSetup: _set_bot_avatar wrapper — %s", _ae)

            return return_token, return_uname

        except Exception as exc:

            logger.error("BotSetup: create_bot failed — %s", exc)

        return None, None

    async def get_token_for_bot(self, username: str) -> str | None:

        username = username.lstrip("@")

        try:

            async with _BOTFATHER_LOCK:

                async with self._client.conversation("@BotFather", timeout=40) as conv:

                    await conv.send_message("/mybots")

                    resp = await conv.get_response()

                    buttons = _extract_buttons(resp)

                    target = next((b for b in buttons if username.lower() in b.lower()), None)

                    await conv.send_message(target or f"@{username}")

                    menu = await conv.get_response()

                    m = re.search(r"(\d{8,}:[A-Za-z0-9_-]{35,})", menu.text or "")

                    if m:

                        return m.group(1)

                    menu_btns = _extract_buttons(menu)

                    api_btn = next((b for b in menu_btns if "token" in b.lower() or "api" in b.lower()), None)

                    await conv.send_message(api_btn or "/token")

                    token_resp = await conv.get_response()

                    m2 = re.search(r"(\d{8,}:[A-Za-z0-9_-]{35,})", token_resp.text or "")

                    return m2.group(1) if m2 else None

        except Exception as exc:

            logger.debug("BotSetup: get_token_for_bot failed — %s", exc)

        return None

    async def list_kitsune_bots(self) -> list[tuple[str, str | None]]:

        results = []

        try:

            async with _BOTFATHER_LOCK:

                async with self._client.conversation("@BotFather", timeout=40) as conv:

                    await conv.send_message("/mybots")

                    resp = await conv.get_response()

                    usernames = _extract_buttons(resp)

                    if not usernames:

                        usernames = re.findall(r"@([a-zA-Z0-9_]+bot)", resp.text or "", re.IGNORECASE)

                    for uname in usernames:

                        uname = uname.lstrip("@")

                        token = await self._get_token_via_conv(conv, uname, _extract_buttons(resp))

                        results.append((uname, token))

        except Exception as exc:

            logger.debug("BotSetup: list_kitsune_bots failed — %s", exc)

        return results

    async def _bot_inline_already_enabled(self, username: str) -> bool:
        """Эвристика: открываем меню бота в @BotFather и смотрим, есть ли пункт
        Inline Mode со значением «Enabled». Если выставлен — возвращаем True.

        Делается под общим _BOTFATHER_LOCK, чтобы не конфликтовать с другими диалогами.
        """
        try:
            async with self._client.conversation("@BotFather", timeout=20) as conv:
                await conv.send_message(f"@{username}")
                resp = await conv.get_response()
                text = (resp.text or "").lower()
                # BotFather пишет "Inline Mode: Enabled" или подобное
                if "inline mode" in text and "enabled" in text:
                    return True
                if "инлайн" in text and ("вкл" in text or "enabled" in text):
                    return True
        except Exception as exc:
            logger.debug("BotSetup: _bot_inline_already_enabled(%s) failed — %s",
                         username, exc)
        return False

    async def enable_inline_mode(self, username: str) -> None:

        try:

            async with _BOTFATHER_LOCK:

                # Если inline уже включён — не дублируем процесс.
                if await self._bot_inline_already_enabled(username):
                    logger.info(
                        "BotSetup: inline mode уже включён для @%s — пропускаю", username,
                    )
                    return

                # Пауза, чтобы предыдущая conversation в этом же чате 100%
                # успела закрыться на сервере Telethon.
                await asyncio.sleep(1.0)

                async with self._client.conversation("@BotFather", timeout=30) as conv:

                    await conv.send_message("/setinline")

                    await conv.get_response()

                    await conv.send_message(f"@{username}")

                    await conv.get_response()

                    await conv.send_message("kitsune")

                    await conv.get_response()

                logger.info("BotSetup: inline mode enabled for @%s", username)

                # Ещё одна пауза перед следующим conversation
                # с тем же чатом — Telethon должен освободить exclusive lock.
                await asyncio.sleep(1.5)

                async with self._client.conversation("@BotFather", timeout=30) as conv:

                    await conv.send_message("/setinlinefeedback")

                    await conv.get_response()

                    await conv.send_message(f"@{username}")

                    await conv.get_response()

                    await conv.send_message("Enabled")

                    await conv.get_response()

        except Exception as exc:

            err = str(exc).lower()
            # Эта ошибка не критична: значит inline-режим скорее всего уже включён.
            if "exclusive conversation" in err or "already has one open" in err:
                logger.info(
                    "BotSetup: enable_inline_mode пропущен (диалог BotFather уже занят) — %s",
                    exc,
                )
            else:
                logger.warning("BotSetup: could not enable inline mode — %s", exc)

    async def _get_token_via_conv(self, conv, username: str, buttons: list[str]) -> str | None:

        try:

            btn = next((b for b in buttons if username.lower() in b.lower()), None)

            await conv.send_message(btn or f"@{username}")

            menu = await conv.get_response()

            m = re.search(r"(\d{8,}:[A-Za-z0-9_-]{35,})", menu.text or "")

            if m:

                return m.group(1)

            menu_btns = _extract_buttons(menu)

            api_btn = next((b for b in menu_btns if "token" in b.lower() or "api" in b.lower()), None)

            await conv.send_message(api_btn or "/token")

            token_resp = await conv.get_response()

            m2 = re.search(r"(\d{8,}:[A-Za-z0-9_-]{35,})", token_resp.text or "")

            return m2.group(1) if m2 else None

        except Exception as exc:

            logger.debug("BotSetup: _get_token_via_conv failed for %s — %s", username, exc)

            return None
