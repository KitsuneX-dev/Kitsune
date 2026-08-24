
from __future__ import annotations

import asyncio
import logging
import os
import signal
import typing

logger = logging.getLogger(__name__)

__all__ = ["run_cmd", "kill_process_tree", "ProcResult"]


_REAP_TIMEOUT = 5.0

ProcResult = typing.Tuple[int, bytes, bytes]


async def kill_process_tree(
    proc: asyncio.subprocess.Process,
    *,
    use_group: bool = True,
    sig: int = signal.SIGKILL,
) -> None:
    if proc.returncode is not None:
        return

    killed_group = False
    if use_group:


        try:
            os.killpg(os.getpgid(proc.pid), sig)
            killed_group = True
        except (ProcessLookupError, PermissionError, OSError) as exc:
            logger.debug("proc: killpg(%s) не удался — %s", proc.pid, exc)

    if not killed_group:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        except Exception as exc:  # pragma: no cover — платформозависимо
            logger.debug("proc: kill(%s) не удался — %s", proc.pid, exc)


    try:
        await asyncio.wait_for(proc.wait(), timeout=_REAP_TIMEOUT)
    except (asyncio.TimeoutError, TimeoutError):
        logger.warning("proc: процесс %s не завершился после SIGKILL", proc.pid)
    except ProcessLookupError:
        pass


async def run_cmd(
    args: typing.Sequence[str] | str,
    *,
    timeout: float,
    use_group: bool = True,
    env: typing.Optional[typing.Mapping[str, str]] = None,
    cwd: typing.Optional[str] = None,
    shell: bool = False,
    stdin_devnull: bool = True,
) -> ProcResult:
    started_via_shell = shell or isinstance(args, str)
    printable = args if isinstance(args, str) else " ".join(map(str, args))

    kwargs: dict[str, typing.Any] = {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,


        "stdin": asyncio.subprocess.DEVNULL if stdin_devnull else None,
    }
    if env is not None:
        kwargs["env"] = dict(env)
    if cwd is not None:
        kwargs["cwd"] = cwd
    if use_group:


        kwargs["start_new_session"] = True

    try:
        if started_via_shell:
            proc = await asyncio.create_subprocess_shell(printable, **kwargs)
        else:
            proc = await asyncio.create_subprocess_exec(*[str(a) for a in args], **kwargs)
    except Exception as exc:
        logger.warning("proc: не удалось запустить %r — %s", printable[:120], exc)
        return -1, b"", str(exc).encode(errors="replace")

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, TimeoutError):
        logger.warning(
            "proc: таймаут %.0fс — убиваю %r (pid=%s)", timeout, printable[:120], proc.pid
        )
        await kill_process_tree(proc, use_group=use_group)
        return -int(signal.SIGKILL), b"", f"timeout after {timeout:.0f}s".encode()
    except asyncio.CancelledError:


        await kill_process_tree(proc, use_group=use_group)
        raise

    rc = proc.returncode if proc.returncode is not None else -1
    if rc != 0:
        logger.debug("proc: %r → rc=%s", printable[:120], rc)
    return rc, stdout or b"", stderr or b""
