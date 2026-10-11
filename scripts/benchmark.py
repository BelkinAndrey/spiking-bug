"""Reproducible kernel benchmark; does not include world, JSON, or rendering."""

import argparse
import json
import platform
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from server.schema import topology
from server.engine import Network


def measure(count, fanout, steps):
    rng = np.random.default_rng(42)
    ns = [dict(id=f"n{i}", bias=0.05, leak=0.02, refractory=2) for i in range(count)]
    ss = [
        dict(source=f"n{i}", target=f"n{int(j)}", weight=0.04 if i % 5 else -0.08, delay=1 + i % 8)
        for i in range(count)
        for j in rng.integers(0, count, fanout)
    ]
    net = Network(topology(dict(format_version=3, neurons=ns, synapses=ss)))
    for _ in range(100):
        net.step()
    timings = []
    for _ in range(steps):
        start = time.perf_counter()
        net.step()
        timings.append((time.perf_counter() - start) * 1000)
    return dict(
        neurons=count,
        edges=len(ss),
        steps=steps,
        median_ms=float(np.median(timings)),
        p95_ms=float(np.percentile(timings, 95)),
        memory_mb=net.memory_bytes / 1048576,
        spikes_per_neuron=float(net.total.mean()),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--steps", type=int, default=1000)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    result = dict(
        platform=platform.platform(),
        python=platform.python_version(),
        numpy=np.__version__,
        seed=42,
        dt_ms=10,
        scope="Network.step only; excludes world, telemetry, browser",
        results=[measure(n, 10, a.steps) for n in (1000, 10000, 20000)],
    )
    out = json.dumps(result, indent=2)
    if a.output:
        a.output.write_text(out + "\n")
    print(out)
