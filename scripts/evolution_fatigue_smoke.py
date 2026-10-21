"""Check shared fatigue settings and lifetime-only evolution scoring.

Run: .venv/bin/python scripts/evolution_fatigue_smoke.py
"""

import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import genome
from server.evolution import Evolution, assess, fitness
from server.runtime import Conflict, Runtime


def main():
    assert fitness([dict(duration=2), dict(duration=4)]) == dict(
        value=3, lifetime=3, lifetime_std=1
    )
    assert "fitness" not in genome.settings(dict(fitness=dict(neuron_penalty=999)))
    for invalid in (-1, 2, True, float("nan"), "0.1"):
        try:
            genome.settings(dict(neuron_fatigue_rate=invalid))
        except ValueError:
            pass
        else:
            raise AssertionError(f"Accepted {invalid!r}")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runtime = Runtime(root / "project.json")
        manager = Evolution(root / "archive")
        options = dict(
            population=2,
            elite=1,
            generations=1,
            attempts=1,
            validation_attempts=1,
            duration=1,
            workers=2,
            mode="current",
        )
        try:
            original = copy.deepcopy(runtime.project())
            for changes, revision, error in (
                ({"neuron_fatigue_rate": -1}, runtime.revision, ValueError),
                ({"neuron_fatigue_rate": 0.01}, runtime.revision - 1, Conflict),
                ({"neuron_fatigue_rate": 0.01, "max_neurons": 1}, runtime.revision, ValueError),
            ):
                try:
                    manager.start(runtime, {**options, **changes}, revision)
                except error:
                    pass
                else:
                    raise AssertionError("Invalid start succeeded")
                assert runtime.project() == original

            # First run saves an explicit coefficient; the second inherits the world value.
            for changes in ({"neuron_fatigue_rate": 0.1}, {}):
                job = manager.start(runtime, {**options, **changes}, runtime.revision)["job"]
                assert job["settings"]["neuron_fatigue_rate"] == 0.1
                assert "fitness" not in job["settings"]
                assert runtime.world.config["neuron_fatigue_rate"] == 0.1
                assert Runtime(root / "project.json").world.config["neuron_fatigue_rate"] == 0.1
                source = json.loads((manager.root / job["id"] / "source.json").read_text())
                assert source["world"]["config"]["neuron_fatigue_rate"] == 0.1
                if changes:
                    # Later live edits must not change the frozen evaluation environment.
                    runtime.command("world_config", {"neuron_fatigue_rate": 0.2}, runtime.revision)
                deadline = time.monotonic() + 15
                while manager.snapshot()["job"]["status"] == "running":
                    assert time.monotonic() < deadline, manager.snapshot()
                    time.sleep(0.02)
                assert manager.snapshot()["job"]["status"] == "completed", manager.snapshot()
                manager.close()
                best = json.loads((manager.root / job["id"] / "best.json").read_text())
                assert best["world"]["config"]["neuron_fatigue_rate"] == 0.1
                meta = best["extensions"]["evolution"]
                for validation in (False, True):
                    result = assess(
                        best, job["settings"], threading.Event(), lambda *_: None, validation
                    )
                    assert result == meta["validation" if validation else "search"]
                    assert result["fitness"]["value"] == result["fitness"]["lifetime"]
                    assert "neuron_penalty" not in result["fitness"]
                runtime.command("world_config", {"neuron_fatigue_rate": 0.1}, runtime.revision)
        finally:
            manager.close()
    print(
        "PASS: shared fatigue, validation, persistence, frozen environment, parallel replay, no penalty"
    )


if __name__ == "__main__":
    main()
