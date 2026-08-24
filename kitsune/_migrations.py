from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Files that existed in 1.4.3 but were deliberately replaced or removed in 1.4.4.
# Keep this list explicit: an updater must never delete arbitrary untracked files,
# because user modules and local configuration may live beside the source tree.
_LEGACY_143_PATHS = (
    "kitsune/core/loader.py",
    "kitsune/inline/core.py",
    "kitsune/modules/backup.py",
    "kitsune/secure/customtl.py",
    "kitsune/secure/patcher.py",
    "kitsune/utils.py",
    "kitsune/utils_additions.py",
)


def cleanup_legacy_143_layout(repo_root: Path | str) -> tuple[Path, ...]:
    """Remove only known-obsolete 1.4.3 source files from an overlaid install.

    The migration is idempotent and intentionally uses an allow-list instead of
    comparing the installation with Git: untracked user modules, sessions,
    configuration and databases must be preserved.
    """

    root = Path(repo_root).resolve()
    removed: list[Path] = []

    for relative in _LEGACY_143_PATHS:
        candidate = root / relative
        try:
            candidate.relative_to(root)
        except ValueError:  # pragma: no cover - fixed internal allow-list
            continue

        try:
            if candidate.is_file() or candidate.is_symlink():
                candidate.unlink()
                removed.append(candidate)
        except OSError as exc:
            logger.warning("migration: failed to remove legacy file %s: %s", candidate, exc)

    secure_dir = root / "kitsune" / "secure"
    try:
        if secure_dir.is_dir() and not any(secure_dir.iterdir()):
            secure_dir.rmdir()
    except OSError:
        pass

    if removed:
        logger.info(
            "migration: removed %d obsolete 1.4.3 file(s): %s",
            len(removed),
            ", ".join(path.relative_to(root).as_posix() for path in removed),
        )

    return tuple(removed)
