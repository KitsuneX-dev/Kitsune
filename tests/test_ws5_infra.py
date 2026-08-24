from __future__ import annotations
import importlib
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_ENV_KEYS = ("KITSUNE_DATA_DIR", "KITSUNE_CONFIG", "DOCKER")


def _reload_paths(**env: str):
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    os.environ.update(env)
    sys.modules.pop("kitsune.paths", None)
    import kitsune.paths as paths
    return importlib.reload(paths)


class PathsDataDirTests(unittest.TestCase):

    def setUp(self) -> None:
        self._saved = {key: os.environ.get(key) for key in _ENV_KEYS}

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        sys.modules.pop("kitsune.paths", None)
        import kitsune.paths as paths
        importlib.reload(paths)

    def test_host_default_is_home_kitsune(self) -> None:
        paths = _reload_paths()
        if Path("/.dockerenv").exists():
            self.skipTest("тест выполняется внутри контейнера")
        self.assertEqual(paths.data_dir(), Path.home() / ".kitsune")

    def test_docker_env_gives_data_volume(self) -> None:
        paths = _reload_paths(DOCKER="1")
        self.assertEqual(paths.data_dir(), Path("/data"))

    def test_explicit_override_wins_over_docker(self) -> None:
        paths = _reload_paths(DOCKER="1", KITSUNE_DATA_DIR="/srv/kitsune-data")
        self.assertEqual(paths.data_dir(), Path("/srv/kitsune-data"))

    def test_docker_falsy_value_is_ignored(self) -> None:
        paths = _reload_paths(DOCKER="0")
        if Path("/.dockerenv").exists():
            self.skipTest("тест выполняется внутри контейнера")
        self.assertEqual(paths.data_dir(), Path.home() / ".kitsune")

    def test_config_path_follows_data_dir_in_docker(self) -> None:
        paths = _reload_paths(DOCKER="1")
        self.assertEqual(paths.config_path(), Path("/data/config.toml"))
        self.assertEqual(paths.config_path(Path("/data")), Path("/data/config.toml"))

    def test_config_env_override_wins(self) -> None:
        paths = _reload_paths(DOCKER="1", KITSUNE_CONFIG="/etc/kitsune/config.toml")
        self.assertEqual(paths.config_path(), Path("/etc/kitsune/config.toml"))

    def test_docker_primary_is_not_secondary(self) -> None:
        paths = _reload_paths(DOCKER="1", KITSUNE_DATA_DIR="/data")
        self.assertFalse(paths.is_secondary())

    def test_docker_account_dir_is_secondary(self) -> None:
        paths = _reload_paths(DOCKER="1", KITSUNE_DATA_DIR="/data/accounts/second")
        self.assertTrue(paths.is_secondary())

    def test_host_account_dir_is_secondary(self) -> None:
        target = Path.home() / ".kitsune" / "accounts" / "second"
        paths = _reload_paths(KITSUNE_DATA_DIR=str(target))
        self.assertTrue(paths.is_secondary())

    def test_host_default_override_is_not_secondary(self) -> None:
        paths = _reload_paths(KITSUNE_DATA_DIR=str(Path.home() / ".kitsune"))
        if Path("/.dockerenv").exists():
            self.skipTest("тест выполняется внутри контейнера")
        self.assertFalse(paths.is_secondary())

    def test_main_base_dir_matches_paths(self) -> None:
        paths = _reload_paths(DOCKER="1")
        self.assertEqual(paths.DOCKER_DATA_DIR, "/data")
        self.assertTrue(paths.in_docker())


class VersionSyncTests(unittest.TestCase):

    def test_version_is_144(self) -> None:
        from kitsune.version import __version__, __version_str__
        self.assertEqual(__version__, (1, 4, 4))
        self.assertEqual(__version_str__, "1.4.4")

    def test_pyproject_declares_version_dynamic(self) -> None:
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        data = self._parse_toml(text)
        project = data["project"]
        self.assertIn("version", project.get("dynamic", []))
        self.assertNotIn("version", project)

    def test_pyproject_dynamic_points_to_version_module(self) -> None:
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        data = self._parse_toml(text)
        dynamic = data["tool"]["setuptools"]["dynamic"]
        self.assertEqual(dynamic["version"]["attr"], "kitsune.version.__version__")

    def test_resolved_build_version_matches_module(self) -> None:
        from setuptools.config.pyprojecttoml import read_configuration
        from kitsune.version import __version_str__
        cfg = read_configuration(str(REPO_ROOT / "pyproject.toml"))
        self.assertEqual(cfg["project"]["version"], __version_str__)

    @staticmethod
    def _parse_toml(text: str) -> dict:
        try:
            import tomllib
            return tomllib.loads(text)
        except ImportError:
            import toml
            return toml.loads(text)


class DockerAssetsTests(unittest.TestCase):

    def setUp(self) -> None:
        self.dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    def test_multi_stage_build(self) -> None:
        self.assertIn("AS builder", self.dockerfile)
        self.assertIn("AS runtime", self.dockerfile)
        self.assertIn("COPY --from=builder", self.dockerfile)

    def test_no_masked_pip_failure(self) -> None:
        payload = [
            line for line in self.dockerfile.splitlines()
            if not line.lstrip().startswith("#")
        ]
        self.assertNotIn("|| true", "\n".join(payload))

    def test_unprivileged_user(self) -> None:
        self.assertIn("useradd -u 1000", self.dockerfile)
        self.assertIn("USER kitsune", self.dockerfile)

    def test_data_dir_env_and_volume(self) -> None:
        self.assertIn("KITSUNE_DATA_DIR=/data", self.dockerfile)
        self.assertIn('VOLUME ["/data"]', self.dockerfile)
        self.assertIn("chown -R kitsune:kitsune /data", self.dockerfile)

    def test_healthcheck_uses_health_endpoint(self) -> None:
        self.assertIn("HEALTHCHECK", self.dockerfile)
        self.assertIn("tools/healthcheck.py", self.dockerfile)
        script = (REPO_ROOT / "tools" / "healthcheck.py").read_text(encoding="utf-8")
        self.assertIn("/health", script)

    def test_dockerignore_covers_sensitive_and_bulky(self) -> None:
        text = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
        lines = {line.strip() for line in text.splitlines()}
        for entry in (
            ".git", "tests/", "*.md", "banner.gif", "__pycache__",
            ".venv", "config.toml", ".mypy_cache", ".pytest_cache",
        ):
            self.assertIn(entry, lines, f"{entry} отсутствует в .dockerignore")
        self.assertTrue(any(item.startswith("*.session") for item in lines))

    def test_compose_has_volume_env_and_restart(self) -> None:
        import yaml
        data = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        service = data["services"]["kitsune"]
        self.assertEqual(service["restart"], "unless-stopped")
        self.assertIn("kitsune-data:/data", service["volumes"])
        self.assertEqual(service["environment"]["KITSUNE_DATA_DIR"], "/data")
        self.assertEqual(service["environment"]["DOCKER"], "1")
        self.assertIn("kitsune-data", data["volumes"])


class CiWorkflowTests(unittest.TestCase):

    def setUp(self) -> None:
        import yaml
        self.data = yaml.safe_load(
            (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        )
        self.jobs = self.data["jobs"]

    def test_separate_jobs(self) -> None:
        for job in ("lint", "typecheck", "test", "docker", "missing-await"):
            self.assertIn(job, self.jobs, f"job {job} отсутствует")

    def test_lint_does_not_block_tests(self) -> None:
        self.assertNotIn("needs", self.jobs["test"])

    def test_matrix_and_fail_fast(self) -> None:
        strategy = self.jobs["test"]["strategy"]
        self.assertEqual(strategy["matrix"]["python-version"], ["3.12", "3.13"])
        self.assertFalse(strategy["fail-fast"])

    def test_setup_python_uses_pip_cache(self) -> None:
        cached = 0
        for job in self.jobs.values():
            for step in job.get("steps", []):
                uses = step.get("uses", "")
                if uses.startswith("actions/setup-python"):
                    self.assertEqual(step["with"].get("cache"), "pip")
                    cached += 1
        self.assertGreaterEqual(cached, 4)

    def test_missing_await_job_runs_tool(self) -> None:
        runs = " ".join(
            str(step.get("run", "")) for step in self.jobs["missing-await"]["steps"]
        )
        self.assertIn("tools/check_missing_await.py", runs)


if __name__ == "__main__":
    unittest.main()
