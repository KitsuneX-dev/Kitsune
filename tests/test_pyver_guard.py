from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from kitsune.utils import pyver
from kitsune.utils import update_guard


class TestVersionParsing(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(pyver.parse_version("3.12"), (3, 12))
        self.assertEqual(pyver.parse_version("Python 3.13.1"), (3, 13))
        self.assertEqual(pyver.parse_version(b"3.9\n"), (3, 9))
        self.assertEqual(pyver.parse_version((3, 14)), (3, 14))
        self.assertIsNone(pyver.parse_version("abc"))
        self.assertIsNone(pyver.parse_version(None))

    def test_parse_requires_python(self):
        self.assertEqual(pyver.parse_requires_python(">=3.12"), (3, 12))
        self.assertEqual(pyver.parse_requires_python(">=3.10,<4.0"), (3, 10))
        self.assertEqual(pyver.parse_requires_python(">3.11"), (3, 12))
        self.assertEqual(pyver.parse_requires_python("==3.13"), (3, 13))
        self.assertEqual(pyver.parse_requires_python("~=3.12"), (3, 12))
        self.assertIsNone(pyver.parse_requires_python("<4.0"))
        self.assertIsNone(pyver.parse_requires_python(""))

    def test_read_requires_python_real_pyproject(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.assertEqual(pyver.read_requires_python(root), (3, 12))

    def test_version_ok(self):
        self.assertTrue(pyver.version_ok((3, 12), (3, 13)))
        self.assertTrue(pyver.version_ok((3, 12), (3, 12)))
        self.assertFalse(pyver.version_ok((3, 12), (3, 10)))

    def test_format_version(self):
        self.assertEqual(pyver.format_version((3, 12)), "3.12")
        self.assertEqual(pyver.format_version(None), "?")

    def test_candidate_names(self):
        names = pyver.candidate_names((3, 12), span=2)
        self.assertEqual(names, ["python3.14", "python3.13", "python3.12", "python3", "python"])

    def test_excluded_paths_only_executable(self):
        skip = pyver.excluded_paths("/opt/py310/bin/python3.10")
        self.assertIn("/opt/py310/bin/python3.10", skip)
        self.assertNotIn("/opt/py310/bin", skip)
        self.assertNotIn("/opt/py310", skip)


class TestInterpreterSelection(unittest.TestCase):
    def test_prefers_venv_capable_over_newer(self):
        found = [
            {"path": "/usr/bin/python3.14", "version": (3, 14), "can_venv": False},
            {"path": "/usr/bin/python3.12", "version": (3, 12), "can_venv": True},
        ]
        best = pyver.select_interpreter(found, (3, 12))
        self.assertEqual(best["path"], "/usr/bin/python3.12")

    def test_newest_among_venv_capable(self):
        found = [
            {"path": "/usr/bin/python3.12", "version": (3, 12), "can_venv": True},
            {"path": "/usr/bin/python3.13", "version": (3, 13), "can_venv": True},
        ]
        best = pyver.select_interpreter(found, (3, 12))
        self.assertEqual(best["path"], "/usr/bin/python3.13")

    def test_fallback_without_venv(self):
        found = [{"path": "/usr/bin/python3.13", "version": (3, 13), "can_venv": False}]
        best = pyver.select_interpreter(found, (3, 12))
        self.assertEqual(best["path"], "/usr/bin/python3.13")

    def test_rejects_too_old(self):
        found = [{"path": "/usr/bin/python3.10", "version": (3, 10), "can_venv": True}]
        self.assertIsNone(pyver.select_interpreter(found, (3, 12)))

    def test_empty(self):
        self.assertIsNone(pyver.select_interpreter([], (3, 12)))


class TestFindInterpreters(unittest.TestCase):
    def setUp(self):
        self.table = {
            "python3.14": ("/usr/bin/python3.14", {"version": "3.14", "can_venv": False}),
            "python3.12": ("/usr/bin/python3.12", {"version": "3.12", "can_venv": True}),
            "python3.10": ("/usr/bin/python3.10", {"version": "3.10", "can_venv": True}),
            "python3": ("/usr/bin/python3.10", {"version": "3.10", "can_venv": True}),
            "python": ("/usr/bin/python3.10", {"version": "3.10", "can_venv": True}),
        }

    def _which(self, name):
        entry = self.table.get(name)
        return entry[0] if entry else None

    def _probe(self, path):
        for _name, (candidate, info) in self.table.items():
            if candidate == path:
                return info
        return None

    def test_filters_and_dedups(self):
        found = pyver.find_interpreters(
            (3, 12),
            probe=self._probe,
            which=self._which,
            names=["python3.14", "python3.12", "python3.10", "python3", "python"],
            exclude=set(),
        )
        paths = [i["path"] for i in found]
        self.assertEqual(paths, ["/usr/bin/python3.14", "/usr/bin/python3.12"])

    def test_excludes_current_executable_only(self):
        found = pyver.find_interpreters(
            (3, 12),
            probe=self._probe,
            which=self._which,
            names=["python3.14", "python3.12"],
            exclude={"/usr/bin/python3.14"},
        )
        self.assertEqual([i["path"] for i in found], ["/usr/bin/python3.12"])

    def test_selection_end_to_end(self):
        found = pyver.find_interpreters(
            (3, 12),
            probe=self._probe,
            which=self._which,
            names=["python3.14", "python3.12"],
            exclude=set(),
        )
        best = pyver.select_interpreter(found, (3, 12))
        self.assertEqual(best["path"], "/usr/bin/python3.12")
        self.assertTrue(best["can_venv"])


class FakeDB:
    def __init__(self):
        self.data = {}
        self.deleted = []
        self.saves = 0

    def get(self, owner, key, default=None):
        return self.data.get((owner, key), default)

    async def set(self, owner, key, value):
        self.data[(owner, key)] = value
        return True

    async def delete(self, owner, key):
        self.deleted.append((owner, key))
        self.data.pop((owner, key), None)
        return True

    async def force_save(self):
        self.saves += 1
        return True


class TestUpdateGuard(unittest.TestCase):
    def test_guarded_update_success(self):
        db = FakeDB()
        sent = []

        async def body():
            return "done"

        result = asyncio.run(
            update_guard.guarded_update(
                body,
                db=db,
                owners=("kitsune.notifier",),
                notify=lambda t: sent.append(t),
            )
        )
        self.assertTrue(result)
        self.assertEqual(sent, [])
        self.assertEqual(db.deleted, [])

    def test_guarded_update_failure_clears_state_and_notifies(self):
        db = FakeDB()
        db.data[("kitsune.notifier", "update_msg_id")] = 42
        sent = []

        async def body():
            raise RuntimeError("Could not find a version that satisfies the requirement cryptg>=0.6.0")

        result = asyncio.run(
            update_guard.guarded_update(
                body,
                db=db,
                owners=("kitsune.notifier",),
                notify=lambda t: sent.append(t),
            )
        )
        self.assertFalse(result)
        self.assertEqual(len(sent), 1)
        self.assertIn("Обновление не удалось", sent[0])
        self.assertIn("cryptg", sent[0])
        self.assertIn("версия Python слишком старая", sent[0])
        self.assertIn(("kitsune.notifier", "update_msg_id"), db.deleted)
        self.assertIn(("kitsune.notifier", "update_start_time"), db.deleted)
        self.assertEqual(db.data.get(("kitsune.notifier", "last_update_error")),
                         "Could not find a version that satisfies the requirement cryptg>=0.6.0")

    def test_guarded_update_notify_failure_is_swallowed(self):
        db = FakeDB()

        async def body():
            raise ValueError("boom")

        async def bad_notify(_text):
            raise OSError("no network")

        result = asyncio.run(
            update_guard.guarded_update(
                body,
                db=db,
                owners=("kitsune.updater",),
                notify=bad_notify,
            )
        )
        self.assertFalse(result)
        self.assertIn(("kitsune.updater", "pending_update"), db.deleted)

    def test_cancelled_is_reraised(self):
        db = FakeDB()

        async def body():
            raise asyncio.CancelledError()

        async def runner():
            with self.assertRaises(asyncio.CancelledError):
                await update_guard.guarded_update(body, db=db, owners=("kitsune.updater",))

        asyncio.run(runner())

    def test_spawn_guarded_reports_background_failure(self):
        db = FakeDB()
        sent = []

        async def body():
            raise RuntimeError("background fail")

        async def runner():
            task = update_guard.spawn_guarded(
                body(),
                db=db,
                owners=("kitsune.notifier",),
                notify=lambda t: sent.append(t),
            )
            with self.assertRaises(RuntimeError):
                await task
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        asyncio.run(runner())
        self.assertEqual(len(sent), 1)
        self.assertIn("background fail", sent[0])

    def test_format_update_error_truncates(self):
        text = update_guard.format_update_error(RuntimeError("x" * 1000))
        self.assertEqual(len(text), 600)
        self.assertEqual(update_guard.format_update_error(RuntimeError()), "RuntimeError")


class TestMessages(unittest.TestCase):
    def test_missing_python_message(self):
        text = pyver.missing_python_message((3, 12))
        self.assertIn("3.12", text)
        self.assertIn("apt install python3.12", text)

    def test_venv_python_path(self):
        self.assertTrue(pyver.venv_python("/opt/app/venv").endswith("python"))

    def test_default_requirements(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.assertTrue(pyver.default_requirements(root).endswith(".txt"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
