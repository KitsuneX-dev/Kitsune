from __future__ import annotations

import json
import pathlib
import sys

import pytest

_TOOLS = pathlib.Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))


def _reload_paths(monkeypatch, env: dict[str, str]):
    import importlib

    for key in ("DOCKER", "KITSUNE_DATA_DIR", "KITSUNE_CONFIG"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import kitsune.paths as paths

    return importlib.reload(paths)


class TestDataDirDb:

    def test_db_path_follows_data_dir(self, monkeypatch, tmp_path):
        paths = _reload_paths(monkeypatch, {"KITSUNE_DATA_DIR": str(tmp_path / "vol")})
        assert paths.data_dir() == tmp_path / "vol"

    def test_db_path_docker_volume(self, monkeypatch, tmp_path):
        paths = _reload_paths(
            monkeypatch, {"DOCKER": "1", "KITSUNE_DATA_DIR": str(tmp_path / "d")}
        )
        assert paths.data_dir() == tmp_path / "d"

    def test_db_path_docker_default(self, monkeypatch):
        paths = _reload_paths(monkeypatch, {"DOCKER": "1"})
        assert paths.data_dir() == pathlib.Path("/data")

    def test_legacy_db_migrated(self, tmp_path):
        from kitsune.database.manager import _migrate_legacy_db

        legacy_dir = tmp_path / "code"
        legacy_dir.mkdir()
        new_dir = tmp_path / "data"
        new_dir.mkdir()
        legacy = legacy_dir / "kitsune-1.db"
        legacy.write_bytes(b"payload")
        (legacy_dir / "kitsune-1.db-wal").write_bytes(b"wal")

        target = new_dir / "kitsune-1.db"
        _migrate_legacy_db(legacy_dir, target)

        assert target.read_bytes() == b"payload"
        assert (new_dir / "kitsune-1.db-wal").read_bytes() == b"wal"
        assert not legacy.exists()

    def test_migration_does_not_overwrite_existing(self, tmp_path):
        from kitsune.database.manager import _migrate_legacy_db

        legacy_dir = tmp_path / "code"
        legacy_dir.mkdir()
        new_dir = tmp_path / "data"
        new_dir.mkdir()
        (legacy_dir / "kitsune-1.db").write_bytes(b"old")
        target = new_dir / "kitsune-1.db"
        target.write_bytes(b"current")

        _migrate_legacy_db(legacy_dir, target)

        assert target.read_bytes() == b"current"
        assert (legacy_dir / "kitsune-1.db").exists()


class TestEffectiveConfigPath:

    def test_prefers_main_config_path(self, monkeypatch, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text("prefix = '.'\n", encoding="utf-8")

        import kitsune.main as kmain
        import kitsune.paths as paths

        monkeypatch.setattr(kmain, "CONFIG_PATH", cfg)
        assert paths.effective_config_path() == cfg

    def test_falls_back_when_main_unavailable(self, monkeypatch, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text("prefix = '.'\n", encoding="utf-8")

        import kitsune.paths as paths

        monkeypatch.setenv("KITSUNE_CONFIG", str(cfg))
        monkeypatch.setitem(sys.modules, "kitsune.main", None)
        assert paths.effective_config_path() == cfg

    def test_consumers_use_single_source(self):
        import inspect

        from kitsune.database.manager import DatabaseManager
        from kitsune.modules.notifier.bot_setup import BotSetup

        assert "effective_config_path" in inspect.getsource(DatabaseManager.init)
        assert "effective_config_path" in inspect.getsource(
            BotSetup.load_token_from_config
        )
        assert "effective_config_path" in inspect.getsource(
            BotSetup.save_token_to_config
        )
        settings_src = pathlib.Path(
            inspect.getsourcefile(BotSetup)
        ).parent.parent.joinpath("settings.py").read_text(encoding="utf-8")
        assert "effective_config_path" in settings_src
        assert 'parent.parent.parent / "config.toml"' not in settings_src


class TestLowPowerIsMobile:

    def test_config_low_power_enables_mobile(self, monkeypatch, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text("low_power = true\n", encoding="utf-8")
        monkeypatch.delenv("KITSUNE_LOW_POWER", raising=False)
        monkeypatch.setenv("KITSUNE_CONFIG", str(cfg))

        import kitsune.low_power as low_power
        import kitsune.utils.platform as pl

        import kitsune.main as kmain

        monkeypatch.setattr(kmain, "CONFIG_PATH", cfg)
        low_power.reset_cache()
        monkeypatch.setattr(pl, "_is_android_kernel", lambda: False)
        monkeypatch.setattr(pl, "is_termux", lambda: False)
        monkeypatch.setattr(pl, "is_userland", lambda: False)
        try:
            assert pl.is_mobile() is True
        finally:
            low_power.reset_cache()

    def test_no_sources_means_not_mobile(self, monkeypatch, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text("low_power = false\n", encoding="utf-8")
        monkeypatch.delenv("KITSUNE_LOW_POWER", raising=False)
        monkeypatch.setenv("KITSUNE_CONFIG", str(cfg))

        import kitsune.low_power as low_power
        import kitsune.utils.platform as pl

        import kitsune.main as kmain

        monkeypatch.setattr(kmain, "CONFIG_PATH", cfg)
        low_power.reset_cache()
        monkeypatch.setattr(pl, "_is_android_kernel", lambda: False)
        monkeypatch.setattr(pl, "is_termux", lambda: False)
        monkeypatch.setattr(pl, "is_userland", lambda: False)
        try:
            assert pl.is_mobile() is False
        finally:
            low_power.reset_cache()

    def test_truthy_sets_are_in_sync(self):
        import healthcheck

        from kitsune.low_power import _TRUTHY as core_truthy

        assert healthcheck._TRUTHY == core_truthy


class TestProotRouting:

    @pytest.mark.parametrize(
        ("proot", "android", "expected"),
        [
            (False, False, ("WAL", 64 << 20)),
            (True, False, ("WAL", 0)),
            (True, True, ("WAL", 0)),
            (False, True, ("DELETE", 0)),
        ],
    )
    def test_journal_settings(self, monkeypatch, proot, android, expected):
        import kitsune.database.manager as mgr

        monkeypatch.setattr(mgr, "_UNDER_PROOT", proot)
        monkeypatch.setattr(mgr, "_IS_ANDROID", android)
        assert mgr._journal_settings() == expected

    def test_detect_proot_by_tracer_pid(self, monkeypatch):
        import kitsune.utils.platform as pl

        monkeypatch.setattr(pl, "is_userland", lambda: False)
        monkeypatch.setattr(pl, "_is_android_kernel", lambda: False)
        monkeypatch.setattr(pl, "_tracer_pid", lambda: 0)
        assert pl._detect_proot() is False
        monkeypatch.setattr(pl, "_tracer_pid", lambda: 4242)
        assert pl._detect_proot() is True

    def test_detect_proot_userland_non_android_kernel(self, monkeypatch):
        import kitsune.utils.platform as pl

        monkeypatch.setattr(pl, "_tracer_pid", lambda: 0)
        monkeypatch.setattr(pl, "is_userland", lambda: True)
        monkeypatch.setattr(pl, "_is_android_kernel", lambda: False)
        assert pl._detect_proot() is True
        monkeypatch.setattr(pl, "_is_android_kernel", lambda: True)
        assert pl._detect_proot() is False

    def test_pragmas_applied(self, monkeypatch, tmp_path):
        import kitsune.database.manager as mgr

        monkeypatch.setattr(mgr, "_UNDER_PROOT", True)
        monkeypatch.setattr(mgr, "_IS_ANDROID", False)
        backend = mgr.SQLiteBackend(tmp_path / "t.db")
        conn = backend._get_conn()
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert conn.execute("PRAGMA mmap_size").fetchone()[0] == 0
        finally:
            backend.close()


class TestHealthcheckLiveness:

    def test_telegram_down_is_tolerated(self):
        import healthcheck

        payload = {
            "ok": False,
            "sqlite": {"alive": True, "active": True},
            "telegram": {"alive": False, "connected": False},
        }
        assert healthcheck._tolerable_degradation(json.dumps(payload).encode()) is True

    def test_dead_sqlite_triggers_restart(self):
        import healthcheck

        payload = {
            "ok": False,
            "sqlite": {"alive": False, "active": True, "error": "disk I/O"},
            "telegram": {"alive": True, "connected": True},
        }
        assert healthcheck._tolerable_degradation(json.dumps(payload).encode()) is False

    def test_inactive_sqlite_with_redis_primary_is_tolerated(self):
        import healthcheck

        payload = {
            "ok": False,
            "sqlite": {"alive": False, "active": False},
            "telegram": {"alive": False},
        }
        assert healthcheck._tolerable_degradation(json.dumps(payload).encode()) is True

    def test_unparsable_body_triggers_restart(self):
        import healthcheck

        assert healthcheck._tolerable_degradation(b"<html>502</html>") is False


class TestCryptoConfigPath:
    def test_derive_key_uses_effective_config_path(self, monkeypatch, tmp_path):
        import base64
        import hashlib

        cfg = tmp_path / "elsewhere" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(
            'api_id = 123456\napi_hash = "deadbeefdeadbeefdeadbeefdeadbeef"\n',
            encoding="utf-8",
        )
        monkeypatch.delenv("KITSUNE_DATA_DIR", raising=False)
        monkeypatch.delenv("DOCKER", raising=False)
        monkeypatch.setenv("KITSUNE_CONFIG", str(cfg))
        import kitsune.crypto as crypto
        import kitsune.main as kmain
        import kitsune.paths as paths

        monkeypatch.setattr(kmain, "CONFIG_PATH", cfg)
        monkeypatch.setattr(paths, "in_docker", lambda: False)
        monkeypatch.setattr(paths, "is_secondary", lambda: False)
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(
                b"123456:deadbeefdeadbeefdeadbeefdeadbeef:kitsune-backup-key"
            ).digest()
        )
        assert crypto._derive_key_from_credentials() == expected

    def test_crypto_no_longer_builds_path_from_file(self):
        import inspect
        import kitsune.crypto as crypto

        src = inspect.getsource(crypto._derive_key_from_credentials)
        assert "effective_config_path" in src
        assert 'Path(__file__).parent.parent / "config.toml"' not in src
        assert 'Path.home() / "Kitsune" / "config.toml"' in src
