"""Check neuron-count fatigue in live simulation and isolated trials.

Run: .venv/bin/python scripts/neuron_fatigue_smoke.py
"""

import copy
import math
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import schema, trials
from server.runtime import Runtime
from server.world import World


def close(actual, expected):
    assert math.isclose(actual, expected, abs_tol=1e-12), (actual, expected)


def world(**config):
    return World(dict(config=dict(food_target=0, threat_target=0, hunger_rate=0, **config)))


def main():
    assert schema.world_config({})["neuron_fatigue_rate"] == 0
    for invalid in (-0.001, 1.001, True, "0.1", None, float("nan"), float("inf")):
        try:
            schema.world_config(dict(neuron_fatigue_rate=invalid))
        except ValueError:
            pass
        else:
            raise AssertionError(f"Accepted {invalid!r}")

    for count in (0, 10, 100):
        w = world(neuron_fatigue_rate=0.001, fatigue_decay=0)
        for _ in range(round(1 / schema.DT)):
            w.step({}, neuron_count=count)
        close(w.agent["fatigue"], 0.001 * count)
        close(w.agent["health"], 1)

    # Motor spike cost and recovery remain additive; old projects pay no neuron cost.
    for rate in (0, 0.002):
        w = world(neuron_fatigue_rate=rate)
        w.agent["fatigue"] = 0.3
        w.step(dict(left=True, forward=True), neuron_count=100)
        close(w.agent["fatigue"], 0.3 + 2 * 0.025 + rate * 100 * schema.DT - 0.07 * schema.DT)
    w = world(neuron_fatigue_rate=1, fatigue_decay=0)
    w.step({}, neuron_count=1000)
    close(w.agent["fatigue"], 1)
    close(w.agent["health"], 1)  # Exhaustion alone does not cause damage at rest.
    w.step(dict(left=True), neuron_count=1000)
    close(w.agent["health"], 1 - World.exhaustion_damage_rate * schema.DT)
    w = world()
    w.step({}, neuron_count=1000)
    close(w.agent["fatigue"], 0)
    w.drive(dict(left=True), schema.DT)  # Paused manual movement advances no physiology.
    close(w.agent["fatigue"], 0)
    close(w.elapsed, schema.DT)

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "project.json"
        runtime = Runtime(path)
        runtime.command(
            "world_config",
            dict(
                neuron_fatigue_rate=0.002,
                fatigue_decay=0,
                fatigue_gain=0,
                food_target=0,
                threat_target=0,
                hunger_rate=0,
            ),
            runtime.revision,
        )
        close(Runtime(path).world.config["neuron_fatigue_rate"], 0.002)
        project = copy.deepcopy(runtime.project())
        for count in (17, 29):
            topology = copy.deepcopy(project["topology"])
            topology["neurons"] += [dict(id=f"extra_{i}", x=0, y=0) for i in range(count - 17)]
            topology["ganglia"] = [
                dict(
                    id="cluster",
                    x=0,
                    y=0,
                    radius=300,
                    members=[n["id"] for n in topology["neurons"][:3]],
                )
            ]
            runtime.command("topology", topology, runtime.revision)
            assert runtime.net.n == count  # Ganglion connector does not add a neuron.
            runtime.world.agent["fatigue"] = 0
            for _ in range(round(1 / schema.DT)):
                runtime.step()
            close(runtime.world.agent["fatigue"], 0.002 * count)

            captured = []

            def capture(data):
                instance = World(data)
                captured.append(instance)
                return instance

            with patch.object(trials, "World", side_effect=capture):
                result = trials.run_attempt(
                    runtime.project(),
                    trials.settings(dict(duration=1)),
                    0,
                    threading.Event(),
                    lambda *_: None,
                )
            assert result["survived"]
            close(captured[0].agent["fatigue"], 0.002 * count)

        old_project = runtime.project()
        del old_project["world"]["config"]["neuron_fatigue_rate"]
        runtime.command("import", old_project, runtime.revision)
        close(runtime.world.config["neuron_fatigue_rate"], 0)
    print("Neuron fatigue: formula, limits, recovery, persistence, live topology and trials passed")


if __name__ == "__main__":
    main()
