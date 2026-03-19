"""Kitsune version info"""

# © Yushi (@Mikasu32), 2024-2026
# Kitsune Userbot
# License: AGPLv3

from __future__ import annotations

import contextlib
import os

__version__ = (1, 0, 0)
__version_str__ = ".".join(map(str, __version__))

branch: str = "main"

with contextlib.suppress(Exception):
    import git

    _repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    branch = git.Repo(path=_repo_path).active_branch.name
