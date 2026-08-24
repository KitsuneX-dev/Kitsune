from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)




_LEGACY_143_PATHS = (
    "kitsune/core/loader.py",
    "kitsune/inline/core.py",
    "kitsune/modules/backup.py",
    "kitsune/secure/customtl.py",
    "kitsune/secure/patcher.py",
    "kitsune/secure/__init__.py",
    "kitsune/utils.py",
    "kitsune/utils_additions.py",
)


def cleanup_legacy_143_layout(repo_root: Path | str) -> tuple[Path, ...]:
    






    root = Path(repo_root).resolve()
    removed: list[Path] = []

    for relative in _LEGACY_143_PATHS:
        candidate = root / relative
        try:
            candidate.relative_to(root)
        except ValueError:  
            continue

        try:
            if candidate.is_file() or candidate.is_symlink():
                candidate.unlink()
                removed.append(candidate)
        except OSError as exc:
            logger.warning("migration: failed to remove legacy file %s: %s", candidate, exc)

    secure_dir = root / "kitsune" / "secure"
    try:
        pycache_dir = secure_dir / "__pycache__"
        if pycache_dir.is_dir():
            for cached_file in pycache_dir.iterdir():
                if cached_file.is_file() or cached_file.is_symlink():
                    cached_file.unlink()
            if not any(pycache_dir.iterdir()):
                pycache_dir.rmdir()
        if secure_dir.is_dir() and not any(secure_dir.iterdir()):
            secure_dir.rmdir()
    except OSError as exc:
        logger.warning("migration: failed to remove empty legacy secure package: %s", exc)

    if removed:
        logger.info(
            "migration: removed %d obsolete 1.4.3 file(s): %s",
            len(removed),
            ", ".join(path.relative_to(root).as_posix() for path in removed),
        )

    return tuple(removed)
