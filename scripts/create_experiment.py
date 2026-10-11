"""Build a reproducible maze experiment using the public Python/schema API."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.schema import default_topology, default_bindings, world_config
from server.generators import maze, ganglion


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("experiment.json"))
    args = parser.parse_args()
    walls, spawn = maze(2400, 1600, 12, 8, args.seed)
    net = ganglion(
        default_topology(),
        dict(
            id="g_explore",
            label="Exploration ganglion",
            x=550,
            y=430,
            count=48,
            radius=190,
            density=0.07,
            excitatory=0.8,
            seed=args.seed,
            neuron=dict(noise_std=0.02),
        ),
    )
    net["synapses"].append(
        dict(
            id="hunger_modulation",
            source="sensor_hunger",
            target="g_explore",
            kind="mod_exc",
            weight=0.1,
            delay=3,
        )
    )
    experiment = dict(
        version=1,
        name=f"Maze · seed {args.seed}",
        topology=net,
        bindings=default_bindings(),
        world=dict(config=world_config(dict(seed=args.seed)), objects=walls, zones=[], spawn=spawn),
    )
    args.output.write_text(json.dumps(experiment, ensure_ascii=False, indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
