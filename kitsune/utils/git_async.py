
from __future__ import annotations

import asyncio
import logging
import os
import typing

from . import run_sync

logger = logging.getLogger(__name__)

__all__ = [
    "GitTimeout",
    "ensure_git_env",
    "open_repo",
    "fetch",
    "git_log",
    "git_show",
    "git_reset",
    "git_rm",
    "iter_commits",
    "get_remote_commit",
    "active_branch",
]


DEFAULT_FETCH_TIMEOUT = 60.0
DEFAULT_LOCAL_TIMEOUT = 30.0


_LOW_SPEED_LIMIT = "1000"
_LOW_SPEED_TIME = "20"

_env_ready = False


def ensure_git_env() -> None:
    global _env_ready
    if _env_ready:
        return
    os.environ.setdefault("GIT_HTTP_LOW_SPEED_LIMIT", _LOW_SPEED_LIMIT)
    os.environ.setdefault("GIT_HTTP_LOW_SPEED_TIME", _LOW_SPEED_TIME)


    os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")
    os.environ.setdefault("GIT_ASKPASS", "")
    _env_ready = True


class GitTimeout(Exception):
    pass


async def _call(
    func: typing.Callable[..., typing.Any],
    *args: typing.Any,
    timeout: float,
    what: str,
    **kwargs: typing.Any,
) -> typing.Any:
    ensure_git_env()
    try:
        return await asyncio.wait_for(run_sync(func, *args, **kwargs), timeout=timeout)
    except (asyncio.TimeoutError, TimeoutError) as exc:


        logger.warning("git_async: %s не уложился в %.0fс", what, timeout)
        raise GitTimeout(f"{what}: timeout after {timeout:.0f}s") from exc


async def open_repo(path: str | os.PathLike[str], *, timeout: float = DEFAULT_LOCAL_TIMEOUT):

    def _open():
        import git

        return git.Repo(path)

    return await _call(_open, timeout=timeout, what=f"open_repo({path})")


async def active_branch(repo: typing.Any, default: str = "main", *, timeout: float = DEFAULT_LOCAL_TIMEOUT) -> str:

    def _branch() -> str:
        try:
            return str(repo.active_branch.name)
        except TypeError:
            return default

    try:
        return await _call(_branch, timeout=timeout, what="active_branch")
    except GitTimeout:
        return default


async def fetch(
    repo: typing.Any,
    remote: str | None = "origin",
    *,
    timeout: float = DEFAULT_FETCH_TIMEOUT,
) -> None:

    def _fetch_one(name: str) -> None:
        repo.remote(name).fetch()

    if remote is not None:
        await _call(_fetch_one, remote, timeout=timeout, what=f"fetch({remote})")
        return

    names = [r.name for r in repo.remotes]
    if not names:
        return
    per_remote = max(timeout / len(names), 5.0)
    for name in names:
        await _call(_fetch_one, name, timeout=per_remote, what=f"fetch({name})")


async def git_log(repo: typing.Any, *args: typing.Any, timeout: float = DEFAULT_LOCAL_TIMEOUT) -> str:
    def _log() -> str:
        return str(repo.git.log(*args))

    return await _call(_log, timeout=timeout, what="git log")


async def git_show(repo: typing.Any, ref: str, *, timeout: float = DEFAULT_LOCAL_TIMEOUT) -> str:
    def _show() -> str:
        return str(repo.git.show(ref))

    return await _call(_show, timeout=timeout, what=f"git show {ref}")


async def git_reset(repo: typing.Any, *args: typing.Any, timeout: float = DEFAULT_FETCH_TIMEOUT) -> str:

    def _reset() -> str:
        return str(repo.git.reset(*args))

    return await _call(_reset, timeout=timeout, what="git reset")


async def git_rm(repo: typing.Any, *args: typing.Any, timeout: float = DEFAULT_LOCAL_TIMEOUT) -> str:
    def _rm() -> str:
        return str(repo.git.rm(*args))

    return await _call(_rm, timeout=timeout, what="git rm")


async def iter_commits(
    repo: typing.Any,
    *args: typing.Any,
    timeout: float = DEFAULT_LOCAL_TIMEOUT,
    **kwargs: typing.Any,
) -> list:

    def _iter() -> list:
        return list(repo.iter_commits(*args, **kwargs))

    return await _call(_iter, timeout=timeout, what="iter_commits")


async def get_remote_commit(
    branch: str | None = None,
    *,
    timeout: float = DEFAULT_FETCH_TIMEOUT,
) -> str | None:
    from .git import get_remote_commit as _sync_get_remote_commit

    try:
        return await _call(
            _sync_get_remote_commit, branch, timeout=timeout, what="get_remote_commit"
        )
    except GitTimeout:


        return None


async def has_updates(*, timeout: float = DEFAULT_FETCH_TIMEOUT) -> bool:
    from .git import get_current_commit

    local = get_current_commit(short=False)
    remote = await get_remote_commit(timeout=timeout)
    if not local or not remote:
        return False
    return not remote.startswith(local[:7])
