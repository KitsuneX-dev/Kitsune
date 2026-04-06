"""
kitsune/web/ssh_tunnel.py — SSH-туннелирование для публичного доступа к веб-UI.

Поднимает SSH-туннель через бесплатные сервисы (serveo.net, localhost.run)
чтобы сделать локальный веб-интерфейс Kitsune доступным из интернета —
без VPS и без настройки роутера.

Автоматически пробует сервисы по очереди и переключается при сбое.
"""

from __future__ import annotations

import asyncio
import logging
import re
import typing

logger = logging.getLogger(__name__)

# Список SSH-туннель-сервисов: (команда, regex для URL)
_TUNNEL_SERVICES: list[tuple[str, str]] = [
    (
        "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 "
        "-R 80:127.0.0.1:{port} serveo.net -T -n",
        r"https?://(\S+\.serveo\.net\S*)",
    ),
    (
        "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 "
        "-R 80:127.0.0.1:{port} nokey@localhost.run",
        r"https?://(\S+\.lhr\.life\S*)",
    ),
]

_RECONNECT_DELAY = 10  # секунд до переподключения при обрыве


class SSHTunnel:
    """
    Поднимает и поддерживает SSH-туннель.

    При обрыве автоматически пробует следующий сервис.
    URL туннеля передаётся в change_url_callback при смене.
    """

    def __init__(
        self,
        port: int,
        change_url_callback: typing.Optional[typing.Callable[[str], None]] = None,
    ) -> None:
        self._port               = port
        self._change_url_callback = change_url_callback
        self._tunnel_url: str | None = None
        self._url_available      = asyncio.Event()
        self._process: typing.Any = None
        self._task: typing.Any    = None
        self._stopped             = False
        self._service_idx         = 0

    @property
    def url(self) -> str | None:
        return self._tunnel_url

    async def start(self) -> None:
        """Запустить туннель (не блокирует)."""
        self._stopped = False
        self._task = asyncio.ensure_future(self._run_loop())

    async def stop(self) -> None:
        """Остановить туннель."""
        self._stopped = True
        if self._task and not self._task.done():
            self._task.cancel()
        await self._kill_process()

    async def wait_url(self, timeout: float = 30.0) -> str | None:
        """Ждать появления URL туннеля."""
        try:
            await asyncio.wait_for(self._url_available.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        return self._tunnel_url

    async def _run_loop(self) -> None:
        """Основной цикл: пробует сервисы по очереди, перезапускает при сбое."""
        while not self._stopped:
            cmd_template, url_pattern = _TUNNEL_SERVICES[self._service_idx % len(_TUNNEL_SERVICES)]
            cmd = cmd_template.format(port=self._port)
            logger.info("SSHTunnel: запуск туннеля: %s", cmd.split()[0:4])

            try:
                await self._run_process(cmd, url_pattern)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("SSHTunnel: ошибка туннеля")

            if not self._stopped:
                self._service_idx += 1
                logger.info("SSHTunnel: переключение на следующий сервис, ожидание %ds", _RECONNECT_DELAY)
                await asyncio.sleep(_RECONNECT_DELAY)

    async def _run_process(self, cmd: str, url_pattern: str) -> None:
        self._url_available.clear()
        self._tunnel_url = None

        try:
            self._process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except Exception as exc:
            logger.warning("SSHTunnel: не удалось запустить процесс: %s", exc)
            return

        regex = re.compile(url_pattern)

        assert self._process.stdout is not None
        async for raw_line in self._process.stdout:
            if self._stopped:
                break
            try:
                line = raw_line.decode(errors="ignore").strip()
            except Exception:
                continue

            logger.debug("SSHTunnel: %s", line)

            match = regex.search(line)
            if match:
                url = match.group(0)
                if not url.startswith("http"):
                    url = "https://" + match.group(1)
                self._tunnel_url = url
                self._url_available.set()
                logger.info("SSHTunnel: URL получен: %s", url)

                if self._change_url_callback:
                    try:
                        self._change_url_callback(url)
                    except Exception:
                        logger.debug("SSHTunnel: ошибка в change_url_callback", exc_info=True)

        await self._process.wait()
        logger.info("SSHTunnel: процесс завершился (код %s)", self._process.returncode)

    async def _kill_process(self) -> None:
        if self._process and self._process.returncode is None:
            try:
                self._process.kill()
                await self._process.wait()
            except Exception:
                pass
