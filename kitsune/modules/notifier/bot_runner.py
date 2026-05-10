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

# Регэксп, которым ловим формат токена бота от @BotFather.
_TOKEN_RE = re.compile(r"(\d{8,}:[A-Za-z0-9_-]{35,})")

# Эвристики, по которым мы понимаем, что BotFather прислал список ботов
# для выбора (а не сам токен). Это ключевая часть фикса для шага «Choose a bot
# to get Bot API access token.» — без неё мы пропускали выбор кнопки и шли
# создавать нового бота.
_CHOOSE_BOT_HINTS = (
    "choose a bot",
    "select a bot",
    "выбери бота",
    "выберите бота",
    "выбери бот",
    "выберите бот",
)


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


def _looks_like_choose_bot(message) -> bool:
    """Возвращает True, если ответ BotFather — это список ботов на выбор."""
    text = (getattr(message, "text", "") or "").lower()
    if any(h in text for h in _CHOOSE_BOT_HINTS):
        return True
    # Иногда заголовок отсутствует, но кнопок несколько и все они выглядят
    # как @username_bot — это тоже список выбора.
    btns = _extract_buttons(message)
    if len(btns) >= 2:
        usernames = [b for b in btns if "bot" in b.lower()]
        if len(usernames) >= 2:
            return True
    return False


def _pick_bot_button(buttons: list[str], username: str) -> str | None:
    """Ищет в списке кнопок ту, что соответствует нашему боту."""
    uname_low = username.lower().lstrip("@")
    # 1) точное совпадение @username
    for b in buttons:
        if b.lstrip("@").strip().lower() == uname_low:
            return b
    # 2) подстрока username
    for b in buttons:
        if uname_low in b.lower():
            return b
    return None


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
        """Ищет среди ботов пользователя бота Kitsune, созданного ранее.

        Поиск ведётся СТРОГО по tg_id владельца — именно этот ID Kitsune
        всегда вшивает в username бота при создании. Имя пользователя может
        меняться, ориентироваться на него нельзя.

        Сценарии:
          • Первая установка — ничего не найдено → (None, None) → создаём нового.
          • Переустановка/сбой — бот уже есть в BotFather → берём его токен.
        """
        try:

            async with _BOTFATHER_LOCK:

                async with self._client.conversation("@BotFather", timeout=40) as conv:

                    await conv.send_message("/mybots")

                    resp = await conv.get_response()

                    text    = resp.text or ""

                    buttons = _extract_buttons(resp)

                    # Ищем строго по ID — формат kitsune_<tg_id>[любой_суффикс]_bot
                    pattern = re.compile(rf"kitsune_{tg_id}[a-z0-9_]*_?bot", re.IGNORECASE)

                    raw_candidates: list[str] = []

                    # 1) Сканируем текст ответа BotFather (там бывают @username)
                    for m in pattern.finditer(text):

                        uname = m.group(0).lstrip("@")

                        if uname not in raw_candidates:

                            raw_candidates.append(uname)

                    # 2) Сканируем кнопки — обычно это основной источник username
                    for b in buttons:

                        b_clean = b.lstrip("@").strip()

                        if pattern.search(b_clean):

                            uname = b.lstrip("@").strip()

                            if uname and uname not in raw_candidates:

                                raw_candidates.append(uname)

                    # 3) Безопасный fallback: любой бот с вхождением tg_id в имя.
                    #    Это покрывает случаи, когда раньше префикс был другим (legacy).
                    legacy_pat = re.compile(rf"[a-z0-9_]*{tg_id}[a-z0-9_]*bot", re.IGNORECASE)

                    for b in buttons:

                        b_clean = b.lstrip("@").strip()

                        if legacy_pat.fullmatch(b_clean) and b_clean not in raw_candidates:

                            raw_candidates.append(b_clean)

                    exact = f"kitsune_{tg_id}_bot"

                    def _sort_key(u: str) -> tuple:

                        u_low = u.lower()

                        # Сначала — точное совпадение kitsune_<id>_bot,
                        # потом явные «kitsune_<id>», потом остальные.
                        if u_low == exact:
                            return (0, len(u_low))
                        if u_low.startswith(f"kitsune_{tg_id}"):
                            return (1, len(u_low))
                        return (2, len(u_low))

                    candidates = sorted(raw_candidates, key=_sort_key)

                    logger.info(
                        "BotSetup: find_existing_bot for tg_id=%s candidates=%s",
                        tg_id, candidates,
                    )

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

                    # ВСЕГДА строим username из tg_id владельца — это гарантирует,
                    # что при следующем запуске find_existing_bot найдёт бота по ID.
                    return_uname: str | None = None
                    return_token: str | None = None

                    for suffix in ["", f"_{me.id % 10000}", "_ub", "_kitsune_ub"]:

                        uname = f"kitsune_{me.id}{suffix}_bot"

                        await conv.send_message(uname)

                        resp = await conv.get_response()

                        text = resp.text or ""

                        m = _TOKEN_RE.search(text)

                        if m:

                            return_token = m.group(1)
                            return_uname = uname

                            # Покидаем conversation/lock — даём вложенным
                            # обработчикам возможность открыть свои диалоги
                            # с @BotFather без коллизии.
                            break

                    else:

                        return None, None

            if not return_token or not return_uname:
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
        """Получает токен для конкретного бота через диалог с @BotFather.

        Делегирует основной поток в `_get_token_via_conv`, чтобы код выбора
        бота из списка («Choose a bot to get Bot API access token.») жил
        в одном месте.
        """

        username = username.lstrip("@")

        try:

            async with _BOTFATHER_LOCK:

                async with self._client.conversation("@BotFather", timeout=40) as conv:

                    await conv.send_message("/mybots")

                    resp = await conv.get_response()

                    buttons = _extract_buttons(resp)

                    return await self._get_token_via_conv(conv, username, buttons)

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

    async def _get_token_via_conv(
        self,
        conv,
        username: str,
        buttons: list[str],
    ) -> str | None:
        """Достаёт токен у @BotFather для указанного `username`.

        Полный поток (исправлен, чтобы корректно обрабатывать все три уровня
        BotFather):

        1. /mybots  → `buttons` (список ботов).
        2. Кликаем по кнопке/тексту с `@username`  → меню бота.
        3. В меню ищем кнопку «API Token». Если её нет — отправляем `/token`.
        4. ⚠ ВАЖНО: после `/token` BotFather может прислать «Choose a bot to
           get Bot API access token.» со списком кнопок. Это и был баг —
           раньше мы тут возвращали None и шли создавать нового бота. Теперь
           кликаем по нужной кнопке и читаем токен.
        """

        username = username.lstrip("@")

        try:

            # --- Шаг 2: выбираем нашего бота из списка /mybots --------------
            btn = _pick_bot_button(buttons, username)

            await conv.send_message(btn or f"@{username}")

            menu = await conv.get_response()

            # Иногда токен прилетает уже здесь (если у бота единственный
            # сценарий — отдать токен).
            m = _TOKEN_RE.search(menu.text or "")
            if m:
                return m.group(1)

            # --- Шаг 3: жмём «API Token» из меню или шлём /token -----------
            menu_btns = _extract_buttons(menu)

            api_btn = next(
                (b for b in menu_btns if "token" in b.lower() or "api" in b.lower()),
                None,
            )

            await conv.send_message(api_btn or "/token")

            token_resp = await conv.get_response()

            m2 = _TOKEN_RE.search(token_resp.text or "")
            if m2:
                return m2.group(1)

            # --- Шаг 4 (фикс): BotFather прислал список ботов на выбор -----
            # Текст: «Choose a bot to get Bot API access token.»
            # Кнопки: список всех @username_bot пользователя.
            if _looks_like_choose_bot(token_resp):

                choose_btns = _extract_buttons(token_resp)

                pick = _pick_bot_button(choose_btns, username)

                if pick is None:
                    logger.debug(
                        "BotSetup: 'Choose a bot' пришёл, но кнопки для @%s не нашлось "
                        "(buttons=%r)", username, choose_btns,
                    )
                    return None

                logger.debug(
                    "BotSetup: выбираю бота из списка /token → %r", pick,
                )

                await conv.send_message(pick)

                final_resp = await conv.get_response()

                m3 = _TOKEN_RE.search(final_resp.text or "")
                if m3:
                    return m3.group(1)

                # Иногда после выбора BotFather всё равно показывает меню,
                # а токен прилетает ещё одним сообщением — добираем.
                try:
                    extra = await asyncio.wait_for(
                        conv.get_response(), timeout=5.0,
                    )
                    m4 = _TOKEN_RE.search(extra.text or "")
                    if m4:
                        return m4.group(1)
                except (asyncio.TimeoutError, Exception):
                    pass

                # Возможно, после выбора нам сначала показывают меню бота,
                # а токен надо ещё «попросить» кнопкой API Token.
                final_btns = _extract_buttons(final_resp)
                api_btn2 = next(
                    (b for b in final_btns
                     if "token" in b.lower() or "api" in b.lower()),
                    None,
                )
                if api_btn2:
                    await conv.send_message(api_btn2)
                    token_resp2 = await conv.get_response()
                    m5 = _TOKEN_RE.search(token_resp2.text or "")
                    if m5:
                        return m5.group(1)

            return None

        except Exception as exc:

            logger.debug("BotSetup: _get_token_via_conv failed for %s — %s", username, exc)

            return None
