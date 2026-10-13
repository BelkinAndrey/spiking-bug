# Architecture and numerical contract

Spiking Bug is a local, deterministic-step research sandbox, not a biologically
validated model and not a learning algorithm. Weights change only through editing
or importing an experiment. The default controller is hand-wired.

## Ownership

- `server/schema.py`: format validation and legacy migration.
- `server/engine.py`: NumPy LIF state and delayed sparse transmission; no HTTP/world code.
- `server/gpu.py`: device-resident PyTorch LIF kernel for Metal/MPS and CUDA.
- `server/devices.py`: optional GPU discovery and explicit backend factory.
- `server/world.py`: BUG geometry, sensors, food, obstacles, threats.
- `server/generators.py`: seeded ganglia, inter-ganglion projections and connected DFS mazes.
- `server/runtime.py`: authoritative clock, bindings, transactions, telemetry, persistence.
- `server/app.py`: local REST API and SSE at 15 Hz.
- `apps/environment`: Vite entry on port 5173.
- `apps/editor`: Vite entry on port 5174.
- `packages/ui`: typed protocol, Canvas viewports, panels and shared transport controls.

Both clients proxy `/api` to port 8000. Closing either client does not interrupt
simulation. The server starts paused. The simulation thread holds a lock around
fixed steps and edits. There is only one neural state, world and bindings table.
Commands carry a project revision; stale edits return HTTP 409 instead of silently
overwriting another window. Connection state is shown separately from play/pause.

## Time

One neural step is 10 ms of **simulation time**. The world advances at the same
fixed timestep; speed 0.1–5× changes wall-clock scheduling, not the equations.
At most 20 steps execute in a scheduling iteration; if more than 0.5 seconds of
backlog accumulates, wall-clock debt is dropped and an overrun is reported.
Simulation time advances only for executed steps. It never fabricates skipped steps.

For each step t:

1. Deliver currents previously scheduled for t.
2. Recover excitation/inhibition sensitivity toward 1, then apply modulation.
3. Integrate leakage and all inputs, even during refractoriness.
4. Fire eligible neurons; apply the selected post-spike behavior.
5. Schedule outgoing signals at t + delay.
6. Apply motor spikes, collisions, pursuit, physiology and food spawning.
7. Sample sensors for the next neural step.

## LIF semantics

For neuron i, positive and negative direct synaptic arrivals are summed separately:

```
g_E ← clip(1 + (g_E - 1) exp(-dt / tau_E) + gain_E · M_E, 0, 10)
g_I ← clip(1 + (g_I - 1) exp(-dt / tau_I) + gain_I · M_I, 0, 10)
V   ← clip((1 - leak) V + g_E · I_positive + g_I · I_negative
           + I_external + bias + noise_std · Normal(0, 1), v_min, 1e6)
spike ← (V >= threshold) AND (refractory_left == 0 at start of step)
```

The refractory counter decrements each step. A spike sets it to `refractory`;
exactly that many subsequent steps cannot fire. It never blocks integration or
leakage. With refractory = 2, spikes can occur at steps 0, 3, 6, … .

Two post-spike modes:

- `retain` (default for new neurons): leave V unchanged.
- `reset`: set V to **zero**.

No separate refractory potential setting exists. A retained above-threshold
potential can fire again after refractoriness without a new input. Leakage can
also reduce it below threshold first. Leak is a fraction **per step**, noise is
standard deviation **per step**, and threshold/potential/current are dimensionless.
`v_reset` is accepted as legacy metadata but does not affect reset-to-zero behavior.
Legacy v1/v2 neurons migrate to `reset`; new v3 neurons default to `retain`.
Negative/zero thresholds are allowed to preserve old autonomous oscillator examples.

Modulatory arrivals do not directly change V. Their signed weights add to the
corresponding sensitivity channel, scaled by that neuron's gain. Both channels
relax to 1 with independently configurable time constants. Tau is in seconds;
after tau, approximately 37% of the initial displacement from 1 remains. Concurrent
modulation affects direct arrivals in the **same** step. External sensory currents,
bias and noise are not multiplied by synaptic sensitivity.

## Connections and ganglia

An edge has a persistent ID, source neuron, target neuron **or ganglion**, weight,
integer delay in 1…256, and kind: `direct`, `mod_exc`, `mod_inh`.
Parallel edges, self-connections and different edge kinds on the same pair are
supported. A ganglion connector is a targeting alias, not a neuron or relay.
At compile time its incoming connections fan out to explicit member IDs. Each
member receives the full weight, not a weight divided by group size. Membership
is explicit; dragging a neuron outside the drawn circle does not remove it.
A neuron belongs to at most one ganglion.
Dragging a ganglion translates its center and every explicit member atomically,
including members outside its circle. This is a geometry-only edit.

The generator places neurons uniformly by area in a disk (`r = R sqrt(U)`). Each
directed pair is independently connected with the requested probability,
excluding self-edges. It supports either neuron-level E/I polarity (all direct
outgoing weights have the same sign) or edge-level random signs. The E fraction
is a Bernoulli probability, not an exact quota. Geometric skips avoid allocating
an N×N adjacency matrix. An optional maximum Euclidean distance filters eligible
pairs; zero means unlimited. The probability applies within the distance limit.
Inter-ganglion generation uses directed source-member/target-member pairs with
the same probability and distance rules. Existing pairs of the same kind are
skipped. It supports direct and both modulatory kinds; direct signs respect fixed
E/I source polarity, while mixed sources and modulators use the supplied sign.

Structural/parameter edits preserve V, sensitivity, refractory counters, cumulative
counts and random-generator state for surviving neuron IDs, but discard in-flight
currents and reset the displayed rolling statistics. Pure position, label and annotation edits preserve
everything, including in-flight currents. Import/reset restart neural state.

## Sparse execution and limits

Connectivity uses O(E) source/target/weight/delay arrays, no dense N×N matrix.
A delay ring of shape `(max_delay + 1, 4, N)` accumulates delivered currents.
Repeated targets use [`numpy.add.at`](https://numpy.org/doc/stable/reference/generated/numpy.ufunc.at.html),
which accumulates repeated indices. There is no 8,192-pulse truncation from the
old implementation. Each step scans the edge source array to find firing sources;
this is O(E), not an outgoing-CSR event-only algorithm.

Validation limits: 1,000,000 neurons; 500,000 effective edges **after** ganglion
expansion; 200,000 neurons per generated ganglion (radius up to 50,000); 2,500 world objects. The delay
ring can use about 82 MB at 20k neurons and delay 256, excluding edge arrays,
Python topology objects and JSON buffers. The UI memory metric is NumPy arrays
only, not process RSS.

The camera zooms out to 0.0005 (100 times farther than the former 0.05 limit).
Fit includes ganglion boundaries and handles large neuron arrays without spreading
them into function arguments. The background grid adapts to screen-space density.
API import and structural-edit request bodies accept up to 512 MiB.
For 200,000 neurons with unlimited connection distance, probability 0.00001
produces about 400,000 edges on average; the 500,000 effective-edge cap still applies.

CPU uses NumPy. The optional PyTorch backend runs LIF integration, modulation,
refractory handling and delayed scatter-add on Metal/MPS or CUDA. State, parameters,
edges and the delay ring remain on the GPU. It scatters all edge weights masked by
source spikes, avoiding dynamic index selection and extra device synchronizations.
Each step uploads external currents and reads back the boolean spike vector for
CPU world control and group rate bins. Telemetry reads the first 2,000 neurons at
snapshot time. The world, topology editing and seeded noise generation remain on
CPU; noise uses the same NumPy RNG stream when switching devices. This version is
not a fully GPU-resident world or batched simulator.

Switching backends copies all transient arrays (including the delay ring), the
tick and RNG state under the runtime lock, then replaces the kernel only after
the new device has synchronized. World state, history and run/pause state survive.
Structural edits and imports keep the selected device and retain their existing
reset/preservation semantics. Device availability is discovered once per server
process. CPU works without PyTorch. Unsupported selection is rejected; startup
with an unavailable saved device uses CPU and reports the fallback. MPS with
`PYTORCH_ENABLE_MPS_FALLBACK=1` is deliberately unavailable to prevent a GPU label
from hiding unsupported operations executed on CPU.

Both kernels use float32 state. Parallel scatter accumulation and noise arithmetic
can differ by floating-point rounding; close-to-threshold spikes and long
trajectories are not guaranteed bit-identical across devices. Local tests compare
spikes and all transient state over 520 ticks, including maximum-delay arrivals,
both reset modes and modulation. CUDA remains unverified on this MPS-only host.
Timing includes GPU completion, following the
[PyTorch MPS synchronization API](https://docs.pytorch.org/docs/stable/generated/torch.mps.synchronize.html).
See CPU/GPU measurements and their boundaries in `performance.md`.

## World semantics

The arena defaults to 2400×1600 world units and can grow to 12000×12000.
The body has radius 12. Motor spikes translate by `speed * 0.04` units (backward
factor 0.7) and turn by `turn_speed * 0.04` radians. Thus the default 25 Hz motor
firing rate produces the configured speed; changing motor refractory parameters
changes realized speed. Threat speed is a continuous fraction of that configured
nominal speed, not a guarantee to be slower than an idle or weakly driven bug.

Keyboard WASD/arrow control directly overrides motor commands while held, without
injecting neural currents or requiring bindings. It uses configured continuous
speed and shares collision handling. Commands expire after 350 ms without a
heartbeat. On pause only pose and sensor readings change; neural time, physiology,
threats and food spawning remain frozen. Releasing keys returns control to the
network. Focused form inputs do not trigger movement.

Movement is substepped at at most half the body radius to prevent thin-wall
penetration. Sensors use exact ray/AABB intersections; walls block food/threat
visibility. Five lidar rays span −50…50°. Food sectors span −120…+2° and
−2…+120°; threat sectors span −150…0° and 0…+150°. Food and threat signals
are inverse-square and capped to 1; configurable range truncates detection.

Pursuit threats see omnidirectionally within a radius, require line of sight,
and lose interest after a maximum chase duration, lost visibility or bug death.
They then rest for a cooldown before reacquiring. Obstacles block their motion.
They do not perform global path planning. Static threats never move. Threats expire
by lifetime and are replenished toward the target. Manual additions survive until
consumed/expired/deleted; lowering target trims existing objects.

Food spawns one portion per interval toward the target; if zones exist, choose
a zone uniformly and a free point inside it. Spawn attempts are bounded; a full
arena can contain fewer objects than requested. Contact food restores health and
clears hunger. Hunger and fatigue are neural observations; fatigue does not
implicitly scale speed. Movement or turning at full fatigue costs 0.01 health per
simulated second and contributes to cumulative damage. A tick is exhausted if
fatigue is full at its start or after motor activity and recovery. Idle ticks and
fully blocked motion do not incur this damage; paused manual jogging does not
advance physiology. At health zero the bug stops until reset.

## Telemetry and visualization contract

- Rates = actual spikes / neuron count / 0.1 simulated seconds. Whole network and
  each ganglion use their own denominator. History is 300 bins (30 simulated s).
- Cumulative spike counts let both clients observe activity without consuming one
  another's events. Displayed spike flashes aggregate arrivals between frames;
  they are not a complete spike raster or a depiction of precise axonal flight.
- Per-neuron V, gains and counts are streamed for the first 2,000 neurons; this
  limitation is shown in the editor. Aggregate rates include **all** neurons.
- Rendering has at most one scene Canvas and one chart Canvas per window. Scene
  renders at at most 30 Hz, with DPR capped at 2, viewport culling and edge
  decimation above 15,000 drawn edges; decimation is labelled and affects no
  computation. Canvas avoids thousands of continuously mutated DOM elements.
- Native HTML contains forms, keyboard controls, search and neuron lists. Hit tests
  invert the shared camera transform; pointers are captured during drags.
  Zoom buttons provide a non-wheel alternative. Mobile stacks panels under the
  canvas and keeps controls reachable without horizontal scrolling.
- Camera state is local to each interface in localStorage. Experiments live on the
  server and export as portable JSON. The time-series CSV is the same rolling
  aggregate displayed in the graph.

Local Canvas specialist review covers network geometry, world geometry and rate
trace. A fallback for detailed accessibility is the searchable HTML neuron list,
numeric inspector, channel values and CSV; Canvas geometry itself is not exposed
as thousands of screen-reader nodes. UI tests exercise desktop and mobile layouts.

## Persistence boundary

An experiment is **configuration plus a world scene**, not a runtime checkpoint.
Export includes topology, parameters, group membership, bindings, world config,
objects, zones and spawn. It excludes potentials, pending currents, refractory
counters, RNG progress, threat chase progress and rolling telemetry. Import starts
paused with fresh neural/physiology state. `data/project.json` is replaced atomically
after edits or explicit Save; external invalid input is validated before applying.

A failed disk write is reported to the client; simulation state is in memory and
should be exported before closing. Keep JSON exports for named experiments.
Automatic saving is not a history/versioning system. The editor maintains up to
20 local topology undo snapshots; other-window edits are still revision-checked.
