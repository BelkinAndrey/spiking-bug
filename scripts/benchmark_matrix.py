"""Paired CPU/GPU scaling experiment. Never connects to or edits the running app."""

import argparse
import csv
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
from server.devices import create_network
from server.schema import topology, neuron, DT, MAX_NEURONS, MAX_SYNAPSES

CASES = [
    (100, 10),
    (1000, 10),
    (5000, 10),
    (10000, 10),
    (20000, 10),
    (1000, 100),
    (5000, 100),
    (10000, 50),
    (20000, 25),
]
EXTENDED_CASES = [(10000, 10), (20000, 10), (30000, 10), (50000, 10), (100000, 10), (200000, 10)]


def make_graph(count, fanout, activity):
    rng = np.random.default_rng(42)
    active = activity == "active"
    ids = [f"n{i}" for i in range(count)]
    neurons = [
        dict(
            id=ids[i],
            bias=0.05 if active else 0,
            threshold=1 if active else 100,
            leak=0.02,
            refractory=2,
            reset_mode="retain" if active else "reset",
        )
        for i in range(count)
    ]
    synapses = [
        dict(source=ids[i], target=ids[int(j)], weight=0.04 if i % 5 else -0.08, delay=1 + i % 8)
        for i in range(count)
        for j in rng.integers(0, count, fanout)
    ]
    if count <= MAX_NEURONS and len(synapses) <= MAX_SYNAPSES:
        return topology(dict(format_version=3, neurons=neurons, synapses=synapses))
    # Offline stress test only: engine dimensions have no UI/import quota. Retain
    # canonical neuron/edge fields without relaxing server.schema's product limits.
    template = neuron(neurons[0])
    return dict(
        format_version=3,
        task="BUG",
        ganglia=[],
        groups=[],
        neurons=[{**template, "id": nid} for nid in ids],
        synapses=[{**s, "id": f"s{i}", "kind": "direct"} for i, s in enumerate(synapses)],
    )


def measure(graph, activity, device, steps, warmup):
    net = create_network(graph, device=device)
    # Always pass a vector, as Runtime.step does; include its upload on GPU.
    external = np.zeros(net.n, np.float32)
    if activity == "sparse":
        # Avoid alignment with the every-fifth-neuron inhibitory pattern.
        selected = np.random.default_rng(123).choice(net.n, max(1, net.n // 100), replace=False)
        external[selected] = 125
    for _ in range(warmup):
        net.step(external)
    net.synchronize()
    initial = net.host_values("total")
    timings = np.empty(steps)
    for i in range(steps):
        start = time.perf_counter_ns()
        net.step(external)
        # GPUNetwork.step synchronizes before returning; CPU is synchronous too.
        timings[i] = (time.perf_counter_ns() - start) / 1e6
    totals = net.host_values("total") - initial
    v = net.host_values("V")
    result = dict(
        mean_ms=float(timings.mean()),
        median_ms=float(np.median(timings)),
        p95_ms=float(np.percentile(timings, 95)),
        p99_ms=float(np.percentile(timings, 99)),
        max_ms=float(timings.max()),
        steps_per_second=1000 / float(timings.mean()),
        rate_hz=float(totals.mean() / (steps * DT)),
        memory_mb=net.memory_bytes / 1048576,
        counts_sha256=hashlib.sha256(totals.tobytes()).hexdigest(),
    )
    return result, totals, v, timings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpu", default="mps")
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=150)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--extended",
        action="store_true",
        help="Offline 10k–200k neurons; bypasses only benchmark import quotas",
    )
    parser.add_argument("--output", type=Path, default=Path("docs/benchmarks/scaling"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = dict(
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        platform=platform.platform(),
        python=platform.python_version(),
        numpy=np.__version__,
        pytorch=torch.__version__,
        source_sha256={
            name: hashlib.sha256(
                (Path(__file__).resolve().parents[1] / name).read_bytes()
            ).hexdigest()
            for name in ("server/engine.py", "server/gpu.py", "scripts/benchmark_matrix.py")
        },
        gpu=args.gpu,
        seed=42,
        dt_ms=10,
        steps=args.steps,
        warmup=args.warmup,
        repeats=args.repeats,
        extended=args.extended,
        scope="Synchronized Network.step with external-input upload and spike readback; "
        "excludes topology compilation, world, SSE, rendering, and OS power measurement",
        protocols={
            "active": "bias=0.05, leak=0.02, refractory=2, retain potential",
            "sparse": "bias=0, threshold=100, leak=0.02, refractory=2, reset potential; "
            "constant input 125 into 1% of neurons chosen uniformly without replacement, seed=123; "
            "high threshold prevents recurrent avalanches",
        },
        order="Alternate CPU/GPU within each repetition; each device starts from identical seed/state",
        cases=[],
    )
    raw = {}
    for activity in ("sparse", "active"):
        for count, fanout in EXTENDED_CASES if args.extended else CASES:
            graph = make_graph(count, fanout, activity)
            case = dict(
                activity=activity,
                neurons=count,
                fanout=fanout,
                edges=count * fanout,
                runs=[],
                parity=[],
            )
            for repeat in range(args.repeats):
                pair = {}
                order = ("cpu", args.gpu) if repeat % 2 == 0 else (args.gpu, "cpu")
                for device in order:
                    result, counts, v, timings = measure(
                        graph, activity, device, args.steps, args.warmup
                    )
                    case["runs"].append(dict(device=device, repeat=repeat, **result))
                    pair[device] = (counts, v)
                    raw[f"{activity}_{count}_{fanout}_{device.replace(':', '_')}_{repeat}"] = (
                        timings
                    )
                c, g = pair["cpu"], pair[args.gpu]
                case["parity"].append(
                    dict(
                        repeat=repeat,
                        count_mismatches=int(np.count_nonzero(c[0] != g[0])),
                        max_count_difference=int(np.max(np.abs(c[0] - g[0]))),
                        max_potential_difference=float(np.max(np.abs(c[1] - g[1]))),
                    )
                )
            summary = {}
            for device in ("cpu", args.gpu):
                runs = [r for r in case["runs"] if r["device"] == device]
                times = np.concatenate(
                    [
                        raw[f"{activity}_{count}_{fanout}_{device.replace(':', '_')}_{i}"]
                        for i in range(args.repeats)
                    ]
                )
                summary[device] = dict(
                    mean_ms=float(times.mean()),
                    median_ms=float(np.median(times)),
                    p95_ms=float(np.percentile(times, 95)),
                    p99_ms=float(np.percentile(times, 99)),
                    steps_per_second=1000 / float(times.mean()),
                    run_mean_min_ms=min(r["mean_ms"] for r in runs),
                    run_mean_max_ms=max(r["mean_ms"] for r in runs),
                    rate_hz=float(np.mean([r["rate_hz"] for r in runs])),
                    memory_mb=runs[0]["memory_mb"],
                )
            case["summary"] = summary
            case["gpu_speedup"] = summary["cpu"]["mean_ms"] / summary[args.gpu]["mean_ms"]
            report["cases"].append(case)
            (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
            print(
                f"{activity:6} N={count:5} E={count * fanout:6} "
                f"CPU={summary['cpu']['mean_ms']:.3f} ms GPU={summary[args.gpu]['mean_ms']:.3f} ms "
                f"GPU speedup={case['gpu_speedup']:.2f}x "
                f"rate={summary['cpu']['rate_hz']:.2f} Hz "
                f"mismatches={max(p['count_mismatches'] for p in case['parity'])}",
                flush=True,
            )
    np.savez_compressed(args.output / "timings.npz", **raw)
    rows = [
        dict(
            activity=c["activity"],
            neurons=c["neurons"],
            edges=c["edges"],
            device=d,
            **s,
            gpu_speedup=c["gpu_speedup"],
        )
        for c in report["cases"]
        for d, s in c["summary"].items()
    ]
    with (args.output / "summary.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
