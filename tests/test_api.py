import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from server.app import create_app
from server.runtime import Runtime
from server.schema import topology


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "project.json"
        self.runtime = Runtime(self.path)
        self.client = create_app(self.runtime).test_client()

    def tearDown(self):
        self.temp.cleanup()

    def command(self, action, data={}, revision=None):
        return self.client.post(
            "/api/command",
            json=dict(
                action=action,
                data=data,
                revision=self.runtime.revision if revision is None else revision,
            ),
        )

    def test_legacy_migration(self):
        for p in Path("examples/legacy").glob("*.json"):
            r = self.command("import", json.loads(p.read_text()))
            self.assertEqual(r.status_code, 200, r.json)
            self.assertTrue(
                all(n["reset_mode"] == "reset" for n in self.runtime.net.topology["neurons"])
            )

    def test_invalid_import_is_atomic(self):
        before = copy.deepcopy(self.runtime.project())
        bad = copy.deepcopy(before)
        bad["topology"]["neurons"][0]["threshold"] = -10001
        self.assertEqual(self.command("import", bad).status_code, 400)
        self.assertEqual(self.runtime.project(), before)
        bad = copy.deepcopy(before)
        bad["world"]["objects"] = [dict(kind="obstacle", x=1, y=1, w=-1, h=10)]
        self.assertEqual(self.command("import", bad).status_code, 400)
        self.assertEqual(self.runtime.project(), before)

    def test_stale_revision_conflict(self):
        rev = self.runtime.revision
        self.command("world_config", dict(food_target=2))
        self.assertEqual(
            self.command("world_config", dict(food_target=3), revision=rev).status_code, 409
        )
        self.assertEqual(self.runtime.world.config["food_target"], 2)

    def test_unknown_binding_is_rejected(self):
        self.assertEqual(self.command("bindings", dict(forward="missing")).status_code, 400)

    def test_shared_mapping_and_save_reload(self):
        b = {**self.runtime.bindings, "forward": "explore"}
        self.assertEqual(self.command("bindings", b).status_code, 200)
        other = create_app(self.runtime).test_client()
        self.assertEqual(other.get("/api/project").json["bindings"]["forward"], "explore")
        restarted = Runtime(self.path)
        self.assertEqual(restarted.bindings["forward"], "explore")
        self.assertEqual(len(restarted.world.objects), len(self.runtime.world.objects))

    def test_telemetry_counts_not_consumed_per_client(self):
        self.runtime.step()
        a = self.client.get("/api/state").json
        b = self.client.get("/api/state").json
        self.assertEqual(a, b)

    def test_move_does_not_reset_or_drop_delayed_events(self):
        for _ in range(9):
            self.runtime.step()
        before = self.runtime.net.queue.copy()
        v = self.runtime.net.V.copy()
        self.command("positions", dict(positions=[dict(id="drive", x=12, y=20)]))
        np.testing.assert_array_equal(before, self.runtime.net.queue)
        np.testing.assert_array_equal(v, self.runtime.net.V)

    def test_roundtrip_new_fields(self):
        self.command("ganglion", dict(id="g", count=4, density=0.5))
        p = self.client.get("/api/export").json
        self.assertEqual(self.command("import", p).status_code, 200)
        self.assertEqual(p["topology"], self.runtime.project()["topology"])
        self.assertEqual(p["bindings"], self.runtime.bindings)

    def test_dangling_connection_rejected(self):
        p = copy.deepcopy(self.runtime.net.topology)
        p["synapses"][0]["target"] = "missing"
        self.assertEqual(self.command("topology", p).status_code, 400)

    def test_modulation_connector_expansion_limit(self):
        with self.assertRaises(ValueError):
            topology(dict(neurons=[dict(id="a")], synapses=[dict(source="a", target="missing")]))

    def test_step_requires_pause(self):
        self.command("control", dict(mode="play"))
        self.assertEqual(self.command("control", dict(mode="step")).status_code, 400)
        self.command("control", dict(mode="pause"))
        self.assertEqual(self.command("control", dict(mode="step")).status_code, 200)


if __name__ == "__main__":
    unittest.main()


class MalformedInputTests(unittest.TestCase):
    def test_structural_errors_are_rejected_without_mutation(self):
        runtime = Runtime()
        client = create_app(runtime).test_client()
        malformed = [
            {"neurons": ["bad"]},
            {"neurons": [], "synapses": ["bad"]},
            {"neurons": [], "ganglia": ["bad"]},
            {"neurons": [], "world": []},
            {"neurons": [], "world": {"objects": ["bad"]}},
            {"neurons": [], "bindings": []},
            {"neurons": [], "groups": ["bad"]},
        ]
        before = copy.deepcopy(runtime.project())
        for data in malformed:
            response = client.post(
                "/api/command", json=dict(action="import", data=data, revision=runtime.revision)
            )
            self.assertEqual(response.status_code, 400, response.json)
            self.assertEqual(runtime.project(), before)


class VisualEditTests(unittest.TestCase):
    def test_annotation_and_label_do_not_clear_pending_currents(self):
        runtime = Runtime()
        for _ in range(9):
            runtime.step()
        before = runtime.net.queue.copy()
        v = runtime.net.V.copy()
        session = runtime.session
        net = copy.deepcopy(runtime.net.topology)
        net["neurons"][0]["label"] = "Renamed"
        net["groups"] = [dict(id="f", label="Frame", x=0, y=0, w=100, h=100)]
        runtime.command("topology", net, runtime.revision)
        np.testing.assert_array_equal(before, runtime.net.queue)
        np.testing.assert_array_equal(v, runtime.net.V)
        self.assertEqual(runtime.session, session)
