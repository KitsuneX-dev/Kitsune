from __future__ import annotations

from pathlib import Path

from kitsune._migrations import cleanup_legacy_143_layout


def test_cleanup_legacy_143_layout_is_safe_and_idempotent(tmp_path: Path) -> None:
    obsolete = (
        "kitsune/core/loader.py",
        "kitsune/inline/core.py",
        "kitsune/modules/backup.py",
        "kitsune/secure/customtl.py",
        "kitsune/secure/patcher.py",
        "kitsune/utils.py",
        "kitsune/utils_additions.py",
    )
    for relative in obsolete:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("old", encoding="utf-8")

    preserved = (
        "config.toml",
        "kitsune/modules/MyUserModule.py",
        "kitsune/secure/local_extension.py",
        "kitsune-123.db",
    )
    for relative in preserved:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("keep", encoding="utf-8")

    removed = cleanup_legacy_143_layout(tmp_path)

    assert {path.relative_to(tmp_path).as_posix() for path in removed} == set(obsolete)
    assert all(not (tmp_path / relative).exists() for relative in obsolete)
    assert all((tmp_path / relative).read_text(encoding="utf-8") == "keep" for relative in preserved)
    assert cleanup_legacy_143_layout(tmp_path) == ()
