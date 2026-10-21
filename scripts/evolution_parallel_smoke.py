"""Real spawn workers: deterministic evolution, concurrent episodes and cancellation.

Run: .venv/bin/python scripts/evolution_parallel_smoke.py
Uses temporary archives and a fresh runtime; never touches the running application.
"""

import copy
import json
import multiprocessing as mp
from pathlib import Path
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import genome
from server.evolution import Evolution, evaluate
from server.evolution_pool import EpisodePool
from server.runtime import Runtime


def main():
    project = copy.deepcopy(Runtime().project())
    project["world"]["config"]["neuron_fatigue_rate"] = 0.1
    for neuron in project["topology"]["neurons"]:
        neuron["noise_std"] = 0.1
    base = dict(
        mode="current",
        population=4,
        elite=1,
        generations=2,
        duration=2,
        attempts=2,
        validation_attempts=2,
        archive_size=20,
    )
    outputs = []
    with tempfile.TemporaryDirectory(prefix="bug-parallel-") as directory:
        root = Path(directory)
        for workers in (1, 2, 4):
            options = genome.settings({**base, "workers": workers})
            updates = []
            path = root / str(workers)
            evaluate(
                project,
                genome.initial(project, options),
                options,
                threading.Event(),
                updates.append,
                path,
                "comparison",
            )
            state = updates[-1]
            assert state["status"] == "completed", state
            assert state["settings"]["workers"] == workers
            specimens = {}
            for file in sorted(path.glob("*.json")):
                if file.name.endswith(".meta.json") or file.name == "status.json":
                    continue
                value = json.loads(file.read_text())
                value["extensions"]["evolution"]["settings"].pop("workers")
                specimens[file.name] = value
            outputs.append((state["history"], state["best"], state["baseline"], specimens))
        assert outputs[0] == outputs[1] == outputs[2], "Worker count changed evolution"

        # Exercise actual server-owned coordinator spawning its own pool.
        manager = Evolution(root / "manager")
        runtime = Runtime()
        original = runtime.project()
        try:
            job = manager.start(runtime, {**base, "workers": 2}, runtime.revision)["job"]
            # The manager's collector owns join(); avoid concurrent waitpid calls.
            deadline = time.monotonic() + 20
            while manager.process.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert not manager.process.is_alive(), ("Coordinator hung", manager.snapshot())
            deadline = time.monotonic() + 2
            while manager.snapshot()["job"]["status"] == "running" and time.monotonic() < deadline:
                time.sleep(0.02)
            assert manager.snapshot()["job"]["status"] == "completed", manager.snapshot()
            assert manager.snapshot()["job"]["id"] == job["id"]
            assert runtime.project() == original
            # Cancel during a real, long episode and close the process tree.
            job = manager.start(
                runtime,
                {**base, "workers": 2, "duration": 3600},
                runtime.revision,
            )["job"]
            time.sleep(0.7)
            manager.cancel(job["id"])
            manager.close()
            assert not manager.process.is_alive()
            deadline = time.monotonic() + 2
            while (
                manager.snapshot()["job"]["status"] == "cancelling" and time.monotonic() < deadline
            ):
                time.sleep(0.02)
            assert manager.snapshot()["job"]["status"] == "cancelled", manager.snapshot()
        finally:
            manager.close()

    options = genome.settings({**base, "workers": 2, "duration": 3600, "attempts": 1})
    stop = threading.Event()
    pool = EpisodePool(2, stop)
    overlap = False
    try:
        tickets = [pool.submit(project, options) for _ in range(2)]
        deadline = time.monotonic() + 15

        def progress(*_):
            nonlocal overlap
            overlap = all(any(t["fractions"]) for t in pool.tickets.values())
            if overlap:
                stop.set()
            assert time.monotonic() < deadline, "No concurrent episode progress"

        assert pool.collect(tickets[0], progress) is None
        assert overlap, "Different candidates did not execute concurrently"
    finally:
        pool.close()
    assert all(not p.is_alive() for p in pool.processes), "Worker survived cancellation"

    pool = EpisodePool(2, threading.Event())
    try:
        ticket = pool.submit(project, options)
        pool.processes[0].terminate()
        pool.processes[0].join(timeout=2)
        try:
            pool.collect(ticket, lambda *_: None)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Worker crash must fail the run")
    finally:
        pool.close()
    assert all(not p.is_alive() for p in pool.processes)
    assert not mp.active_children(), "Leaked child processes"
    for invalid in (0, 65, 1.5, True):
        try:
            genome.settings({"workers": invalid})
        except ValueError:
            continue
        raise AssertionError(f"Accepted invalid workers={invalid}")
    print(
        "PASS: exact 1/2/4-process replay, concurrent candidates, server lifecycle, cancel, crash, limits"
    )


if __name__ == "__main__":
    main()
