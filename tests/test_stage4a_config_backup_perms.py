
from __future__ import annotations

import os
import pathlib
import shutil
import stat
import tempfile

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _mode(path: str | os.PathLike[str]) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture()
def insecure_config(tmp_path: pathlib.Path) -> pathlib.Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text('api_hash = "SECRET"\nbot_token = "123:AAA"\n', encoding="utf-8")
    os.chmod(cfg, 0o644)
    return cfg


def test_copy2_leaks_source_permissions(insecure_config: pathlib.Path) -> None:
    fd, backup = tempfile.mkstemp(suffix=".toml", prefix="kitsune_cfg_")
    os.close(fd)
    try:
        assert _mode(backup) == 0o600, "mkstemp обязан давать 0600"
        shutil.copy2(insecure_config, backup)
        assert _mode(backup) == 0o644, (
            "если copy2 перестал переносить права, тест-страховку можно снять"
        )
    finally:
        os.unlink(backup)


def test_copyfile_keeps_mkstemp_permissions(insecure_config: pathlib.Path) -> None:
    fd, backup = tempfile.mkstemp(suffix=".toml", prefix="kitsune_cfg_")
    os.close(fd)
    try:
        shutil.copyfile(insecure_config, backup)
        assert _mode(backup) == 0o600, f"утечка прав временной копии: {oct(_mode(backup))}"
        assert (_mode(backup) & (stat.S_IRGRP | stat.S_IROTH)) == 0
    finally:
        os.unlink(backup)


def test_restore_returns_original_config_mode(insecure_config: pathlib.Path) -> None:
    config_mode = _mode(insecure_config)
    fd, backup = tempfile.mkstemp(suffix=".toml", prefix="kitsune_cfg_")
    os.close(fd)
    try:
        shutil.copyfile(insecure_config, backup)
        os.unlink(insecure_config)
        shutil.copyfile(backup, insecure_config)
        os.chmod(insecure_config, config_mode)
        assert _mode(insecure_config) == config_mode == 0o644
        assert insecure_config.read_text(encoding="utf-8").startswith('api_hash = "SECRET"')
    finally:
        os.unlink(backup)


def test_backup_dir_is_private(tmp_path: pathlib.Path) -> None:
    backup_dir = tmp_path / ".kitsune_update_backup"
    os.makedirs(backup_dir, mode=0o700, exist_ok=True)
    assert _mode(backup_dir) == 0o700, f"каталог бэкапа доступен другим: {oct(_mode(backup_dir))}"


def test_written_backup_is_narrowed_to_0600(insecure_config: pathlib.Path,
                                            tmp_path: pathlib.Path) -> None:
    backup_dir = tmp_path / ".kitsune_update_backup"
    os.makedirs(backup_dir, mode=0o700, exist_ok=True)
    backup = backup_dir / "config.toml"
    with open(insecure_config, "rb") as src, open(backup, "wb") as dst:
        dst.write(src.read())
    os.chmod(backup, 0o600)
    assert _mode(backup) == 0o600
    assert (_mode(backup) & (stat.S_IRGRP | stat.S_IROTH)) == 0


@pytest.mark.parametrize(
    "rel_path",
    ["kitsune/modules/updater.py", "kitsune/modules/notifier/update_checker.py"],
)
def test_no_copy2_on_config_backup_paths(rel_path: str) -> None:
    source = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in source.splitlines()
        if "copy2(" in line and not line.strip().startswith("#")
    ]
    assert not offenders, f"{rel_path}: copy2 переносит права на копию секретов — {offenders}"
