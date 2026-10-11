"""Numerical contract and lossless backend handover on every local accelerator."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from server.app import create_app
from server.devices import create_network, devices
from server.engine import Network
from server.runtime import Runtime
from server.schema import topology

ACCELERATORS = [d["id"] for d in devices() if d["available"] and d["id"] != "cpu"]


def fixture():
    return topology(
        dict(
            format_version=3,
            neurons=[
                dict(id="source", reset_mode="reset", leak=0, refractory=2),
                dict(id="retain", leak=0.125, refractory=3),
                dict(id="reset", leak=0.125, refractory=3, reset_mode="reset"),
                dict(id="e", threshold=100, mod_tau_exc=0.04, mod_gain_exc=0.25),
                dict(id="i", threshold=100, mod_tau_inh=0.07, mod_gain_inh=0.5),
            ],
            ganglia=[dict(id="g", x=0, y=0, radius=100, members=["e", "i"])],
            synapses=[
                dict(source="source", target="g", kind="mod_exc", weight=0.75, delay=1),
                dict(source="source", target="g", kind="mod_inh", weight=-0.25, delay=3),
                dict(source="source", target="e", weight=0.5, delay=2),
                dict(source="source", target="e", weight=0.25, delay=2),
                dict(source="source", target="i", weight=-0.5, delay=2),
                dict(source="source", target="i", weight=0.125, delay=256),
            ],
        )
    )


class DeviceAPITests(unittest.TestCase):
    def test_discovery_and_invalid_switch_are_read_only(self):
        rt = Runtime()
        client = create_app(rt).test_client()
        options = client.get("/api/devices").json
        self.assertEqual(options["device"], "cpu")
        self.assertTrue(options["devices"][0]["available"])
        rt.step()
        before, net = copy.deepcopy(rt.snapshot()), rt.net
        response = client.post(
            "/api/command",
            json=dict(action="compute", data=dict(device="nonexistent"), revision=rt.revision),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIs(rt.net, net)
        self.assertEqual(rt.snapshot(), before)
        response = client.post(
            "/api/command",
            json=dict(action="compute", data=dict(device="cpu"), revision=rt.revision - 1),
        )
        self.assertEqual(response.status_code, 409)

    def test_unavailable_saved_device_falls_back_visibly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            p = Runtime().project()
            p["compute"] = dict(device="cuda:999")
            path.write_text(json.dumps(p))
            rt = Runtime(path)
            self.assertEqual(rt.net.device, "cpu")
            self.assertIn("cuda:999", rt.snapshot()["compute"]["notice"])
            self.assertFalse(rt.running)

    def test_missing_torch_does_not_break_cpu(self):
        devices.cache_clear()
        try:
            with patch.dict("sys.modules", {"torch": None}):
                options = devices()
                self.assertTrue(options[0]["available"])
                self.assertFalse(any(d["available"] for d in options[1:]))
                self.assertIsInstance(create_network(fixture()), Network)
                with self.assertRaises(ValueError):
                    create_network(fixture(), device="mps")
        finally:
            devices.cache_clear()


@unittest.skipUnless(ACCELERATORS, "No available GPU on this test host")
class GPUContractTests(unittest.TestCase):
    def assert_state_close(self, a, b):
        for key in Network.state_fields:
            np.testing.assert_allclose(
                a.host_values(key), b.host_values(key), rtol=2e-5, atol=2e-5, err_msg=key
            )

    def test_lif_modulation_delays_and_fanout_match_cpu(self):
        for device in ACCELERATORS:
            with self.subTest(device=device):
                cpu, gpu = create_network(fixture()), create_network(fixture(), device=device)
                for tick in range(520):
                    external = np.array(
                        [2 if tick % 7 == 0 else 0, 2 if tick == 0 else 0, 0.25, 0, 0], np.float32
                    )
                    np.testing.assert_array_equal(cpu.step(external), gpu.step(external))
                    self.assert_state_close(cpu, gpu)
                self.assertEqual(gpu.V.device.type, device.split(":")[0])

    def test_noise_and_empty_network(self):
        for device in ACCELERATORS:
            empty = create_network(topology(dict(neurons=[])), device=device)
            self.assertEqual(len(empty.step()), 0)
            net = topology(
                dict(format_version=3, neurons=[dict(id="n", noise_std=0.1, threshold=100)])
            )
            cpu, gpu = create_network(net), create_network(net, device=device)
            for _ in range(100):
                cpu.step()
                gpu.step()
            self.assert_state_close(cpu, gpu)
            self.assertEqual(cpu.rng.bit_generator.state, gpu.rng.bit_generator.state)

    def test_switch_preserves_pending_events_world_history_and_rng(self):
        for device in ACCELERATORS:
            rt = Runtime()
            rt.command("topology", fixture(), rt.revision)
            for _ in range(15):
                rt.step()
            rt.net.step(np.array([2, 0, 0, 0, 0], np.float32))
            rt.running = True
            before = {k: rt.net.host_values(k) for k in Network.state_fields}
            tick, rng = rt.net.tick, copy.deepcopy(rt.net.rng.bit_generator.state)
            history, world = list(rt.history), copy.deepcopy(rt.world.snapshot())
            for next_device in (device, "cpu"):
                rt.command("compute", dict(device=next_device), rt.revision)
                for key, value in before.items():
                    np.testing.assert_array_equal(value, rt.net.host_values(key))
                self.assertEqual(rt.net.tick, tick)
                self.assertEqual(rt.net.rng.bit_generator.state, rng)
                self.assertEqual(list(rt.history), history)
                self.assertEqual(rt.world.snapshot(), world)
                self.assertTrue(rt.running)

    def test_gpu_survives_edits_import_reset_and_persistence(self):
        for device in ACCELERATORS:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "p.json"
                rt = Runtime(path)
                rt.command("compute", dict(device=device), rt.revision)
                for _ in range(10):
                    rt.step()
                before = rt.net.host_values("V")
                net = copy.deepcopy(rt.net.topology)
                net["neurons"].append(dict(id="new"))
                rt.command("topology", net, rt.revision)
                np.testing.assert_array_equal(before, rt.net.host_values("V")[:-1])
                rt.command("control", dict(mode="reset"))
                self.assertEqual(rt.net.device, device)
                np.testing.assert_array_equal(rt.net.host_values("V"), 0)
                rt.command("import", rt.project(), rt.revision)
                self.assertEqual(rt.net.device, device)
                restarted = Runtime(path)
                self.assertEqual(restarted.net.device, device)
                rt.step()
                self.assertIn("PyTorch", rt.snapshot()["stats"]["backend"])
