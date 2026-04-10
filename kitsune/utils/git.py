
from __future__ import annotations

import logging
import os
import typing
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_PATH = Path(__file__).parent.parent.parent

def get_repo_path() -> Path:
    return _REPO_PATH

def get_git_repo() -> typing.Any:
    try:
        import git
        return git.Repo(_REPO_PATH)
    except Exception:
        return None

def get_current_commit(short: bool = True) -> str | None:
    repo = get_git_repo()
    if repo is None:
        return None
    try:
        sha = repo.head.commit.hexsha
        return sha[:7] if short else sha
    except Exception:
        return None

def get_current_branch() -> str | None:
    repo = get_git_repo()
    if repo is None:
        return None
    try:
        return repo.active_branch.name
    except TypeError:
        return "HEAD (detached)"
    except Exception:
        return None

def get_remote_commit(branch: str | None = None) -> str | None:
    repo = get_git_repo()
    if repo is None:
        return None
    try:
        if branch is None:
            branch = get_current_branch() or "main"
        origin = repo.remote("origin")
        origin.fetch()
        ref = origin.refs[branch]
        return ref.commit.hexsha[:7]
    except Exception:
        return None

def has_updates() -> bool:
    local  = get_current_commit(short=False)
    remote = get_remote_commit()
    if not local or not remote:
        return False
    return not remote.startswith(local[:7])

def get_changelog(n: int = 5) -> list[dict]:
    repo = get_git_repo()
    if repo is None:
        return []
    try:
        commits = []
        for commit in list(repo.iter_commits(max_count=n)):
            commits.append({
                "sha":     commit.hexsha[:7],
                "message": commit.message.strip().split("\n")[0],
                "author":  commit.author.name,
                "date":    commit.authored_datetime.strftime("%Y-%m-%d %H:%M"),
            })
        return commits
    except Exception:
        logger.debug("get_changelog: ошибка", exc_info=True)
        return []
