"""Sparse PyTorch LIF kernel on MPS/CUDA, with persistent device-resident state."""

import numpy as np
import torch
from .engine import Network


class GPUNetwork(Network):
    def __init__(self, topology, seed=42, device="mps"):
        super().__init__(topology, seed)
        self.device = device
        self.backend = f"PyTorch · {'Metal/MPS' if device == 'mps' else device.upper()}"
        # Keep topology, group membership and the reproducible noise RNG on the host.
        for key, value in list(vars(self).items()):
            if isinstance(value, np.ndarray):
                setattr(self, key, torch.as_tensor(value.copy(), device=device))
        self.sources = self.sources.long()
        self.targets = self.targets.long()
        self.edge_channels = self.edge_channels.long()
        self.delays = self.delays.long()
        self.synchronize()

    @torch.no_grad()
    def step(self, external=None):
        slot = self.tick % self.slots
        due = self.queue[slot].clone()
        self.queue[slot].zero_()
        self.sensitivity = 1 + (self.sensitivity - 1) * self.recovery
        self.sensitivity[:, 0] += due[2] * self.mod_gain_exc
        self.sensitivity[:, 1] += due[3] * self.mod_gain_inh
        self.sensitivity.clamp_(0, 10)
        refractory = self.refr > 0
        drive = (
            self.V * (1 - self.leak)
            + due[0] * self.sensitivity[:, 0]
            + due[1] * self.sensitivity[:, 1]
            + self.bias
        )
        if external is not None:
            drive += torch.as_tensor(np.asarray(external, dtype=np.float32), device=self.device)
        if self.noisy:
            # Same NumPy generator as CPU: switching devices keeps the random stream.
            noise = self.rng.normal(size=self.n).astype(np.float32)
            drive += torch.as_tensor(noise, device=self.device) * self.noise_std
        self.V = torch.minimum(torch.maximum(drive, self.v_min), drive.new_tensor(1e6))
        self.refr = (self.refr - 1).clamp_min_(0)
        self.spikes = (self.V >= self.threshold) & ~refractory
        self.total += self.spikes
        self.V = torch.where(self.spikes & (self.reset_mode == 0), 0.0, self.V)
        self.refr = torch.where(self.spikes, self.refractory.to(torch.int32), self.refr)
        # Fixed-size scatter avoids a GPU->CPU synchronization for dynamic nonzero counts.
        slots = (self.tick + self.delays) % self.slots
        indices = (slots * 4 + self.edge_channels) * self.n + self.targets
        self.queue.view(-1).scatter_add_(0, indices, self.weights * self.spikes[self.sources])
        self.tick += 1
        # World motors and aggregate rate bins consume spikes on CPU; potentials and
        # delayed currents stay on GPU. This transfer also completes the timed step.
        result = self.spikes.cpu().numpy().copy()
        self.synchronize()
        return result

    def host_values(self, key, limit=None):
        value = getattr(self, key)
        if limit is not None:
            value = value[:limit]
        return value.detach().cpu().numpy().copy()

    def set_values(self, key, value):
        tensor = getattr(self, key)
        tensor.copy_(torch.as_tensor(value, dtype=tensor.dtype, device=self.device))

    def synchronize(self):
        if self.device == "mps":
            torch.mps.synchronize()
        else:
            torch.cuda.synchronize(self.device)

    @property
    def memory_bytes(self):
        return sum(
            v.numel() * v.element_size() for v in vars(self).values() if isinstance(v, torch.Tensor)
        )
