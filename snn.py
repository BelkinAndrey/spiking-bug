"""Leaky-Integrate-and-Fire spiking neural network, vectorized with NumPy.

Features
--------
* Per-neuron noise (Gaussian) -> sub-threshold spiking for sensors.
* Per-synapse delay (integer simulation steps).
* Active "pulses in flight": each spike spawns one pulse per outgoing synapse,
  carrying its weight; pulses are delivered after their delay and exposed for
  visualization (a dot travelling along the synapse).
"""

from __future__ import annotations

import numpy as np


class SpikingNetwork:
    """Vectorized LIF network with delays and in-flight pulses."""

    MAX_DELAY = 64
    MAX_PULSES = 8192

    def __init__(self, capacity: int = 512):
        self.capacity = capacity
        self.n = 0
        self.ids: list[str] = []
        self.id_to_idx: dict[str, int] = {}
        self.meta: dict[str, dict] = {}
        # Visual-only "groups" / frames behind neurons. Persisted in topology.
        self.groups: list[dict] = []

        # LIF state
        self.V = np.zeros(capacity, dtype=np.float32)
        self.threshold = np.ones(capacity, dtype=np.float32)
        self.leak = np.full(capacity, 0.08, dtype=np.float32)
        self.v_reset = np.zeros(capacity, dtype=np.float32)
        self.noise_std = np.zeros(capacity, dtype=np.float32)
        self.refractory_left = np.zeros(capacity, dtype=np.int32)
        self.refractory_period = np.full(capacity, 2, dtype=np.int32)
        self.spikes = np.zeros(capacity, dtype=bool)
        self.spike_count = np.zeros(capacity, dtype=np.int32)

        # Connectivity
        self.W = np.zeros((capacity, capacity), dtype=np.float32)
        self.delay_steps = np.ones((capacity, capacity), dtype=np.int16)

        # Active pulses
        self.pulse_from = np.zeros(self.MAX_PULSES, dtype=np.int32)
        self.pulse_to = np.zeros(self.MAX_PULSES, dtype=np.int32)
        self.pulse_age = np.zeros(self.MAX_PULSES, dtype=np.int32)
        self.pulse_delay = np.ones(self.MAX_PULSES, dtype=np.int32)
        self.pulse_weight = np.zeros(self.MAX_PULSES, dtype=np.float32)
        self.pulse_count = 0

    # ------------------------------------------------------------------ topology

    def add_neuron(
        self,
        nid: str,
        label: str = "",
        kind: str = "inter",
        x: float = 0.0,
        y: float = 0.0,
        threshold: float = 1.0,
        leak: float = 0.08,
        v_reset: float = 0.0,
        refractory: int = 2,
        noise_std: float = 0.0,
    ) -> int:
        if nid in self.id_to_idx:
            raise ValueError(f"neuron {nid} already exists")
        if self.n >= self.capacity:
            raise RuntimeError("network capacity reached")
        idx = self.n
        self.ids.append(nid)
        self.id_to_idx[nid] = idx
        self.meta[nid] = {"label": label or nid, "kind": kind, "x": x, "y": y}
        self.threshold[idx] = threshold
        self.leak[idx] = leak
        self.v_reset[idx] = v_reset
        self.refractory_period[idx] = max(0, int(refractory))
        self.noise_std[idx] = max(0.0, float(noise_std))
        self.V[idx] = 0.0
        self.refractory_left[idx] = 0
        self.spikes[idx] = False
        self.n += 1
        self._invalidate_pulses()
        return idx

    def remove_neuron(self, nid: str) -> None:
        if nid not in self.id_to_idx:
            return
        if self.meta[nid].get("kind") in ("sensor", "motor"):
            raise ValueError("cannot remove default sensor/motor neuron")
        idx = self.id_to_idx[nid]
        last = self.n - 1
        if idx != last:
            self._swap(idx, last)
        self._clear_slot(last)
        last_id = self.ids.pop()
        del self.id_to_idx[last_id]
        del self.meta[last_id]
        self.n -= 1
        self._invalidate_pulses()

    def _swap(self, a: int, b: int) -> None:
        if a == b:
            return
        for arr in (
            self.V, self.threshold, self.leak, self.v_reset,
            self.noise_std, self.refractory_left, self.refractory_period,
            self.spikes, self.spike_count,
        ):
            arr[a], arr[b] = arr[b], arr[a]
        self.W[[a, b], :] = self.W[[b, a], :]
        self.W[:, [a, b]] = self.W[:, [b, a]]
        self.delay_steps[[a, b], :] = self.delay_steps[[b, a], :]
        self.delay_steps[:, [a, b]] = self.delay_steps[:, [b, a]]
        id_a = self.ids[a]
        id_b = self.ids[b]
        self.ids[a], self.ids[b] = id_b, id_a
        self.id_to_idx[id_a] = b
        self.id_to_idx[id_b] = a

    def _clear_slot(self, idx: int) -> None:
        self.V[idx] = 0
        self.threshold[idx] = 1.0
        self.leak[idx] = 0.08
        self.v_reset[idx] = 0
        self.noise_std[idx] = 0
        self.refractory_left[idx] = 0
        self.refractory_period[idx] = 2
        self.spikes[idx] = False
        self.spike_count[idx] = 0
        self.W[idx, :] = 0
        self.W[:, idx] = 0
        self.delay_steps[idx, :] = 1
        self.delay_steps[:, idx] = 1

    def add_synapse(self, from_id: str, to_id: str, weight: float, delay: int = 1) -> None:
        i = self.id_to_idx[to_id]
        j = self.id_to_idx[from_id]
        self.W[i, j] = float(weight)
        self.delay_steps[i, j] = max(1, min(self.MAX_DELAY, int(delay)))
        self._invalidate_pulses()

    def remove_synapse(self, from_id: str, to_id: str) -> None:
        if from_id not in self.id_to_idx or to_id not in self.id_to_idx:
            return
        i = self.id_to_idx[to_id]
        j = self.id_to_idx[from_id]
        self.W[i, j] = 0.0
        self.delay_steps[i, j] = 1
        self._invalidate_pulses()

    def update_neuron(self, nid: str, **params) -> None:
        if nid not in self.id_to_idx:
            return
        idx = self.id_to_idx[nid]
        if "threshold" in params:
            self.threshold[idx] = float(params["threshold"])
        if "leak" in params:
            self.leak[idx] = float(params["leak"])
        if "v_reset" in params:
            self.v_reset[idx] = float(params["v_reset"])
        if "refractory" in params:
            self.refractory_period[idx] = max(0, int(params["refractory"]))
        if "noise_std" in params:
            self.noise_std[idx] = max(0.0, float(params["noise_std"]))
        if "label" in params:
            self.meta[nid]["label"] = params["label"]
        if "x" in params:
            self.meta[nid]["x"] = float(params["x"])
        if "y" in params:
            self.meta[nid]["y"] = float(params["y"])

    def _invalidate_pulses(self) -> None:
        # Easier than reindexing pulses on structural changes.
        self.pulse_count = 0

    # ----------------------------------------------------------- visual groups

    def add_group(self, gid: str, x: float, y: float, w: float, h: float,
                  label: str = "", color: str = "#3a5cff",
                  comment: str = "") -> dict:
        g = {"id": gid, "x": float(x), "y": float(y),
             "w": float(w), "h": float(h),
             "label": str(label), "color": str(color),
             "comment": str(comment)}
        self.groups.append(g)
        return g

    def update_group(self, gid: str, **params) -> None:
        for g in self.groups:
            if g["id"] == gid:
                for k, v in params.items():
                    if k == "id":
                        continue
                    if k in ("x", "y", "w", "h"):
                        g[k] = float(v)
                    else:
                        g[k] = v
                return

    def remove_group(self, gid: str) -> None:
        self.groups = [g for g in self.groups if g["id"] != gid]

    # --------------------------------------------------------------- simulation

    def step(self, external_input: np.ndarray) -> None:
        n = self.n
        if n == 0:
            return

        # 1. Advance & deliver in-flight pulses
        I_syn = np.zeros(n, dtype=np.float32)
        pc = self.pulse_count
        if pc > 0:
            self.pulse_age[:pc] += 1
            delivered = self.pulse_age[:pc] >= self.pulse_delay[:pc]
            if delivered.any():
                tgt = self.pulse_to[:pc][delivered]
                wt  = self.pulse_weight[:pc][delivered]
                # Multiple pulses can target the same neuron, np.add.at handles that
                np.add.at(I_syn, tgt, wt)
                # Compact: keep only undelivered
                keep = np.flatnonzero(~delivered)
                new_pc = keep.size
                if new_pc > 0:
                    self.pulse_from[:new_pc]   = self.pulse_from[:pc][keep]
                    self.pulse_to[:new_pc]     = self.pulse_to[:pc][keep]
                    self.pulse_age[:new_pc]    = self.pulse_age[:pc][keep]
                    self.pulse_delay[:new_pc]  = self.pulse_delay[:pc][keep]
                    self.pulse_weight[:new_pc] = self.pulse_weight[:pc][keep]
                self.pulse_count = new_pc
                pc = new_pc

        # 2. LIF update (with per-neuron Gaussian noise)
        V = self.V[:n]
        thr = self.threshold[:n]
        leak = self.leak[:n]
        reset = self.v_reset[:n]
        refr = self.refractory_left[:n]
        noise_std = self.noise_std[:n]

        noise = np.zeros(n, dtype=np.float32)
        if (noise_std > 0).any():
            noise = noise_std * np.random.standard_normal(n).astype(np.float32)

        in_refr = refr > 0
        V_drive = V * (1.0 - leak) + I_syn + external_input[:n] + noise
        V_next = np.where(in_refr, reset, V_drive)
        refr_next = np.maximum(0, refr - 1)
        new_spikes = (V_next >= thr) & ~in_refr
        V_next = np.where(new_spikes, reset, V_next)
        refr_next = np.where(new_spikes, self.refractory_period[:n], refr_next)

        self.V[:n] = V_next
        self.refractory_left[:n] = refr_next
        self.spikes[:n] = new_spikes
        self.spike_count[:n] += new_spikes

        # 3. Spawn pulses for spiking neurons (one per outgoing non-zero synapse)
        spiking = np.flatnonzero(new_spikes)
        if spiking.size > 0:
            for j in spiking:
                if self.pulse_count >= self.MAX_PULSES:
                    break
                col = self.W[:n, j]
                tgt = np.flatnonzero(col)
                if tgt.size == 0:
                    continue
                avail = self.MAX_PULSES - self.pulse_count
                if tgt.size > avail:
                    tgt = tgt[:avail]
                k = tgt.size
                slc = slice(self.pulse_count, self.pulse_count + k)
                self.pulse_from[slc]   = j
                self.pulse_to[slc]     = tgt
                self.pulse_age[slc]    = 0
                self.pulse_delay[slc]  = np.maximum(1, self.delay_steps[tgt, j].astype(np.int32))
                self.pulse_weight[slc] = col[tgt]
                self.pulse_count += k

    # ------------------------------------------------------------- snapshots

    def snapshot_state(self) -> dict:
        n = self.n
        V = self.V[:n].copy()
        thr = self.threshold[:n].copy()
        with np.errstate(divide="ignore", invalid="ignore"):
            norm = np.where(thr > 0, V / thr, 0.0)
        norm = np.clip(norm, -0.5, 1.0).tolist()
        spikes = self.spike_count[:n].tolist()
        self.spike_count[:n] = 0
        return {
            "ids": list(self.ids),
            "potentials": norm,
            "spike_counts": spikes,
        }

    def snapshot_pulses(self, dt: float) -> dict:
        pc = self.pulse_count
        if pc == 0:
            return {"from_idx": [], "to_idx": [], "progress": [], "duration": [], "sign": []}
        progress = self.pulse_age[:pc].astype(np.float32) / np.maximum(1, self.pulse_delay[:pc])
        progress = np.clip(progress, 0.0, 1.0)
        duration = self.pulse_delay[:pc].astype(np.float32) * float(dt)
        weight = self.pulse_weight[:pc]
        return {
            "from_idx": self.pulse_from[:pc].astype(int).tolist(),
            "to_idx":   self.pulse_to[:pc].astype(int).tolist(),
            "progress": progress.tolist(),
            "duration": duration.tolist(),
            "sign":     np.sign(weight).astype(int).tolist(),
        }

    def topology(self) -> dict:
        n = self.n
        neurons = []
        for i in range(n):
            nid = self.ids[i]
            m = self.meta[nid]
            neurons.append({
                "id": nid,
                "label": m.get("label", nid),
                "kind": m.get("kind", "inter"),
                "x": m.get("x", 0.0),
                "y": m.get("y", 0.0),
                "threshold": float(self.threshold[i]),
                "leak": float(self.leak[i]),
                "v_reset": float(self.v_reset[i]),
                "refractory": int(self.refractory_period[i]),
                "noise_std": float(self.noise_std[i]),
            })
        synapses = []
        nz = np.argwhere(self.W[:n, :n] != 0)
        for to_i, from_i in nz:
            synapses.append({
                "from": self.ids[from_i],
                "to": self.ids[to_i],
                "weight": float(self.W[to_i, from_i]),
                "delay": int(self.delay_steps[to_i, from_i]),
            })
        return {
            "neurons":  neurons,
            "synapses": synapses,
            "groups":   [dict(g) for g in self.groups],
        }

    def to_json(self) -> dict:
        return self.topology()

    def load_json(self, data: dict, preserved_kinds: set | None = None) -> None:
        preserved_kinds = preserved_kinds or set()
        self.n = 0
        self.ids.clear()
        self.id_to_idx.clear()
        self.meta.clear()
        self.V[:] = 0
        self.threshold[:] = 1.0
        self.leak[:] = 0.08
        self.v_reset[:] = 0
        self.noise_std[:] = 0
        self.refractory_left[:] = 0
        self.refractory_period[:] = 2
        self.spikes[:] = False
        self.spike_count[:] = 0
        self.W[:] = 0
        self.delay_steps[:] = 1
        self.pulse_count = 0
        self.groups = []

        for grec in data.get("groups", []):
            try:
                self.add_group(
                    grec.get("id") or f"g{len(self.groups)}",
                    grec.get("x", 0), grec.get("y", 0),
                    grec.get("w", 100), grec.get("h", 80),
                    label=grec.get("label", ""),
                    color=grec.get("color", "#3a5cff"),
                    comment=grec.get("comment", ""),
                )
            except (KeyError, TypeError):
                continue

        for nrec in data.get("neurons", []):
            nid = nrec["id"]
            kind = nrec.get("kind", "inter")
            if nid in preserved_kinds:
                kind = preserved_kinds_map(nid)
            self.add_neuron(
                nid=nid,
                label=nrec.get("label", nid),
                kind=kind,
                x=nrec.get("x", 0.0),
                y=nrec.get("y", 0.0),
                threshold=nrec.get("threshold", 1.0),
                leak=nrec.get("leak", 0.08),
                v_reset=nrec.get("v_reset", 0.0),
                refractory=nrec.get("refractory", 2),
                noise_std=nrec.get("noise_std", 0.0),
            )
        for s in data.get("synapses", []):
            try:
                self.add_synapse(
                    s["from"], s["to"],
                    s.get("weight", 1.0),
                    delay=s.get("delay", 1),
                )
            except KeyError:
                continue


def preserved_kinds_map(nid: str) -> str:
    if nid.startswith("sensor_") or nid.startswith("lidar_"):
        return "sensor"
    if nid.startswith("motor_"):
        return "motor"
    return "inter"
