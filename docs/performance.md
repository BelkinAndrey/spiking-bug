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

## CPU versus GPU (Metal/MPS)

The optional GPU kernel was measured on the same Apple M5 with PyTorch 2.14.1.
Raw results: [benchmark-gpu-macos.json](benchmark-gpu-macos.json). These runs use
100 warmup steps and 200 measured steps, with explicit GPU synchronization and
the spike-vector readback included. They still exclude world, SSE and rendering.

| Neurons / edges | CPU median | MPS median | CPU p95 | MPS p95 |
|---|---:|---:|---:|---:|
| 1,000 / 10,000 | 0.036 ms | 0.448 ms | 0.123 ms | 0.590 ms |
| 10,000 / 100,000 | 0.250 ms | 0.531 ms | 1.160 ms | 0.646 ms |
| 20,000 / 200,000 | 0.501 ms | 0.682 ms | 2.382 ms | 1.028 ms |

CPU remains faster by median in these workloads; MPS has lower p95 for the two
larger networks. No general GPU speedup is claimed. The 10 ms simulation timestep
leaves headroom for either kernel here, but application throughput also includes
world and telemetry costs. Device selection stays explicit, with CPU the default.

The current 141-neuron topology (1,427 effective edges) was also copied read-only
and benchmarked outside the active experiment, with constant external input 0.1
to every neuron: 0.018 ms CPU versus 0.631 ms MPS median over 300 measured steps.
Both produced 78.51 spikes/neuron over warmup plus measurement. This is a controlled
kernel stimulus, **not** a measurement of the running bug's sensor-driven behavior.
Raw results: [benchmark-gpu-current-network.json](benchmark-gpu-current-network.json).
These results and numerical tests verify MPS on this host; no CUDA hardware was
available to test. Float32 scatter accumulation does not promise bitwise identical
long trajectories between devices.

## Scaling beyond editor limits

A paired sweep on 11 October 2026 compares NumPy CPU and Metal/MPS on Apple M5,
16 GB unified memory. Each case has three fresh seeded runs per device, 150 warmup
steps and 1,000 measured steps. CPU/GPU order alternates between repetitions.
Unlike the earlier microbenchmark, every step passes an external-input vector,
as the application does. GPU input upload, spike readback and synchronization are
included. **Mean step time** determines throughput; median alone understates the
cost of periodically synchronized bursts. Bands in the chart are the minimum and
maximum of the three run means, not confidence intervals.

Two controlled regimes use identical seeded connectivity and delays 1–8:

- Sparse: reset mode, no bias, threshold 100, input 125 into a seeded random 1% of
  neurons. The high threshold prevents recurrent avalanches. Measured activity is
  0.334 Hz/neuron (roughly 0.334% of neurons spike each 10 ms step).
- Active: retain mode, threshold 1, bias 0.05, leak 0.02 and refractory 2.
  Measured activity is approximately 31–33 Hz/neuron. This is a separate workload,
  not a claim that only one biological parameter changed.

The normal sweep covers 100–20,000 neurons and 1,000–500,000 edges. The extended
sweep includes 30,000, 50,000, 100,000 and 200,000 neurons at fanout 10 (up to two
million edges), and repeats 10k/20k controls. The offline script constructs canonical
kernel input above schema quotas; **editor/API limits remain 20k neurons / 500k
expanded edges**. The live experiment was never paused, edited or restarted by
these measurements. This is a desktop measurement with other apps open, not an
isolated hardware testbed. Run-to-run variation matters around the crossover.

Extended-suite **mean milliseconds per step**, fanout 10:

| Neurons | Edges | Active CPU ms | Active MPS ms | MPS speedup | Sparse CPU ms | Sparse MPS ms |
|---:|---:|---:|---:|---:|---:|---:|
| 10,000 | 100,000 | 0.817 | 0.938 | 0.87× | 0.192 | 0.912 |
| 20,000 | 200,000 | 1.680 | 1.119 | 1.50× | 0.482 | 0.996 |
| 30,000 | 300,000 | 2.521 | 1.544 | 1.63× | 0.697 | 1.162 |
| 50,000 | 500,000 | 4.207 | 2.415 | 1.74× | 1.084 | 1.581 |
| 100,000 | 1,000,000 | 8.595 | 4.570 | 1.88× | 2.203 | 4.657 |
| 200,000 | 2,000,000 | 18.090 | 7.700 | 2.35× | 4.756 | 7.581 |

In this extended series the active workload crosses between the measured 10k and
20k points. At 30k and above, GPU wins in every individual repetition, not just in
the pooled mean. Treat 20–30k as a local working range rather than a universal
threshold: earlier shorter runs were closer to parity at 20k, and foreground OS
load affects latency. The GPU does not win at any tested sparse point, even 200k.
Increasing edge density can move the crossover to fewer neurons: the standard
sweep's active 5k-neuron / 500k-edge network already favors GPU.

All 180 retained runs (108 standard + 72 extended, including repeated controls)
matched CPU/GPU per-neuron spike counts for their paired initial states. Final
potentials also matched in these deterministic, noise-free fixtures; this does
not guarantee bitwise equivalence for arbitrary noisy or threshold-sensitive
experiments. At 200k/2M, kernel buffers are about 88.5 MiB CPU versus 111.4 MiB MPS.

The cause is visible in the implementations: CPU scans source activity and only
scatters firing edges. MPS scatters every edge with a spike mask, plus launches
many small tensor operations and transfers inputs/spikes each step. Its throughput
advantage emerges with enough **active** synaptic work to amortize those costs.
The application's world and rendering can shift whole-application results.

Raw summaries, run means, percentiles, activity, memory and numerical comparisons:
[standard sweep](benchmarks/2026-10-11-scaling/results.json),
[extended sweep](benchmarks/2026-10-11-extended/results.json).
Each directory also contains `summary.csv` and `timings.npz` with individual step
latencies. The combined [figure](benchmarks/2026-10-11-extended/scaling.png) uses the
extended run for overlapping 10k/20k cases.

These are **kernel** speed and buffer-memory measurements. They exclude world
physics/sensors, SSE serialization, frontend drawing and topology compilation.
Tensor/array bytes exclude PyTorch caches, Python topology objects and total
process memory. Energy consumption was not measured. CUDA was unavailable.

## Reproduce

```bash
.venv/bin/python scripts/benchmark.py --steps 1000 --output docs/benchmark-local.json
.venv/bin/python scripts/benchmark.py --steps 200 --devices cpu mps --output docs/benchmark-gpu-local.json
# CUDA host: replace mps with cuda:0.
# Optional saved topology with controlled external input:
.venv/bin/python scripts/benchmark.py --devices cpu mps --project data/project.json --drive 0.1
# Paired activity / density / size sweeps (sequential, not parallel):
.venv/bin/python scripts/benchmark_matrix.py --output docs/benchmarks/scaling-local
.venv/bin/python scripts/benchmark_matrix.py --extended --output docs/benchmarks/extended-local
# Optional static report figure:
.venv/bin/python -m pip install 'matplotlib>=3.9,<4'
.venv/bin/python scripts/plot_benchmark_matrix.py docs/benchmarks/scaling-local --extend docs/benchmarks/extended-local
```

The UI reports an exponential moving average of **network + world** step duration,
active kernel array/tensor memory, and scheduler overruns. Browser rendering is separate and limited
to 30 Hz. Telemetry is 15 Hz; neuronal totals are cumulative, not frame-local events.

## Remaining scaling costs

- A CPU step scans all edges to find sources that fired; GPU scatters all edges with
  a source-spike mask. A CSR event-driven implementation
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
- GPU launch and CPU/GPU synchronization costs dominate small networks. Motor
  feedback currently requires spike readback each step. Batching independent worlds
  or moving world feedback onto GPU would be separate architectural changes.
