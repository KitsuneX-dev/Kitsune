
from __future__ import annotations

import asyncio
import logging
import typing

from .ssh_tunnel import SSHTunnel

logger = logging.getLogger(__name__)

class ProxyPasser:

    def __init__(
        self,
        port: int,
        *,
        on_url: typing.Optional[typing.Callable[[str], typing.Awaitable[None]]] = None,
        verbose: bool = False,
    ) -> None:
        self._port    = port
        self._on_url  = on_url
        self._verbose = verbose
        self._tunnel  = SSHTunnel(
            port=port,
            change_url_callback=self._sync_url_changed,
        )
        self._current_url: str | None = None
        self._loop: typing.Any = None

    @property
    def url(self) -> str | None:
        return self._tunnel.url

    async def start(self) -> None:
        self._loop = asyncio.get_event_loop()
        await self._tunnel.start()
        logger.info("ProxyPasser: запущен на порту %d", self._port)

    async def stop(self) -> None:
        await self._tunnel.stop()
        logger.info("ProxyPasser: остановлен")

    async def wait_url(self, timeout: float = 30.0) -> str | None:
        return await self._tunnel.wait_url(timeout=timeout)

    def _sync_url_changed(self, url: str) -> None:
        self._current_url = url
        if self._loop and self._on_url:
            asyncio.run_coroutine_threadsafe(
                self._async_url_changed(url),
                self._loop,
            )

    async def _async_url_changed(self, url: str) -> None:
        if self._on_url:
            try:
                await self._on_url(url)
            except Exception:
                logger.debug("ProxyPasser: ошибка в on_url callback", exc_info=True)
