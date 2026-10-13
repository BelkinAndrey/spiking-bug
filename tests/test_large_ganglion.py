import json
import unittest
from unittest.mock import patch

from server.generators import ganglion
from server.schema import topology
from server.app import create_app
from server.runtime import Runtime


class LargeGanglionTests(unittest.TestCase):
    def test_large_ganglion_with_sparse_connections_and_existing_neurons(self):
        original = topology(dict(neurons=[dict(id="existing")]))
        net = ganglion(original, dict(count=200_000, radius=50_000, density=0.000001))
        self.assertEqual(len(net["neurons"]), 200_001)
        self.assertEqual(len(net["ganglia"][0]["members"]), 200_000)
        self.assertEqual(net["ganglia"][0]["radius"], 50_000)
        self.assertTrue(30_000 < len(net["synapses"]) < 50_000)
        self.assertEqual(len(original["neurons"]), 1)
        runtime = Runtime(None)
        project = {**runtime.project(), "topology": net, "bindings": {}}
        payload = json.dumps(dict(action="import", data=project, revision=runtime.revision))
        self.assertGreater(len(payload), 32 * 1024 * 1024)
        response = create_app(runtime).test_client().post(
            "/api/command", data=payload, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(runtime.net.n, 200_001)

    def test_generator_rejects_above_new_limits_before_generating(self):
        net = topology(dict(neurons=[]))
        for params in (dict(count=200_001), dict(radius=50_001)):
            with self.subTest(params=params), self.assertRaises(ValueError):
                ganglion(net, params)
        with patch("server.generators.MAX_NEURONS", 10), self.assertRaises(ValueError):
            ganglion(net, dict(count=11))

    def test_import_rejects_oversized_ganglion(self):
        with self.assertRaises(ValueError):
            topology(
                dict(
                    neurons=[dict(id="n")],
                    ganglia=[
                        dict(
                            id="g",
                            x=0,
                            y=0,
                            radius=50_001,
                            members=["n"],
                        )
                    ],
                )
            )
