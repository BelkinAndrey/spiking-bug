import unittest
import numpy as np
from server.schema import topology, DT
from server.engine import Network


def network(neurons, synapses=(), ganglia=()):
    return Network(
        topology(
            dict(format_version=3, neurons=neurons, synapses=list(synapses), ganglia=list(ganglia))
        )
    )


class LIFTests(unittest.TestCase):
    def test_retain_default_repeats_without_new_input(self):
        n = network([dict(id="a", leak=0, refractory=2)])
        result = [bool(n.step(np.array([2 if i == 0 else 0]))[0]) for i in range(7)]
        self.assertEqual(result, [True, False, False, True, False, False, True])
        self.assertEqual(n.V[0], 2)

    def test_leak_and_inputs_continue_during_refractory(self):
        n = network([dict(id="a", leak=0.5, refractory=2)])
        n.step(np.array([2.0]))
        self.assertEqual(n.V[0], 2)
        n.step(np.array([0.25]))
        self.assertEqual(n.V[0], 1.25)
        n.step()
        self.assertAlmostEqual(n.V[0], 0.625)
        n.step()
        self.assertFalse(n.spikes[0])
        self.assertAlmostEqual(n.V[0], 0.3125)

    def test_reset_is_zero_and_then_integrates_while_refractory(self):
        n = network([dict(id="a", leak=0, refractory=2, reset_mode="reset", v_reset=7)])
        n.step(np.array([2.0]))
        self.assertEqual(n.V[0], 0)
        n.step(np.array([0.6]))
        n.step(np.array([0.6]))
        self.assertFalse(n.spikes[0])
        n.step()
        self.assertTrue(n.spikes[0])
        self.assertEqual(n.V[0], 0)

    def test_delay_and_coincident_events_are_exact(self):
        n = network(
            [
                dict(id="a", reset_mode="reset"),
                dict(id="b", reset_mode="reset"),
                dict(id="c", threshold=10, leak=0),
            ],
            [
                dict(source="a", target="c", weight=0.7, delay=2),
                dict(source="b", target="c", weight=0.6, delay=2),
            ],
        )
        n.step(np.array([1, 1, 0]))
        self.assertEqual(n.V[2], 0)
        n.step()
        self.assertEqual(n.V[2], 0)
        n.step()
        self.assertAlmostEqual(n.V[2], 1.3, places=6)

    def test_modulation_only_changes_requested_gain(self):
        n = network(
            [dict(id="a", reset_mode="reset"), dict(id="b", leak=0, threshold=100)],
            [dict(source="a", target="b", kind="mod_exc", weight=1, delay=1)],
        )
        n.step(np.array([1, 0]))
        n.step()
        self.assertEqual(n.V[1], 0)
        self.assertEqual(n.sensitivity[1, 0], 2)
        self.assertEqual(n.sensitivity[1, 1], 1)
        n.step()
        self.assertAlmostEqual(n.sensitivity[1, 0], 1 + np.exp(-DT / 2), places=6)

    def test_separate_excitation_and_inhibition_gains(self):
        n = network(
            [dict(id="a", reset_mode="reset"), dict(id="b", threshold=100, leak=0)],
            [
                dict(source="a", target="b", kind="mod_inh", weight=2),
                dict(source="a", target="b", weight=-1),
                dict(source="a", target="b", weight=2),
            ],
        )
        n.step(np.array([1, 0]))
        n.step()
        self.assertEqual(n.sensitivity[1, 1], 3)
        self.assertEqual(n.V[1], -1)

    def test_gain_clamps_and_recovery(self):
        n = network(
            [dict(id="a", reset_mode="reset"), dict(id="b")],
            [dict(source="a", target="b", kind="mod_exc", weight=-5)],
        )
        n.step(np.array([1, 0]))
        n.step()
        self.assertEqual(n.sensitivity[1, 0], 0)
        n.step()
        self.assertGreater(n.sensitivity[1, 0], 0)

    def test_ganglion_connector_fanout(self):
        n = network(
            [dict(id=x) for x in ("a", "b", "c")],
            [dict(source="a", target="g", kind="mod_inh", weight=0.5)],
            [dict(id="g", label="G", x=0, y=0, radius=100, members=["b", "c"])],
        )
        n.step(np.array([1, 0, 0]))
        n.step()
        np.testing.assert_array_equal(n.sensitivity[:, 1], [1, 1.5, 1.5])
        self.assertEqual(len(n.V), 3)

    def test_no_pulse_cap_loss(self):
        ns = [dict(id="a", reset_mode="reset")] + [
            dict(id=f"n{i}", leak=0, threshold=10) for i in range(9000)
        ]
        n = network(ns, [dict(source="a", target=f"n{i}", weight=0.5) for i in range(9000)])
        ext = np.zeros(9001)
        ext[0] = 1
        n.step(ext)
        n.step()
        np.testing.assert_array_equal(n.V[1:], np.full(9000, 0.5))

    def test_rng_is_reproducible(self):
        ns = [dict(id="a", noise_std=0.1)]
        a = network(ns)
        b = network(ns)
        for _ in range(20):
            a.step()
            b.step()
        np.testing.assert_array_equal(a.V, b.V)

    def test_empty_network(self):
        n = network([])
        self.assertEqual(len(n.step()), 0)


if __name__ == "__main__":
    unittest.main()


class DelayBoundaryTests(unittest.TestCase):
    def test_max_delay_arrives_once_across_ring_boundary(self):
        n = network(
            [dict(id="source", reset_mode="reset"), dict(id="target", threshold=100, leak=0)],
            [dict(source="source", target="target", delay=256, weight=0.75)],
        )
        n.step(np.array([1, 0]))
        for _ in range(255):
            n.step()
        self.assertEqual(n.V[1], 0)
        n.step()
        self.assertEqual(n.V[1], 0.75)
        for _ in range(300):
            n.step()
        self.assertEqual(n.V[1], 0.75)
