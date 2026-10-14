"""Short reproducibility check, not evidence of improved viability.

.venv/bin/python scripts/evolution_smoke.py --output data/evolution-smoke
"""

import argparse
import copy
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import genome, schema
from server.evolution import assess, atomic_json, evaluate
from server.runtime import Runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/evolution-smoke"))
    args = parser.parse_args()
    project = copy.deepcopy(Runtime().project())
    results = []
    for preset in ("direct", "modulation", "ganglia"):
        options = genome.settings(
            dict(
                preset=preset,
                population=4,
                generations=3,
                elite=1,
                attempts=3,
                validation_attempts=2,
                duration=5,
                seed=42,
                fitness={"neuron_penalty": 0.01},
            )
        )
        path = args.output / preset
        if path.exists():
            raise SystemExit(f"Output already exists: {path}; choose a new --output")
        updates = []
        evaluate(
            project,
            genome.initial(project, options),
            options,
            threading.Event(),
            updates.append,
            path,
            preset,
        )
        state = updates[-1]
        if state["status"] != "completed":
            raise RuntimeError(state)
        best = json.loads((path / "best.json").read_text())
        imported = schema.migrate_project(best)
        imported["compute"] = {"device": "cpu"}
        meta = imported["extensions"]["evolution"]
        replay = assess(imported, options, threading.Event(), lambda *_: None)
        validation = assess(imported, options, threading.Event(), lambda *_: None, True)
        assert replay == meta["search"], "Search replay differs"
        assert validation == meta["validation"], "Validation replay differs"
        assert genome.decode(meta["genome"], project, options) == best["topology"]
        results.append(
            dict(
                preset=preset,
                completed=state["completed"],
                elapsed_seconds=state["elapsed_seconds"],
                size=meta["size"],
                baseline=state["baseline"]["search"]["fitness"],
                fitness=meta["search"]["fitness"],
                search_replay_exact=True,
                validation_replay_exact=True,
                phenotype_exact=True,
                settings=options,
            )
        )
    atomic_json(
        args.output / "report.json",
        dict(purpose="Smoke test only; no long-term viability claim", runs=results),
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
