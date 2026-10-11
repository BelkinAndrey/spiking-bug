# Performance: measured locally

Measured 11 October 2026 on Apple M5, macOS 27.0.1 arm64, Python 3.13.13,
NumPy 2.5.4. Raw results: [benchmark-macos.json](benchmark-macos.json).

The benchmark constructs a seeded sparse network with 10 outgoing edges per
neuron, delays 1–8 steps, tonic bias and both positive and negative weights.
It warms up for 100 steps and measures 1,000 more. Retained potentials keep the
network substantially active (about 339 spikes per neuron over 1,100 steps).

| Neurons | Effective edges | Median step | p95 step | NumPy array memory |
|---:|---:|---:|---:|---:|
| 1,000 | 10,000 | 0.035 ms | 0.118 ms | 0.45 MB |
| 10,000 | 100,000 | 0.242 ms | 1.135 ms | 4.49 MB |
| 20,000 | 200,000 | 0.516 ms | 2.448 ms | 8.98 MB |

**Scope:** these are timings of `Network.step`, not whole-application throughput.
They exclude topology validation/compilation, BUG collision/sensor processing,
JSON serialization, SSE bandwidth, browser interaction and drawing. Array memory
excludes Python objects and process overhead. This is one machine and one workload,
not a bound for every connectivity pattern. Delay 256 uses much more ring memory.

The physics timestep is 10 ms. These kernel timings leave CPU headroom for this
workload, so a GPU dependency is not necessary for the first version. There is
no GPU implementation or CPU-versus-GPU measurement here; PyTorch was not installed
in the project environment. GPU acceleration remains an engineering option for
larger/batched workloads, requiring numerical parity and actual end-to-end timings.

## Reproduce

```bash
.venv/bin/python scripts/benchmark.py --steps 1000 --output docs/benchmark-local.json
```

The UI reports an exponential moving average of **network + world** step duration,
NumPy array memory, and scheduler overruns. Browser rendering is separate and limited
to 30 Hz. Telemetry is 15 Hz; neuronal totals are cumulative, not frame-local events.

## Remaining scaling costs

- A step scans all edges to find sources that fired. A CSR event-driven implementation
  could improve very low-activity sparse networks; measure before choosing it.
- World sensors test rectangles directly. Dense mazes and many threats can dominate
  the neural kernel; spatial indexing would be the next world optimization.
- JSON topology/validation and saves are O(N + E) and run under the shared lock.
  Large structural edits can pause simulation briefly. Every added ganglion counts
  expanded connector targets toward the 500,000-edge limit.
- Scene rendering culls points and decimates edges; visible individual neural activity
  is limited to the first 2,000 neurons. Group/network rate graphs remain exact.
- A max-delay ring trades bounded memory for no pulse truncation. A sparse event
  queue may be preferable for very long, very sparse delays.
