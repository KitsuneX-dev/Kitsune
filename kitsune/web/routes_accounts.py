
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class RoutesAccountsMixin:

    async def _handle_accounts_list(self, request):
        try:
            from ..accounts_manager import get_manager
            mgr = get_manager()
            return self._json({
                "ok": True,
                "accounts": mgr.list_accounts(),
                "count": mgr.count(),
                "max": mgr.max_accounts,
                "can_add": mgr.can_add(),
            })
        except Exception as exc:
            logger.debug("accounts: не удалось получить список", exc_info=True)
            return self._json({"ok": False, "error": str(exc)})

    async def _handle_accounts_create(self, request):
        try:
            from ..accounts_manager import get_manager
            from ..account_setup import AccountSetupSession
            mgr = get_manager()
            if not mgr.can_add():
                return self._json({
                    "ok": False,
                    "error": f"Достигнут лимит доп.аккаунтов ({mgr.max_accounts}).",
                })
            body = await request.json()
            name = str(body.get("name", "")).strip() or "twink"
            meta = mgr.create_account(name)
            slug = meta["slug"]
            self._setup_sessions[slug] = AccountSetupSession(slug, mgr.account_dir(slug))
            return self._json({"ok": True, "slug": slug, "name": meta["name"]})
        except Exception as exc:
            logger.exception("accounts: создание доп.аккаунта не удалось")
            return self._json({"ok": False, "error": str(exc)})

    def _setup_session(self, slug):
        sess = self._setup_sessions.get(slug)
        if sess is not None:
            return sess
        try:
            from ..accounts_manager import get_manager
            from ..account_setup import AccountSetupSession
            mgr = get_manager()
            if mgr.get_meta(slug) is None:
                return None
            sess = AccountSetupSession(slug, mgr.account_dir(slug))
            self._setup_sessions[slug] = sess
            return sess
        except Exception:
            logger.debug("accounts: не удалось восстановить сессию мастера %s", slug, exc_info=True)
            return None

    async def _handle_accounts_sendcode(self, request):
        try:
            body = await request.json()
            slug = str(body.get("slug", "")).strip()
            sess = self._setup_session(slug)
            if sess is None:
                return self._json({"ok": False, "error": "Сессия регистрации не найдена"})
            data = {
                "api_id": body.get("api_id"),
                "api_hash": body.get("api_hash"),
                "phone": body.get("phone"),
                "stage": body.get("stage", "telethon"),
            }
            res = await sess.sendcode(data)
            return self._json(res)
        except Exception as exc:
            logger.debug("accounts: sendcode не удался", exc_info=True)
            return self._json({"ok": False, "error": str(exc)})

    async def _handle_accounts_setup_state(self, request):
        try:
            slug = str(request.match_info.get("slug", "")).strip()
            sess = self._setup_session(slug)
            if sess is None:
                return self._json({"ok": False, "error": "Сессия регистрации не найдена"})
            return self._json(sess.code_state())
        except Exception as exc:
            logger.debug("accounts: state не получен", exc_info=True)
            return self._json({"ok": False, "error": str(exc)})

    async def _handle_accounts_signin(self, request):
        try:
            body = await request.json()
            slug = str(body.get("slug", "")).strip()
            sess = self._setup_session(slug)
            if sess is None:
                return self._json({"ok": False, "error": "Сессия регистрации не найдена"})
            res = await sess.signin({
                "code": body.get("code"),
                "stage": body.get("stage", "telethon"),
            })
            await self._maybe_finalize_setup(slug, sess)
            return self._json(res)
        except Exception as exc:
            logger.debug("accounts: signin не удался", exc_info=True)
            return self._json({"ok": False, "error": str(exc)})

    async def _handle_accounts_2fa(self, request):
        try:
            body = await request.json()
            slug = str(body.get("slug", "")).strip()
            sess = self._setup_session(slug)
            if sess is None:
                return self._json({"ok": False, "error": "Сессия регистрации не найдена"})
            res = await sess.twofa({
                "password": body.get("password"),
                "stage": body.get("stage", "telethon"),
            })
            await self._maybe_finalize_setup(slug, sess)
            return self._json(res)
        except Exception as exc:
            logger.debug("accounts: 2fa не прошла", exc_info=True)
            return self._json({"ok": False, "error": str(exc)})

    async def _maybe_finalize_setup(self, slug, sess):
        if not sess.hydrogram_done():
            return
        try:
            from ..accounts_manager import get_manager
            mgr = get_manager()
            me = sess.me()
            fields = {}
            if me is not None:
                fields["user_id"] = getattr(me, "id", 0)
                fields["username"] = getattr(me, "username", "") or ""
                if getattr(me, "first_name", None):
                    fields["name"] = me.first_name
            cfg_file = mgr.account_dir(slug) / "config.toml"
            if cfg_file.exists():
                try:
                    import toml
                    cfg = toml.loads(cfg_file.read_text(encoding="utf-8"))
                    if cfg.get("phone"):
                        fields["phone"] = cfg["phone"]
                except Exception:
                    logger.debug("accounts: config.toml твинка %s не прочитан", slug, exc_info=True)
            if fields:
                mgr.update_meta(slug, **fields)
            await sess.close()
            self._setup_sessions.pop(slug, None)
            await mgr.start_account(slug)
        except Exception:
            logger.exception("WebCore: finalize account setup failed")

    async def _handle_accounts_toggle(self, request):
        try:
            from ..accounts_manager import get_manager
            mgr = get_manager()
            slug = request.match_info.get("slug", "")
            body = {}
            try:
                body = await request.json()
            except Exception:
                logger.debug("accounts: toggle без JSON-тела, включаем по умолчанию", exc_info=True)
            enable = bool(body.get("enable", True))
            if enable:
                res = await mgr.start_account(slug)
            else:
                res = await mgr.stop_account(slug, disable=True)
            return self._json(res)
        except Exception as exc:
            logger.exception("accounts: переключение твинка не удалось")
            return self._json({"ok": False, "error": str(exc)})

    async def _handle_accounts_delete(self, request):
        try:
            from ..accounts_manager import get_manager
            mgr = get_manager()
            slug = request.match_info.get("slug", "")
            sess = self._setup_sessions.pop(slug, None)
            if sess is not None:
                await sess.close()
            res = await mgr.delete_account(slug)
            return self._json(res)
        except Exception as exc:
            logger.exception("accounts: удаление твинка не удалось")
            return self._json({"ok": False, "error": str(exc)})
