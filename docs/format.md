# Experiment JSON and HTTP API

`GET /api/export` returns an experiment. `GET /api/project` returns the same schema
with current revision. Minimal example:

```json
{
  "version": 1,
  "name": "Minimal oscillator",
  "topology": {
    "format_version": 3,
    "task": "BUG",
    "neurons": [
      {"id": "clock", "x": 100, "y": 100, "bias": 0.2, "leak": 0.02},
      {"id": "motor", "kind": "motor", "x": 400, "y": 100, "refractory": 3}
    ],
    "synapses": [
      {"id": "s1", "source": "clock", "target": "motor", "kind": "direct", "weight": 1, "delay": 2}
    ],
    "ganglia": [],
    "groups": []
  },
  "bindings": {"forward": "motor"},
  "world": {
    "config": {"width": 2400, "height": 1600, "seed": 42},
    "spawn": {"x": 300, "y": 800, "heading": 0},
    "objects": [{"kind": "obstacle", "x": 900, "y": 400, "w": 30, "h": 400}],
    "zones": [{"x": 1200, "y": 600, "w": 400, "h": 400}]
  }
}
```

Defaults and validated ranges live in `server/schema.py`; runtime TypeScript
interfaces are in `packages/ui/types.ts`. Missing bindings mean disconnected
channels. Neuron ID strings are stable across clients. Object IDs are regenerated
when a scene is imported; neural IDs are not.

## Neuron fields

`id`, `label`, `kind` (`sensor`, `motor`, `inter`), `x`, `y`, `threshold`, `leak`,
`v_min`, `refractory`, `noise_std`, `bias`, `reset_mode` (`retain` or `reset`),
`mod_tau_exc`, `mod_tau_inh`, `mod_gain_exc`, `mod_gain_inh`, `polarity`
(`mixed`, `exc`, `inh`). Kind affects visual classification; **bindings** determine
actual sensor/motor function. `v_reset` is retained only as legacy metadata.

## Ganglion

`id`, `label`, `x`, `y`, `radius`, `members` (neuron IDs). Its ID can be a synapse
target, never a source. Empty ganglia and overlapping memberships are rejected.
Deleting selected neurons removes their connections and memberships and disconnects
any bound channels in one edit. IDs share a namespace with ganglia.

## Legacy import

A bare topology with `neurons`, `synapses` and optional `groups` is accepted.
Synapse `from`/`to` migrate to `source`/`target`; missing edge IDs are assigned.
Missing kind becomes `direct`; v1/v2 neurons default to zero-reset behavior.
The old BUG channel names are bound when matching IDs exist; missing IDs stay
unassigned. Unsupported tasks and future format versions are rejected before
changing the active project.

## Commands

`POST /api/command`, JSON body:

```json
{"action":"bindings","revision":1,"data":{"forward":"motor"}}
```

The returned revision is authoritative. Configuration commands other than `save` require the latest
revision. Refresh on HTTP 409 and retry intentionally; do not silently replay old
full-topology edits. Invalid inputs return HTTP 400, unexpected errors HTTP 500.

| Action | Data | Effect |
|---|---|---|
| `control` | `mode: play / pause / step / reset` | Shared simulation controls; no revision needed |
| `speed` | `value: 0.1…5` | Wall-clock tempo; no revision needed |
| `compute` | `device: cpu / mps / cuda:N` | Switch kernel while preserving full runtime state; requires current revision |
| `manual` | `forward/backward/left/right: bool` | Direct movement overriding motor spikes while held; also works paused; expires after 350 ms |
| `inject` | `id, current` | One external input on next executed step |
| `topology` | full v3 topology | Validated topology replacement |
| `positions` | `positions: [{id,x,y}]` | Geometry-only edits, preserves pending currents |
| `move_ganglion` | `id,dx,dy` | Translate group and every explicit member, preserving neural runtime state |
| `ganglion` | `id,label,x,y,radius,count,density,max_distance,excitatory,mode,weight,delay,seed,neuron` | Append seeded generated group; distance 0 means unlimited |
| `connect_ganglia` | `id,source,target,source_polarity,target_polarity,kind,density,weight,delay,seed,max_distance` | Seeded directed member-to-member edges; `source_polarity` and `target_polarity` independently accept `any` (default, includes mixed), `exc`, or `inh`; returns `added_synapses`; distance 0 means unlimited |
| `bindings` | channel → neuron ID or empty string | Replace all bindings |
| `new_document` | empty object | Replace the neural document with the default 17-neuron network and channel bindings; pause and reset neural activity; preserve the current arena and compute device |
| `world_config` | subset of world config | Validate and update settings |
| `place` | `kind,x,y` and `w,h` for obstacle | Add one world object |
| `zone` | `x,y,w,h` | Add food spawn zone |
| `remove` | `id` | Delete world object or zone |
| `clear` | `kind: food / threat / obstacle / zone` | Clear category |
| `spawn` | `x,y` | Move spawn and reset bug physiology |
| `maze` | `cols,rows,seed` | Replace world objects/zones, connected maze |
| `import` | experiment or legacy topology | Replace validated experiment, pause |
| `save` | `{}` | Persist current scene |
| `name` | `name` | Rename experiment |

`GET /api/events` is an SSE stream at 15 Hz. Each snapshot includes simulation time,
world, activity, rolling rate history, revision and measured kernel/world step
latency. `GET /api/state` provides a single snapshot. There is no client-specific
consumption of cumulative spike counts.

`GET /api/devices` returns `devices: [{id,label,available,reason}]`, active `device`
and a startup fallback `notice`. Discovery describes the server's hardware, not
the browser's. Unavailable selections are rejected without changing the kernel.
Snapshots contain `compute: {device,notice}` and the actual `stats.backend`.
Saved experiments include `compute: {device}` for restart preference; import into
a running server keeps that server's selected device. Startup on an unavailable
saved device falls back to CPU with a visible notice. A normal CPU installation
does not require PyTorch; install `requirements-gpu.txt` and restart to add GPU.

## Script-generated worlds

Run `python scripts/create_experiment.py --seed 23 --output experiment.json`,
then import the JSON into either client. This demonstrates the public format;
script execution is outside the web server. The world JSON dialog accepts data,
never executes Python or JavaScript, and replaces the scene on Apply.
