from __future__ import annotations
import contextlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _make_config_fns(config_file: Path):
    def _load() -> dict[str, Any]:
        if not config_file.exists():
            return {}
        try:
            import toml
            return toml.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("account_setup: failed to read %s", config_file)
            return {}

    def _save(data: dict[str, Any]) -> None:
        try:
            import toml
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config_file.write_text(toml.dumps(data), encoding="utf-8")
            with contextlib.suppress(Exception):

                from .paths import harden_file as _harden_file
                _harden_file(config_file)
        except Exception:
            logger.exception("account_setup: failed to write %s", config_file)

    return _load, _save


class AccountSetupSession:
    def __init__(self, slug: str, account_dir: Path) -> None:
        self.slug = slug
        self.account_dir = Path(account_dir)
        self.config_file = self.account_dir / "config.toml"
        load_fn, save_fn = _make_config_fns(self.config_file)
        from .web.setup import SetupServer
        self._srv = SetupServer(
            save_config_fn=save_fn,
            get_config_fn=load_fn,
            hydrogram_only=False,
            data_dir_override=self.account_dir,
        )

    def telethon_done(self) -> bool:
        return bool(getattr(self._srv, "_telethon_success", False))

    def hydrogram_done(self) -> bool:
        return bool(getattr(self._srv, "_hydrogram_success", False))

    def code_state(self) -> dict:
        srv = self._srv
        stage = str(getattr(srv, "_code_stage", "idle"))
        backend = getattr(srv, "_code_backend", None)
        phone = (
            getattr(srv, "_hydro_phone", None)
            if backend == "hydrogram"
            else getattr(srv, "_phone", None)
        )
        return {
            "ok": True,
            "stage": stage,
            "error": getattr(srv, "_code_error", None),
            "backend": backend,
            "telethon_done": self.telethon_done(),
            "hydrogram_done": self.hydrogram_done(),
            "phone": phone if stage != "idle" else None,
        }

    def me(self) -> Any:
        return getattr(self._srv, "_client", None) and getattr(
            self._srv._client, "tg_me", None
        )

    async def sendcode(self, data: dict) -> dict:
        return await self._call(self._srv._api_sendcode, data)

    async def signin(self, data: dict) -> dict:
        return await self._call(self._srv._api_signin, data)

    async def twofa(self, data: dict) -> dict:
        return await self._call(self._srv._api_2fa, data)

    async def _call(self, handler, data: dict) -> dict:
        req = _FakeRequest(data)
        resp = await handler(req)
        try:
            return json.loads(resp.text)
        except Exception:
            return {"ok": False, "error": "bad response"}

    async def close(self) -> None:
        srv = self._srv
        with contextlib.suppress(Exception):
            if getattr(srv, "_client", None) is not None:
                await srv._client.disconnect()
        with contextlib.suppress(Exception):
            if getattr(srv, "_hydro_client", None) is not None:
                await srv._hydro_client.disconnect()


class _FakeRequest:
    def __init__(self, data: dict) -> None:
        self._data = data

    async def json(self) -> dict:
        return self._data
