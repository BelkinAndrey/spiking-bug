"""Check finite/unlimited evolution and cancellation without touching live runs.

Run: .venv/bin/python scripts/evolution_limits_smoke.py
"""

from itertools import count
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import genome
from server.evolution import evaluate
from server.runtime import Runtime


def main():
    project = Runtime().project()
    base = dict(
        preset="direct", mode="current", population=3, elite=1,
        duration=1, attempts=1, validation_attempts=1, wall_seconds=1,
    )
    for generations, cancel_during_candidate in ((2, False), (0, False), (0, True)):
        options = genome.settings({**base, "generations": generations})
        assert "wall_seconds" not in options
        stop = threading.Event()
        updates = []

        def publish(state):
            updates.append(state)
            if generations == 0:
                if cancel_during_candidate:
                    if state["generation"] == 1 and state["candidate"] == 2:
                        stop.set()
                elif len(state["history"]) == 3:
                    stop.set()

        with tempfile.TemporaryDirectory(prefix="bug-evolution-limits-") as directory:
            # Advance the clock beyond an hour without waiting or consuming CPU time.
            with patch("server.evolution.time.monotonic", side_effect=count(0, 1000)):
                evaluate(
                    project, genome.initial(project, options), options, stop,
                    publish, directory, "limits",
                )
            state = updates[-1]
            assert state["elapsed_seconds"] > 3600
            if generations:
                assert state["status"] == "completed", state
                assert state["stop_reason"] is None
                assert len(state["history"]) == 2
                assert state["completed"] == 5  # Three initial candidates + two offspring.
            else:
                assert state["status"] == "cancelled", state
                assert state["stop_reason"] == "requested"
                assert len(state["history"]) == (1 if cancel_during_candidate else 3)
                assert state["completed"] == (3 if cancel_during_candidate else 7)
                if cancel_during_candidate:
                    assert not (Path(directory) / "candidate_g00001_i001.json").exists()
            assert (Path(directory) / "best.json").is_file()
    try:
        genome.settings({**base, "generations": -1})
    except ValueError:
        pass
    else:
        raise AssertionError("Negative generation limit accepted")
    print("PASS: finite generations, unlimited search, cancellation, no wall-clock deadline")


if __name__ == "__main__":
    main()
