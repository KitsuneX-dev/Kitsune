from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import importlib
import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


GOOD_MODULE = (
    "from kitsune.core.loader import KitsuneModule\n"
    "\n"
    "class GoodModule(KitsuneModule):\n"
    "    name = 'good'\n"
)

BAD_MODULE = (
    "import subprocess\n"
    "subprocess.Popen(['sh', '-c', 'echo pwned'])\n"
)


from conftest import FakeDB


@pytest.fixture()
def backup_env(tmp_path, monkeypatch):
    monkeypatch.setenv("KITSUNE_DATA_DIR", str(tmp_path))
    sys.modules.pop("kitsune.paths", None)
    import kitsune.paths as paths
    importlib.reload(paths)
    import kitsune.modules.backup as backup
    importlib.reload(backup)

    module = backup.BackupModule(MagicMock(), FakeDB())
    module.client._kitsune_loader = None
    yield backup, module, tmp_path

    sys.modules.pop("kitsune.paths", None)
    import kitsune.paths as paths_after
    importlib.reload(paths_after)
    importlib.reload(backup)


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, src in files.items():
            zf.writestr(name, src)
    return buf.getvalue()


async def test_malicious_module_goes_to_quarantine(backup_env):
    backup, module, tmp_path = backup_env
    payload = _make_zip({"evil.py": BAD_MODULE})

    count, _cfg = await module._restore_mods_from_zip(payload, "kitsune-test.backup")

    assert count == 0
    assert not (tmp_path / "modules" / "evil.py").exists()

    quarantined = list((tmp_path / "quarantine").glob("*evil.py"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == BAD_MODULE

    assert len(module._rejected) == 1
    rejected = module._rejected[0]
    assert rejected["file"] == "evil.py"
    assert rejected["source"] == "kitsune-test.backup"
    assert rejected["reason"]

    report = module._quarantine_report()
    assert "evil.py" in report
    assert "kitsune-test.backup" in report


async def test_broken_syntax_goes_to_quarantine(backup_env):
    backup, module, tmp_path = backup_env
    payload = _make_zip({"broken.py": "def oops(:\n"})

    count, _cfg = await module._restore_mods_from_zip(payload)

    assert count == 0
    assert not (tmp_path / "modules" / "broken.py").exists()
    assert list((tmp_path / "quarantine").glob("*broken.py"))


async def test_legit_module_is_restored_and_loaded(backup_env):
    backup, module, tmp_path = backup_env

    loaded: list[Path] = []

    class _Loader:
        async def load_from_file(self, path):
            loaded.append(Path(path))

    module.client._kitsune_loader = _Loader()
    payload = _make_zip({"good.py": GOOD_MODULE})

    count, _cfg = await module._restore_mods_from_zip(payload)

    assert count == 1
    dest = tmp_path / "modules" / "good.py"
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == GOOD_MODULE
    assert loaded == [dest]
    assert module._rejected == []
    assert module._quarantine_report() == ""


async def test_mixed_archive_partial_restore(backup_env):
    backup, module, tmp_path = backup_env
    payload = _make_zip({"good.py": GOOD_MODULE, "evil.py": BAD_MODULE})

    count, _cfg = await module._restore_mods_from_zip(payload, "mixed.zip")

    assert count == 1
    assert (tmp_path / "modules" / "good.py").exists()
    assert not (tmp_path / "modules" / "evil.py").exists()
    assert len(module._rejected) == 1


async def test_no_temp_dirs_left_behind(backup_env):
    import tempfile

    backup, module, tmp_path = backup_env
    tmp_root = Path(tempfile.gettempdir())
    before = set(tmp_root.glob("kitsune-restore-*"))

    await module._restore_mods_from_zip(
        _make_zip({"good.py": GOOD_MODULE, "evil.py": BAD_MODULE})
    )

    after = set(tmp_root.glob("kitsune-restore-*"))
    assert after == before


def test_quarantine_dir_permissions(backup_env):
    backup, module, tmp_path = backup_env
    qdir = backup._quarantine_dir()
    assert qdir.is_dir()
    assert oct(qdir.stat().st_mode & 0o777) == "0o700"
