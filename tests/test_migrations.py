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
        "kitsune/secure/__init__.py",
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

    pycache = tmp_path / "kitsune/secure/__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "__init__.cpython-312.pyc").write_bytes(b"stale")

    removed = cleanup_legacy_143_layout(tmp_path)

    assert {path.relative_to(tmp_path).as_posix() for path in removed} == set(obsolete)
    assert all(not (tmp_path / relative).exists() for relative in obsolete)
    assert not pycache.exists()
    assert (tmp_path / "kitsune/secure/local_extension.py").exists()
    assert all((tmp_path / relative).read_text(encoding="utf-8") == "keep" for relative in preserved)
    assert cleanup_legacy_143_layout(tmp_path) == ()


def test_cleanup_removes_empty_legacy_secure_package(tmp_path: Path) -> None:
    secure_dir = tmp_path / "kitsune/secure"
    secure_dir.mkdir(parents=True)
    (secure_dir / "__init__.py").write_text("old", encoding="utf-8")

    cleanup_legacy_143_layout(tmp_path)

    assert not secure_dir.exists()
