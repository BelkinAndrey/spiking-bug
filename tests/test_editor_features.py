import copy
import math
import unittest
from unittest.mock import patch
import numpy as np
from server.schema import topology
from server.generators import ganglion, connect_ganglia
from server.runtime import Runtime


def fixture():
    ns = [
        dict(id=f"{g}{i}", x=x + i * 10, y=200, polarity="exc" if i == 0 else "inh")
        for g, x in [("a", 100), ("b", 300)]
        for i in range(3)
    ]
    gs = [
        dict(id=g, label=g, x=x, y=200, radius=60, members=[f"{g}{i}" for i in range(3)])
        for g, x in [("a", 110), ("b", 310)]
    ]
    return topology(dict(format_version=3, neurons=ns, synapses=[], ganglia=gs))


class GenerationTests(unittest.TestCase):
    def test_distance_is_an_upper_bound_and_zero_is_unlimited(self):
        empty = topology(dict(neurons=[]))
        params = dict(id="g", count=40, seed=42, density=1, radius=100, max_distance=25)
        net = ganglion(empty, params)
        nodes = {n["id"]: n for n in net["neurons"]}
        self.assertGreater(len(net["synapses"]), 0)
        self.assertLess(len(net["synapses"]), 40 * 39)
        for s in net["synapses"]:
            a, b = nodes[s["source"]], nodes[s["target"]]
            self.assertLessEqual(math.hypot(a["x"] - b["x"], a["y"] - b["y"]), 25)
        self.assertEqual(net, ganglion(empty, params))
        self.assertEqual(len(ganglion(empty, {**params, "max_distance": 0})["synapses"]), 40 * 39)

    def test_projection_type_direction_density_and_duplicates(self):
        net = fixture()
        params = dict(source="a", target="b", kind="mod_inh", weight=-0.4, delay=3, density=1)
        result = connect_ganglia(net, params)
        self.assertEqual(len(result["synapses"]), 9)
        for s in result["synapses"]:
            self.assertTrue(s["source"].startswith("a") and s["target"].startswith("b"))
            self.assertEqual((s["kind"], s["weight"], s["delay"]), ("mod_inh", -0.4, 3))
        self.assertEqual(connect_ganglia(result, params), result)
        self.assertEqual(connect_ganglia(net, {**params, "density": 0})["synapses"], [])
        self.assertEqual(connect_ganglia(net, {**params, "max_distance": 100})["synapses"], [])
        with self.assertRaises(ValueError):
            connect_ganglia(net, {**params, "target": "a"})

    def test_projection_respects_direct_source_polarity(self):
        result = connect_ganglia(fixture(), dict(source="a", target="b", density=1, weight=-0.8))
        for s in result["synapses"]:
            self.assertEqual(s["weight"], 0.8 if s["source"] == "a0" else -0.8)

    def test_projection_seed_and_sparse_probability(self):
        net = fixture()
        params = dict(source="a", target="b", density=0.4, seed=7)
        self.assertEqual(connect_ganglia(net, params), connect_ganglia(net, params))
        self.assertGreater(len(connect_ganglia(net, params)["synapses"]), 0)
        self.assertLess(len(connect_ganglia(net, params)["synapses"]), 9)

    def test_projection_filters_both_ends_for_every_connection_kind(self):
        net = fixture()
        net["neurons"][2]["polarity"] = "mixed"
        net["neurons"][-1]["polarity"] = "mixed"
        choices = {"any": (0, 1, 2), "exc": (0,), "inh": (1,)}
        for kind in ("direct", "mod_exc", "mod_inh"):
            params = dict(source="a", target="b", kind=kind, density=1, weight=-0.8)
            for source_polarity, sources in choices.items():
                for target_polarity, targets in choices.items():
                    with self.subTest(kind=kind, source=source_polarity, target=target_polarity):
                        filtered = {
                            **params,
                            "source_polarity": source_polarity,
                            "target_polarity": target_polarity,
                        }
                        result = connect_ganglia(net, filtered)
                        self.assertEqual(
                            {(s["source"], s["target"]) for s in result["synapses"]},
                            {(f"a{src}", f"b{dst}") for src in sources for dst in targets},
                        )
                        for s in result["synapses"]:
                            self.assertEqual(
                                s["weight"],
                                0.8 if kind == "direct" and s["source"] == "a0" else -0.8,
                            )
                        self.assertEqual(connect_ganglia(result, filtered), result)
            self.assertEqual(
                connect_ganglia(net, params),
                connect_ganglia(
                    net, {**params, "source_polarity": "any", "target_polarity": "any"}
                ),
            )

    def test_projection_filters_empty_and_invalid(self):
        net = fixture()
        for n in net["neurons"]:
            n["polarity"] = "mixed"
        params = dict(source="a", target="b", density=1)
        for key in ("source_polarity", "target_polarity"):
            for polarity in ("exc", "inh"):
                self.assertEqual(connect_ganglia(net, {**params, key: polarity}), net)
            with self.assertRaises(ValueError):
                connect_ganglia(net, {**params, key: "invalid"})


class RuntimeEditingTests(unittest.TestCase):
    def test_ganglion_move_is_atomic_preserves_state_and_only_moves_members(self):
        r = Runtime()
        r.command("topology", fixture(), r.revision)
        r.net.queue.fill(0.2)
        r.net.V.fill(0.3)
        before = copy.deepcopy(r.net.topology)
        queue = r.net.queue.copy()
        session = r.session
        r.command("move_ganglion", dict(id="a", dx=50, dy=-10), r.revision)
        for a, b in zip(before["neurons"], r.net.topology["neurons"]):
            delta = (50, -10) if a["id"].startswith("a") else (0, 0)
            self.assertEqual((b["x"] - a["x"], b["y"] - a["y"]), delta)
        self.assertEqual(r.net.topology["ganglia"][0]["x"], 160)
        np.testing.assert_array_equal(r.net.queue, queue)
        np.testing.assert_allclose(r.net.V, 0.3)
        self.assertEqual(r.session, session)
        before = copy.deepcopy(r.net.topology)
        with self.assertRaises(ValueError):
            r.command("move_ganglion", dict(id="a", dx=100000, dy=0), r.revision)
        self.assertEqual(before, r.net.topology)

    def test_paused_manual_control_needs_no_motor_binding_and_releases(self):
        r = Runtime()
        r.bindings = {}
        start = copy.deepcopy(r.world.agent)
        v = r.net.V.copy()
        r.command("manual", dict(forward=True))
        for _ in range(10):
            r.jog(0.01)
        self.assertGreater(r.world.agent["x"], start["x"])
        self.assertEqual(r.ticks, 0)
        self.assertEqual(r.world.elapsed, 0)
        np.testing.assert_array_equal(r.net.V, v)
        r.command("manual", {})
        x = r.world.agent["x"]
        r.jog(0.01)
        self.assertEqual(r.world.agent["x"], x)
        r.command("manual", dict(forward=True))
        with patch("server.runtime.time.monotonic", return_value=r.manual_until + 1):
            r.jog(0.01)
        self.assertEqual(r.world.agent["x"], x)

    def test_manual_overrides_opposing_neural_motors(self):
        r = Runtime()
        r.world.config["food_target"] = 0
        r.world.config["threat_target"] = 0
        r.world.objects = []
        for n in r.net.topology["neurons"]:
            n["bias"] = 2 if n["id"] == "motor_backward" else 0
        r._replace_net(r.net.topology, False)
        start = r.world.agent["x"]
        r.command("manual", dict(forward=True))
        r.step()
        self.assertGreater(r.world.agent["x"], start)
