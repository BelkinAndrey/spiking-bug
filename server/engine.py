"""Sparse delayed LIF runtime. No dense N×N matrices or bounded pulse loss."""

from __future__ import annotations
import numpy as np
from .schema import DT, KINDS


class Network:
    def __init__(self, topology, seed=42):
        self.topology = topology
        ns = topology["neurons"]
        self.ids = [n["id"] for n in ns]
        self.index = {nid: i for i, nid in enumerate(self.ids)}
        self.n = len(ns)
        self.rng = np.random.default_rng(seed)
        for key in (
            "threshold",
            "leak",
            "v_reset",
            "v_min",
            "refractory",
            "noise_std",
            "bias",
            "mod_gain_exc",
            "mod_gain_inh",
        ):
            setattr(self, key, np.array([n[key] for n in ns], dtype=np.float32))
        self.recovery = np.array(
            [[np.exp(-DT / n["mod_tau_exc"]), np.exp(-DT / n["mod_tau_inh"])] for n in ns],
            dtype=np.float32,
        ).reshape(self.n, 2)
        self.reset_mode = np.array([("reset", "retain").index(n["reset_mode"]) for n in ns])
        self.V = np.zeros(self.n, np.float32)
        self.sensitivity = np.ones((self.n, 2), np.float32)
        self.refr = np.zeros(self.n, np.int32)
        self.spikes = np.zeros(self.n, bool)
        self.total = np.zeros(self.n, np.int64)
        self.tick = 0
        self.groups = {
            g["id"]: np.array([self.index[m] for m in g["members"]], dtype=np.int32)
            for g in topology["ganglia"]
        }
        sources = []
        targets = []
        weights = []
        delays = []
        kinds = []
        for s in topology["synapses"]:
            target = (
                self.groups[s["target"]]
                if s["target"] in self.groups
                else [self.index[s["target"]]]
            )
            for t in target:
                sources.append(self.index[s["source"]])
                targets.append(t)
                weights.append(s["weight"])
                delays.append(s["delay"])
                kinds.append(KINDS.index(s["kind"]))
        self.sources = np.array(sources, np.int32)
        self.targets = np.array(targets, np.int32)
        self.weights = np.array(weights, np.float32)
        self.delays = np.array(delays, np.int32)
        self.kinds = np.array(kinds, np.int8)
        self.slots = int(max(delays, default=1)) + 1
        # Delay ring stores aggregated currents, not individual pulse objects.
        # Channels: positive, negative, excitation modulation, inhibition modulation.
        self.queue = np.zeros((self.slots, 4, self.n), np.float32)
        self.edge_channels = np.where(
            self.kinds > 0, self.kinds + 1, np.where(self.weights >= 0, 0, 1)
        )
        self.noisy = bool(np.any(self.noise_std))

    def step(self, external=None):
        due = self.queue[self.tick % self.slots].copy()
        self.queue[self.tick % self.slots].fill(0)
        self.sensitivity = 1 + (self.sensitivity - 1) * self.recovery
        self.sensitivity[:, 0] += due[2] * self.mod_gain_exc
        self.sensitivity[:, 1] += due[3] * self.mod_gain_inh
        np.clip(self.sensitivity, 0, 10, out=self.sensitivity)
        refractory = self.refr > 0
        drive = (
            self.V * (1 - self.leak)
            + due[0] * self.sensitivity[:, 0]
            + due[1] * self.sensitivity[:, 1]
            + self.bias
        )
        if external is not None:
            drive += external
        if self.noisy:
            drive += self.rng.normal(size=self.n) * self.noise_std
        self.V = drive.astype(np.float32)
        np.clip(self.V, self.v_min, 1e6, out=self.V)
        self.refr = np.maximum(0, self.refr - 1)
        self.spikes = (self.V >= self.threshold) & ~refractory
        self.total += self.spikes
        self.V = np.where(self.spikes & (self.reset_mode == 0), 0.0, self.V)
        self.refr[self.spikes] = self.refractory[self.spikes].astype(np.int32)
        active = self.spikes[self.sources]
        if np.any(active):
            slots = (self.tick + self.delays[active]) % self.slots
            np.add.at(
                self.queue,
                (slots, self.edge_channels[active], self.targets[active]),
                self.weights[active],
            )
        self.tick += 1
        return self.spikes

    @property
    def memory_bytes(self):
        return sum(v.nbytes for v in vars(self).values() if isinstance(v, np.ndarray))
