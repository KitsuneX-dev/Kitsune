from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_KEY = "kitsune.notifier"

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
            async with self._client.conversation("@BotFather", timeout=40) as conv:
                await conv.send_message("/mybots")
                resp = await conv.get_response()

                text = resp.text or ""
                pattern = rf"kitsune_{tg_id}[a-z0-9_]*_bot"
                candidates: list[str] = []
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    candidates.append(match.group(0))

                buttons = _extract_buttons(resp)
                for b in buttons:
                    b_clean = b.lstrip("@").lower()
                    if f"kitsune_{tg_id}" in b_clean or "kitsune" in b_clean:
                        uname = b.lstrip("@")
                        if uname not in candidates:
                            candidates.append(uname)

                for username in candidates:
                    token = await self._get_token_via_conv(conv, username, buttons)
                    if token:
                        return token, username

        except Exception as exc:
            logger.debug("BotSetup: find_existing_bot failed — %s", exc)
        return None, None

    async def create_bot(self, me, bot_name: str) -> tuple[str | None, str | None]:
        try:
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
                        await self.enable_inline_mode(uname)
                        return m.group(1), uname
                    if any(w in text.lower() for w in ("sorry", "invalid", "try", "занят")):
                        continue
                    break
        except Exception as exc:
            logger.error("BotSetup: create_bot failed — %s", exc)
        return None, None

    async def get_token_for_bot(self, username: str) -> str | None:
        username = username.lstrip("@")
        try:
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

    async def enable_inline_mode(self, username: str) -> None:
        import asyncio
        try:
            async with self._client.conversation("@BotFather", timeout=30) as conv:
                await conv.send_message("/setinline")
                await conv.get_response()
                await conv.send_message(f"@{username}")
                await conv.get_response()
                await conv.send_message("kitsune")
                await conv.get_response()
            logger.info("BotSetup: inline mode enabled for @%s", username)
            await asyncio.sleep(1)
            async with self._client.conversation("@BotFather", timeout=30) as conv:
                await conv.send_message("/setinlinefeedback")
                await conv.get_response()
                await conv.send_message(f"@{username}")
                await conv.get_response()
                await conv.send_message("Enabled")
                await conv.get_response()
        except Exception as exc:
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
