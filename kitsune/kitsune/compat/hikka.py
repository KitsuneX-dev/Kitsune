from __future__ import annotations

import asyncio
import sys
import types
import logging
import typing

logger = logging.getLogger(__name__)

_SHIM_APPLIED = False

class _HikkaCompatMixin:
    async def request_join(self, username: str, message: str = "") -> None:
        try:
            from telethon.functions.channels import JoinChannelRequest
            from telethon.functions.messages import ImportChatInviteRequest
            if username.startswith("https://t.me/+"):
                invite = username.split("+")[-1]
                await self.client(ImportChatInviteRequest(invite))
            else:
                await self.client(JoinChannelRequest(username))
            logger.info(f"HikkaCompat: Joined {username}")
        except Exception as e:
            logger.warning(f"HikkaCompat: Failed to join {username}: {e}")

    def get_prefix(self) -> str:
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        return dispatcher._prefix if dispatcher else "."

    async def animate(self, chat_id: int, frames: list[str], interval: float = 0.5) -> None:
        for frame in frames:
            try:
                msg = await self.client.send_message(chat_id, frame)
                await asyncio.sleep(interval)
                await msg.delete()
            except Exception as e:
                logger.warning(f"HikkaCompat: Animate error: {e}")
                break

    async def get_chats(self) -> list:
        try:
            dialogs = []
            async for dialog in self.client.iter_dialogs():
                dialogs.append(dialog)
            return dialogs
        except Exception as e:
            logger.warning(f"HikkaCompat: get_chats error: {e}")
            return []

    async def get_chat(self, chat_id: int | str):
        try:
            return await self.client.get_entity(chat_id)
        except Exception as e:
            logger.warning(f"HikkaCompat: get_chat error: {e}")
            return None

    async def delete_chat(self, chat_id: int) -> bool:
        try:
            await self.client.delete_dialog(chat_id)
            return True
        except Exception as e:
            logger.warning(f"HikkaCompat: delete_chat error: {e}")
            return False

    async def get_user(self, user_id: int | str):
        try:
            return await self.client.get_entity(user_id)
        except Exception as e:
            logger.warning(f"HikkaCompat: get_user error: {e}")
            return None

    async def invite_to_chat(self, chat_id: int, user_id: int) -> bool:
        try:
            await self.client.invite_to_chat(chat_id, user_id)
            return True
        except Exception as e:
            logger.warning(f"HikkaCompat: invite_to_chat error: {e}")
            return False

    async def kick_from_chat(self, chat_id: int, user_id: int) -> bool:
        try:
            await self.client.kick_participant(chat_id, user_id)
            return True
        except Exception as e:
            logger.warning(f"HikkaCompat: kick_from_chat error: {e}")
            return False

    async def mute_chat(self, chat_id: int, mute: bool = True) -> bool:
        try:
            if mute:
                await self.client.mute_chat(chat_id)
            else:
                await self.client.unmute_chat(chat_id)
            return True
        except Exception as e:
            logger.warning(f"HikkaCompat: mute_chat error: {e}")
            return False

    async def pin_message(self, chat_id: int, message_id: int, both: bool = False) -> bool:
        try:
            await self.client.pin_message(chat_id, message_id, notify=both)
            return True
        except Exception as e:
            logger.warning(f"HikkaCompat: pin_message error: {e}")
            return False

    async def unpin_message(self, chat_id: int, message_id: int | None = None) -> bool:
        try:
            if message_id:
                await self.client.unpin_message(chat_id, message_id)
            else:
                await self.client.unpin_message(chat_id)
            return True
        except Exception as e:
            logger.warning(f"HikkaCompat: unpin_message error: {e}")
            return False

    def getConfig(self, key: str, default: typing.Any = None) -> typing.Any:
        return self.db.get(f"hikka.{type(self).__name__}", key, default)

    def setConfig(self, key: str, value: typing.Any) -> None:
        self.db.set(f"hikka.{type(self).__name__}", key, value)

    def get(self, key: str, default: typing.Any = None) -> typing.Any:
        return self.getConfig(key, default)

    def set(self, key: str, value: typing.Any) -> None:
        self.setConfig(key, value)

    def lookup(self, name: str) -> typing.Any:
        loader_obj = getattr(self.client, "_kitsune_loader", None)
        return loader_obj.get_module(name) if loader_obj else None

    @property
    def allmodules(self) -> dict:
        loader_obj = getattr(self.client, "_kitsune_loader", None)
        return loader_obj.modules if loader_obj else {}

def _patch_module_class(cls: type) -> type:
    for name in dir(_HikkaCompatMixin):
        if not name.startswith("_"):
            setattr(cls, name, getattr(_HikkaCompatMixin, name))
    return cls

def _make_compat_module_base() -> type:
    from ..core.loader import KitsuneModule
    
    class HikkaCompatModule(KitsuneModule, _HikkaCompatMixin):
        pass
    
    return HikkaCompatModule

def apply() -> None:
    global _SHIM_APPLIED
    if _SHIM_APPLIED:
        return

    HikkaCompatModule = _make_compat_module_base()

    loader_shim = types.ModuleType("hikka.loader")
    loader_shim.Module  = HikkaCompatModule

    security_shim = types.ModuleType("hikka.security")
    security_shim.OWNER           = 1 << 0
    security_shim.SUDO            = 1 << 1
    security_shim.SUPPORT         = 1 << 2
    security_shim.GROUP_OWNER     = 1 << 3
    security_shim.GROUP_ADMIN     = 1 << 4
    security_shim.GROUP_ADMIN_ANY = 1 << 5
    security_shim.GROUP_MEMBER    = 1 << 6
    security_shim.PM              = 1 << 7
    security_shim.EVERYONE        = 1 << 8

    from .. import utils as kitsune_utils
    utils_shim = types.ModuleType("hikka.utils")
    utils_shim.escape_html    = kitsune_utils.escape_html
    utils_shim.chunks         = kitsune_utils.chunks
    utils_shim.run_sync       = kitsune_utils.run_sync
    utils_shim.find_caller    = kitsune_utils.find_caller
    utils_shim.is_serializable = kitsune_utils.is_serializable
    utils_shim.get_args       = kitsune_utils.get_args
    utils_shim.get_args_raw   = kitsune_utils.get_args_raw
    utils_shim.answer         = kitsune_utils.answer

    hikka_shim = types.ModuleType("hikka")
    hikka_shim.loader   = loader_shim
    hikka_shim.security = security_shim
    hikka_shim.utils    = utils_shim

    sys.modules["hikka"]          = hikka_shim
    sys.modules["hikka.loader"]   = loader_shim
    sys.modules["hikka.security"] = security_shim
    sys.modules["hikka.utils"]    = utils_shim

    try:
        import telethon
        sys.modules.setdefault("hikkatl", telethon)
    except ImportError:
        pass

    try:
        import hydrogram
        sys.modules.setdefault("hikkapyro", hydrogram)
    except ImportError:
        try:
            import pyrogram
            sys.modules.setdefault("hikkapyro", pyrogram)
        except ImportError:
            pass

    _SHIM_APPLIED = True
    logger.debug("compat: Hikka shims installed")