"""Regression smoke for importing a manual network into evolution.

Run: .venv/bin/python scripts/evolution_current_smoke.py
Uses temporary files; does not change the active document or start a service.
"""

import copy
import json
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import genome, genome_import, schema
from server.evolution import assess, evaluate
from server.runtime import Runtime


def rejected(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("Expected incompatible network to be rejected")


def main():
    options = genome.settings(
        dict(
            mode="current",
            population=3,
            elite=1,
            generations=2,
            duration=2,
            attempts=2,
            validation_attempts=1,
        )
    )
    base = Runtime().project()
    assert genome.decode(genome.initial(base, options), base, options) == base["topology"]
    raw = dict(
        format_version=3,
        neurons=[
            dict(id="z" * 80, noise_std=0.2, polarity="mixed"),
            dict(id="a", bias=0.2, polarity="exc"),
            dict(id="b", bias=0.1, polarity="inh"),
        ],
        ganglia=[dict(id="grp", members=["b", "a"], x=120, y=130, radius=50)],
        synapses=[
            dict(id="s3", source="grp", target="z" * 80, weight=0.8),
            dict(id="s1", source="z" * 80, target="grp", weight=0.3),
            dict(id="s2", source="z" * 80, target="z" * 80, weight=0.7),
            dict(id="s4", source="z" * 80, target="z" * 80, weight=0.2),
            dict(id="s5", source="a", target="b", kind="mod_inh", weight=-0.3),
        ],
        groups=[dict(id="frame", x=0, y=0, w=50, h=50)],
    )
    net = schema.topology(raw)
    project = {**base, "topology": net, "bindings": schema.bindings({"forward": "a"}, net)}
    genes = genome.initial(project, options)
    assert genome.decode(genes, project, options) == net
    baseline = assess(project, options, threading.Event(), lambda *_: None)
    roundtrip = json.loads(json.dumps(genes))
    decoded = genome.decode(roundtrip, project, options)
    assert (
        assess({**project, "topology": decoded}, options, threading.Event(), lambda *_: None)
        == baseline
    )
    assert {n["id"] for n in genome.nodespace(genes)} == {"z" * 80, "grp"}
    assert baseline["fitness"]["value"] == baseline["fitness"]["lifetime"]
    for changes in (
        {"preset": "direct"},
        {"mod_inh": False},
        {"direct_inh": False},
        {"max_rules": 4},
        {"max_synapses": 6},
        {"max_neurons": 2},
    ):
        restricted = genome.settings({**options, **changes})
        rejected(lambda: genome.initial(project, restricted))
    removed = copy.deepcopy(genes)
    group = removed["C"].pop()
    genome_import.delete_group(removed, group)
    genome_import.prune_explicit(removed)
    child_net = genome.decode(removed, project, options)
    assert {n["id"] for n in child_net["neurons"]} == {"z" * 80, "a"}
    assert not child_net["ganglia"]
    changed = set()
    for i in range(100):
        try:
            child = genome.mutate(genes, project, options, i)
            child_net = genome.decode(child, project, options)
        except ValueError:
            continue
        assert next(n for n in child_net["neurons"] if n["id"] == "a") == net["neurons"][1]
        for block in "ABC":
            if child[block] != genes[block]:
                changed.add(block)
    assert changed == set("ABC"), changed
    # An inherited connector counts as multiple physical edges alongside recipes.
    hybrid = copy.deepcopy(genes)
    hybrid["C"].append(
        dict(
            id="recipe",
            rgb=[0.3, 0.4, 0.5],
            connector_rgb=[0.5, 0.4, 0.3],
            recipe=dict(
                count=3,
                density=1,
                radius=100,
                weight=0.5,
                delay=2,
                seed=7,
                excitatory=1,
                mode="neurons",
                kind="direct",
            ),
        )
    )
    rejected(lambda: genome.decode(hybrid, project, {**options, "max_synapses": 8}))
    with tempfile.TemporaryDirectory(prefix="bug-current-evolution-") as directory:
        path = Path(directory)
        updates = []
        evaluate(project, genes, options, threading.Event(), updates.append, path, "current")
        assert updates[-1]["status"] == "completed", updates[-1]
        first = json.loads((path / "candidate_g00000_i000.json").read_text())
        assert first["topology"] == net
        assert first["extensions"]["evolution"]["search"] == baseline
        best = schema.migrate_project(json.loads((path / "best.json").read_text()))
        best["compute"] = {"device": "cpu"}
        meta = best["extensions"]["evolution"]
        assert meta["decoder"] == 2
        assert assess(best, options, threading.Event(), lambda *_: None) == meta["search"]
        assert assess(best, options, threading.Event(), lambda *_: None, True) == meta["validation"]
        continued = genome.initial(best, {**options, "mode": "continue"})
        assert genome.decode(continued, best, options) == best["topology"]
        # Current mode uses edited phenotype even if old genotype metadata remains.
        edited = copy.deepcopy(best)
        node = next(n for n in edited["topology"]["neurons"] if n["id"] not in genes["frozen"])
        node["bias"] += 0.25
        assert genome.decode(genome.initial(edited, options), edited, options) == edited["topology"]
    # Existing version-1 artifacts must keep their exact phenotype.
    artifacts = list(Path("data/evolution-smoke-final").glob("*/best.json"))
    for file in artifacts:
        saved = schema.migrate_project(json.loads(file.read_text()))
        meta = saved["extensions"]["evolution"]
        assert (
            genome.decode(meta["genome"], saved, genome.settings(meta["settings"]))
            == saved["topology"]
        )
    print(
        f"PASS: lossless import, noisy replay, limits, frozen members, mutations, hybrid budgets, "
        f"two generations, export/continue and {len(artifacts)} legacy artifacts"
    )


if __name__ == "__main__":
    main()
