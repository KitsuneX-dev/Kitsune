from __future__ import annotations

import contextlib
import os

__version__ = (1, 2, 7)
__version_str__ = ".".join(map(str, __version__))

branch: str = "main"

with contextlib.suppress(Exception):
    import git

    _repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    branch = git.Repo(path=_repo_path).active_branch.name
