"""Check archive deletion and active-worker protection in an isolated directory.

Run: .venv/bin/python scripts/evolution_archive_smoke.py
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.app import create_app
from server.evolution import Evolution, atomic_json
from server.runtime import Runtime


def main():
    with tempfile.TemporaryDirectory(prefix="bug-archive-test-") as directory:
        base = Path(directory)
        runtime = Runtime(base / "project.json")
        project = runtime.project()
        atomic_json(runtime.path, project)
        app = create_app(runtime)
        manager = app.extensions["evolution"]
        client = app.test_client()
        for run in ("first", "second"):
            folder = manager.root / run
            folder.mkdir()
            for name in ("source", "experiment", "status", "best", "saved_pinned"):
                atomic_json(folder / (name + ".json"), {"status": "completed"})
            atomic_json(folder / "saved_pinned.meta.json", {"id": run, "saved": 1})
            (folder / "nested").mkdir()
            (folder / "nested" / "unfinished.tmp").write_text("partial")
        (manager.root / "leftover.tmp").write_text("partial")
        outside = base / "outside"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_text("keep")
        (manager.root / "linked-directory").symlink_to(outside, target_is_directory=True)
        (manager.root / "linked-file").symlink_to(sentinel)

        manager.process = Mock()
        manager.process.is_alive.return_value = True
        # A terminal status can arrive before the worker has actually exited.
        for status in ("running", "cancelling", "completed"):
            manager.job = {"id": "second", "status": status}
            response = client.post("/api/evolution/clear")
            assert response.status_code == 409, response.json
            assert (manager.root / "first" / "saved_pinned.json").is_file()
            assert manager.job["status"] == status
        manager.process = None

        for _ in range(2):
            response = client.post("/api/evolution/clear")
            assert response.status_code == 200, response.json
            assert response.json == {"job": None, "artifacts": []}
            assert manager.root.is_dir() and not list(manager.root.iterdir())
            assert client.get("/api/evolution").json == response.json
        assert Evolution(manager.root).snapshot() == {"job": None, "artifacts": []}
        assert runtime.project() == project
        assert runtime.path.is_file()
        assert sentinel.read_text() == "keep"
    print("Archive deletion, repeat clearing, restart, and active-worker protection passed")


if __name__ == "__main__":
    main()
