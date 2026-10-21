"""Deterministic structural checks for vacancy-biased evolutionary mutations.

Run: .venv/bin/python scripts/evolution_growth_smoke.py
Uses synthetic networks and temporary data only; does not run a live experiment.
"""

import copy
import math
import random
import statistics
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import genome, schema
from server.genome_growth import Coverage, fill_connections, vacant_coordinate
from server.runtime import Runtime


def fixture():
    net = schema.topology(
        dict(
            neurons=[
                dict(id=n, rgb=rgb)
                for n, rgb in (
                    ("sensor", [0, 0, 0]),
                    ("motor", [1, 1, 1]),
                    ("used", [0.2, 0.2, 0.2]),
                    ("idle", [0.5, 0.5, 0.5]),
                    ("idle2", [0.7, 0.2, 0.8]),
                )
            ],
            synapses=[
                dict(id="input", source="sensor", target="used", weight=1),
                dict(id="output", source="used", target="motor", weight=1),
            ],
        )
    )
    project = Runtime().project()
    project.update(
        topology=net, bindings=schema.bindings({"food_left": "sensor", "forward": "motor"}, net)
    )
    options = genome.settings(
        dict(
            mode="current",
            preset="direct",
            fill_bias=1,
            population=3,
            elite=1,
            add_rate=1,
            delete_rate=0,
            change_rate=0,
        )
    )
    return project, options, genome.initial(project, options)


def exercise():
    project, options, original = fixture()
    untouched = copy.deepcopy(original)
    rates = {}
    for bias in (0, 1):
        connected = 0
        incoming = 0
        for seed in range(64):
            config = {**options, "fill_bias": bias}
            child = genome.mutate(original, project, config, seed)
            assert child == genome.mutate(original, project, config, seed)
            net = genome.decode(child, project, config)
            coverage = Coverage(child, net, genome.nodespace(child), config)
            added = {n["id"] for n in child["A"]} - {n["id"] for n in original["A"]}
            assert len(added) == 1
            nid = added.pop()
            incoming += bool(coverage.incoming[nid])
            connected += nid in coverage.from_sensors and nid in coverage.to_motors
            for frozen in original["frozen"]:
                assert next(n for n in child["A"] if n["id"] == frozen) == next(
                    n for n in original["A"] if n["id"] == frozen
                )
            assert all(e["source"] != e["target"] for e in net["synapses"])
        rates[bias] = connected
        print(
            f"fill_bias={bias}: new neurons with input {incoming}/64; sensor-to-motor path {connected}/64"
        )
    assert rates[1] == 64 and rates[0] < 32
    assert original == untouched

    # Actual edges, not merely overlapping rule spheres, determine occupancy.
    dirty = copy.deepcopy(original)
    for eid, source, target, weight, kind in (
        ("self", "idle", "idle", 1, "direct"),
        ("zero", "sensor", "idle", 0, "direct"),
        ("mod", "sensor", "idle", 1, "mod_exc"),
    ):
        dirty["B"].append(
            dict(
                id=eid,
                type="synapse",
                synapse=dict(
                    id=eid,
                    source=source,
                    target=target,
                    weight=weight,
                    kind=kind,
                    delay=1,
                ),
            )
        )
    mixed = genome.settings({**options, "preset": "modulation", "mod_exc": True})
    rule = genome.new_rule("empty", genome.nodespace(dirty), random.Random(0), mixed)
    rule.update(density=0, source_radius=math.sqrt(3), target_radius=math.sqrt(3))
    dirty["B"].append(rule)
    dirty = genome.normalize(dirty, project, mixed)
    net = genome.decode(dirty, project, mixed)
    coverage = Coverage(dirty, net, genome.nodespace(dirty), mixed)
    assert "idle" not in coverage.from_sensors
    assert not coverage.incoming["idle"] and not coverage.outgoing["idle"]
    seq = iter(range(1000))

    def identity(block):
        return f"fill_{block}_{next(seq)}"

    repaired = fill_connections(
        copy.deepcopy(dirty), project, mixed, random.Random(7), identity, ["idle"]
    )
    coverage = Coverage(
        repaired, genome.decode(repaired, project, mixed), genome.nodespace(repaired), mixed
    )
    assert "idle" in coverage.from_sensors & coverage.to_motors

    # Both source and target proposals strongly prefer unused endpoint regions.
    net = genome.decode(original, project, options)
    coverage = Coverage(original, net, genome.nodespace(original), options)
    rng = random.Random(4)
    source_hits = target_hits = 0
    for _ in range(1000):
        a, b = coverage.choose_pair(rng, options, "direct")
        source_hits += a["id"] in ("idle", "idle2")
        target_hits += b["id"] in ("idle", "idle2")
        assert a["id"] != b["id"]
    assert source_hits > 850 and target_hits > 850
    print(f"Unused source/target choices: {source_hits}/1000, {target_hits}/1000")

    # Near-full rule/expanded-edge budgets skip optional growth safely.
    for changes in ({"max_rules": 2}, {"max_synapses": 2}):
        bounded = {**options, **changes}
        child = fill_connections(
            copy.deepcopy(original), project, bounded, random.Random(1), identity, ["idle"]
        )
        assert genome.decode(child, project, bounded) == project["topology"]
    stop = threading.Event()
    stop.set()
    try:
        fill_connections(
            copy.deepcopy(original), project, options, random.Random(1), identity, stop=stop
        )
    except InterruptedError:
        pass
    else:
        raise AssertionError("Growth ignored cancellation")

    # Connector expansion integrates every neuron in a newly generated ganglion.
    grouped = genome.settings({**options, "preset": "ganglia"})
    for seed in range(12):
        child = genome.mutate(original, project, grouped, seed)
        net = genome.decode(child, project, grouped)
        raw = Coverage(child, net, net["neurons"], grouped)
        for group in net["ganglia"]:
            assert set(group["members"]) <= raw.from_sensors & raw.to_motors
        assert child == genome.mutate(original, project, grouped, seed)

    # Only enabled direct signs or modulatory types may be introduced.
    for changes in (
        {"direct_inh": False},
        {"direct_exc": False},
        {"preset": "modulation", "direct_exc": False, "direct_inh": False, "mod_exc": True},
    ):
        config = genome.settings({**options, **changes})
        # Use a fresh network because the fixture contains positive direct links.
        config["mode"] = "fresh"
        fresh = genome.initial(project, config)
        child = genome.mutate(fresh, project, config, 12)
        net = genome.decode(child, project, config)
        assert {e["kind"] for e in net["synapses"]} <= set(genome.kinds(config))
        if not config["direct_inh"]:
            assert all(e["weight"] >= 0 for e in net["synapses"] if e["kind"] == "direct")
        if not config["direct_exc"]:
            assert all(e["weight"] <= 0 for e in net["synapses"] if e["kind"] == "direct")

    # Gap sampling should spread points more evenly than independent uniform draws.
    distances = {}
    for guided in (False, True):
        rng = random.Random(123)
        space = []
        for i in range(80):
            color = vacant_coordinate(space, rng) if guided else [rng.random() for _ in range(3)]
            space.append(dict(id=str(i), rgb=color))
        distances[guided] = statistics.mean(
            min(math.dist(a["rgb"], b["rgb"]) for b in space if a is not b) for a in space
        )
    assert distances[True] > distances[False] * 1.3
    print(f"Mean nearest RGB distance: random={distances[False]:.3f}, vacant={distances[True]:.3f}")
    print("PASS: deterministic growth, integration, coverage, frozen ports, presets and budgets")


if __name__ == "__main__":
    exercise()
