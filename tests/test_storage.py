"""Persistence regressions, including real Windows file-sharing conflicts."""

import errno
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from server import genome, storage
from server.evolution import evaluate
from server.runtime import Runtime


def windows_error(code=5):
    error = PermissionError(errno.EACCES, "File is temporarily in use")
    error.winerror = code
    return error


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="bug-storage-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "best.meta.json"
        storage.atomic_json(self.path, {"old": True})

    def test_retries_windows_locks_without_removing_old_result(self):
        replace = os.replace
        attempts = []

        def locked(source, target):
            attempts.append(source)
            self.assertEqual(json.loads(self.path.read_text()), {"old": True})
            if len(attempts) <= 3:
                raise windows_error((5, 32, 33)[len(attempts) - 1])
            return replace(source, target)

        with (
            patch.object(storage.os, "replace", side_effect=locked),
            patch.object(storage.time, "sleep"),
        ):
            storage.atomic_json(self.path, {"name": "Жук", "new": True})
        self.assertEqual(len(attempts), 4)
        self.assertEqual(len(set(attempts)), 1)
        self.assertEqual(json.loads(self.path.read_text()), {"name": "Жук", "new": True})
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_retry_deadline_preserves_old_and_new_json(self):
        clock = [0.0]

        def advance(seconds):
            clock[0] += seconds

        with (
            patch.object(storage, "RETRY_SECONDS", 0.5),
            patch.object(storage.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(storage.time, "sleep", side_effect=advance),
            patch.object(storage.os, "replace", side_effect=windows_error()) as replace,
            self.assertLogs(level="ERROR"),
            self.assertRaises(PermissionError),
        ):
            storage.atomic_json(self.path, {"new": True})
        self.assertGreater(replace.call_count, 1)
        self.assertAlmostEqual(clock[0], 0.5)
        self.assertEqual(json.loads(self.path.read_text()), {"old": True})
        (temporary,) = self.root.glob("*.tmp")
        self.assertEqual(json.loads(temporary.read_text()), {"new": True})

    def test_non_lock_errors_fail_immediately(self):
        for error in (OSError(errno.ENOSPC, "Disk full"), PermissionError("Not a Windows lock")):
            with (
                self.subTest(error=error),
                patch.object(storage.os, "replace", side_effect=error) as replace,
                patch.object(storage.time, "sleep") as sleep,
                self.assertLogs(level="ERROR"),
                self.assertRaises(OSError),
            ):
                storage.atomic_json(self.path, {"new": True})
            self.assertEqual(replace.call_count, 1)
            sleep.assert_not_called()
            self.assertEqual(json.loads(self.path.read_text()), {"old": True})

    def test_invalid_json_does_not_change_saved_result(self):
        with self.assertRaises(ValueError):
            storage.atomic_json(self.path, {"invalid": float("nan")})
        self.assertEqual(json.loads(self.path.read_text()), {"old": True})
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_concurrent_writers_have_distinct_temporary_files(self):
        barrier = threading.Barrier(2)
        replace = os.replace
        sources, errors = [], []
        lock = threading.Lock()

        def synchronized(source, target):
            with lock:
                first_attempt = source not in sources
                if first_attempt:
                    sources.append(source)
            if first_attempt:
                barrier.wait(timeout=5)
            return replace(source, target)

        def write(value):
            try:
                storage.atomic_json(self.path, {"value": value})
            except Exception as exc:
                errors.append(exc)

        with patch.object(storage.os, "replace", side_effect=synchronized):
            threads = [threading.Thread(target=write, args=(i,)) for i in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=6)
        self.assertFalse(errors, errors)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(set(sources)), 2)
        self.assertIn(json.loads(self.path.read_text())["value"], (0, 1))

    def test_archive_deletion_retries_and_is_idempotent(self):
        unlink = Path.unlink
        calls = []

        def locked(path, **kwargs):
            calls.append(path)
            if len(calls) == 1:
                raise windows_error(32)
            return unlink(path, **kwargs)

        with patch.object(Path, "unlink", locked), patch.object(storage.time, "sleep"):
            storage.unlink_file(self.path)
            storage.unlink_file(self.path)
        self.assertEqual(len(calls), 3)
        self.assertFalse(self.path.exists())

    @unittest.skipUnless(os.name == "nt", "Requires real Windows sharing semantics")
    def test_real_windows_reader_lock_is_retried(self):
        self.check_real_reader_lock(lambda: storage.atomic_json(self.path, {"new": True}))
        self.assertEqual(json.loads(self.path.read_text()), {"new": True})

    @unittest.skipUnless(os.name == "nt", "Requires real Windows sharing semantics")
    def test_real_windows_delete_lock_is_retried(self):
        self.check_real_reader_lock(lambda: storage.unlink_file(self.path))
        self.assertFalse(self.path.exists())

    def check_real_reader_lock(self, action):
        reader = self.path.open("r")
        attempts = []
        attempted = threading.Event()
        retry = storage.retry_file_operation

        def observed(operation, *args, **kwargs):
            def call():
                try:
                    return operation(*args, **kwargs)
                except OSError as exc:
                    attempts.append(getattr(exc, "winerror", None))
                    attempted.set()
                    raise

            return retry(call)

        def release():
            attempted.wait(timeout=3)
            time.sleep(0.1)
            reader.close()

        thread = threading.Thread(target=release)
        thread.start()
        try:
            with patch.object(storage, "retry_file_operation", side_effect=observed):
                action()
        finally:
            thread.join(timeout=5)
            reader.close()
        self.assertTrue(attempts, "The test must encounter a real file-sharing failure")
        self.assertTrue(set(attempts) <= storage.WINDOWS_LOCK_ERRORS, attempts)

    def test_evolution_completes_with_save_and_archive_locks(self):
        project = Runtime().project()
        options = genome.settings(
            dict(
                mode="current",
                population=4,
                elite=1,
                generations=2,
                attempts=1,
                validation_attempts=1,
                duration=1,
                archive_size=1,
            )
        )
        replace, unlink = os.replace, Path.unlink
        failures = set()

        def locked_replace(source, target):
            key = ("replace", str(target))
            if target.name == "best.meta.json" and key not in failures:
                failures.add(key)
                raise windows_error()
            return replace(source, target)

        def locked_unlink(path, **kwargs):
            key = ("unlink", str(path))
            if path.name.startswith("candidate_") and key not in failures:
                failures.add(key)
                raise windows_error(32)
            return unlink(path, **kwargs)

        updates = []
        folder = self.root / "evolution"
        with (
            patch.object(storage.os, "replace", side_effect=locked_replace),
            patch.object(Path, "unlink", locked_unlink),
            patch.object(storage.time, "sleep"),
        ):
            evaluate(
                project,
                genome.initial(project, options),
                options,
                threading.Event(),
                updates.append,
                folder,
                "storage-test",
            )
        self.assertEqual(updates[-1]["status"], "completed", updates[-1])
        self.assertTrue(any(key[0] == "replace" for key in failures))
        self.assertTrue(any(key[0] == "unlink" for key in failures))
        self.assertEqual(len(list(folder.glob("candidate_*.meta.json"))), 1)
        best = json.loads((folder / "best.json").read_text())
        meta = json.loads((folder / "best.meta.json").read_text())
        self.assertEqual(meta["fitness"], best["extensions"]["evolution"]["search"]["fitness"])
        self.assertEqual(list(folder.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
