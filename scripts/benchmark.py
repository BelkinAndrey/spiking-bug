"""Reproducible kernel benchmark; does not include world, JSON, or rendering."""

import argparse
import json
import importlib.metadata
import platform
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from server.schema import topology
from server.devices import create_network, devices


def measure(count, fanout, steps, device="cpu", project=None, drive=0):
    rng = np.random.default_rng(42)
    ns = [dict(id=f"n{i}", bias=0.05, leak=0.02, refractory=2) for i in range(count)]
    ss = [
        dict(source=f"n{i}", target=f"n{int(j)}", weight=0.04 if i % 5 else -0.08, delay=1 + i % 8)
        for i in range(count)
        for j in rng.integers(0, count, fanout)
    ]
    graph = (
        project["topology"]
        if project
        else topology(dict(format_version=3, neurons=ns, synapses=ss))
    )
    net = create_network(graph, device=device)
    external = np.full(net.n, drive, dtype=np.float32) if drive else None
    for _ in range(100):
        net.step(external)
    net.synchronize()
    timings = []
    for _ in range(steps):
        start = time.perf_counter()
        net.step(external)
        net.synchronize()
        timings.append((time.perf_counter() - start) * 1000)
    return dict(
        device=device,
        neurons=net.n,
        edges=len(net.sources),
        steps=steps,
        median_ms=float(np.median(timings)),
        p95_ms=float(np.percentile(timings, 95)),
        memory_mb=net.memory_bytes / 1048576,
        spikes_per_neuron=float(net.host_values("total").mean()) if net.n else 0,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--steps", type=int, default=1000)
    p.add_argument("--output", type=Path)
    p.add_argument("--devices", nargs="+", default=["cpu"])
    p.add_argument("--drive", type=float, default=0, help="Constant external input to every neuron")
    p.add_argument(
        "--project", type=Path, help="Benchmark a saved topology instead of synthetic graphs"
    )
    a = p.parse_args()
    try:
        torch_version = importlib.metadata.version("torch")
    except importlib.metadata.PackageNotFoundError:
        torch_version = None
    result = dict(
        platform=platform.platform(),
        python=platform.python_version(),
        numpy=np.__version__,
        pytorch=torch_version,
        drive=a.drive,
        seed=42,
        dt_ms=10,
        scope="Synchronized Network.step including spike readback; excludes world, telemetry, browser",
        available_devices=devices(),
        results=[
            measure(
                n,
                10,
                a.steps,
                device,
                json.loads(a.project.read_text()) if a.project else None,
                a.drive,
            )
            for device in a.devices
            for n in ((0,) if a.project else (1000, 10000, 20000))
        ],
    )
    out = json.dumps(result, indent=2)
    if a.output:
        a.output.write_text(out + "\n")
    print(out)
