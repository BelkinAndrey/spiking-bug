import copy
import threading
import time
import unittest
from unittest.mock import patch

from server.app import create_app
from server.runtime import Runtime
from server import schema
from server.trials import evaluate, run_attempt, settings, summarize


def fixture():
    r = Runtime()
    r.command(
        "topology",
        schema.topology(dict(neurons=[dict(id="motor", bias=2, refractory=0)], synapses=[])),
        r.revision,
    )
    r.command("bindings", {"forward": "motor"}, r.revision)
    r.world.objects = []
    r.world.zones = []
    r.world.config.update(food_target=0, threat_target=0, hunger_rate=0)
    return r


class TrialTests(unittest.TestCase):
    def test_matches_interactive_steps_and_does_not_mutate_snapshot(self):
        r = fixture()
        p = copy.deepcopy(r.project())
        before = copy.deepcopy(p)
        options = settings(dict(attempts=1, duration=1, seed=p["world"]["config"]["seed"]))
        row = run_attempt(p, options, 0, threading.Event(), lambda *_: None)
        r.command("import", p, r.revision)
        x = r.world.agent["x"]
        for _ in range(100):
            r.step()
        self.assertEqual(p, before)
        self.assertAlmostEqual(row["distance"], r.world.agent["x"] - x)
        self.assertEqual(row["health"], r.world.agent["health"] * 100)
        self.assertEqual(row["food"], r.world.agent["eaten"])
        self.assertEqual(row["firing_hz"], int(r.net.total.sum()) / r.net.n)
        self.assertEqual(row["duration"], 1)

    def test_seed_reproducibility_and_summary(self):
        p = fixture().project()
        p["world"]["config"].update(food_target=3, threat_target=1)
        p["topology"]["neurons"][0].update(bias=0.01, noise_std=0.2)
        options = settings(dict(attempts=3, duration=1, randomize=True))
        a, b = [], []
        evaluate(p, options, threading.Event(), a.append)
        evaluate(p, options, threading.Event(), b.append)
        self.assertEqual(a[-1]["rows"], b[-1]["rows"])
        self.assertEqual([r["seed"] for r in a[-1]["rows"]], [42, 43, 44])
        self.assertEqual(a[-1]["progress"], 1)
        self.assertEqual(a[-1]["summary"]["survival_pct"], 100)
        self.assertGreater(a[-1]["speedup"], 0)
        self.assertEqual(summarize([]), None)

    def test_death_ends_attempt_even_though_normal_mode_keeps_moving(self):
        p = fixture().project()
        p["world"]["config"].update(fatigue_gain=1, fatigue_decay=0)
        options = settings(dict(attempts=1, duration=200))
        # Keep moving indefinitely by turning instead of hitting an arena edge.
        p["bindings"] = {"right": "motor"}
        row = run_attempt(p, options, 0, threading.Event(), lambda *_: None)
        self.assertFalse(row["survived"])
        self.assertEqual(row["health"], 0)
        self.assertAlmostEqual(row["duration"], 100, delta=0.02)

    def test_cancel_and_error_keep_only_finished_rows(self):
        p = fixture().project()
        stop = threading.Event()
        updates = []

        def publish(update):
            updates.append(update)
            if update["completed"] == 1:
                stop.set()

        evaluate(p, settings(dict(attempts=20, duration=1)), stop, publish)
        self.assertEqual(updates[-1]["status"], "cancelled")
        self.assertEqual(len(updates[-1]["rows"]), 1)
        with patch("server.trials.run_attempt", side_effect=ValueError("broken")):
            updates = []
            with self.assertLogs(level="ERROR"):
                evaluate(p, settings({}), threading.Event(), updates.append)
        self.assertEqual(updates[-1]["status"], "failed")
        self.assertEqual(updates[-1]["error"], "broken")

    def test_validation(self):
        for data in (
            dict(attempts=0),
            dict(attempts=1001),
            dict(attempts=1.5),
            dict(duration=0),
            dict(seed=-1),
            None,
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                settings(data)

    def test_process_api_isolation_conflicts_and_cancellation(self):
        r = fixture()
        app = create_app(r)
        client = app.test_client()
        manager = app.extensions["trials"]

        def wait():
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                job = client.get("/api/trials").json
                if job["status"] not in ("running", "cancelling"):
                    manager.process.join(timeout=2)
                    return job
                time.sleep(0.01)
            self.fail("trial process did not finish")

        try:
            self.assertIsNone(client.get("/api/trials").json)
            self.assertEqual(client.post("/api/trials", json={"revision": -1}).status_code, 409)
            self.assertEqual(
                client.post(
                    "/api/trials", json={"revision": r.revision, "settings": {"duration": 0}}
                ).status_code,
                400,
            )
            before = copy.deepcopy(r.snapshot())
            response = client.post(
                "/api/trials",
                json={"revision": r.revision, "settings": {"attempts": 2, "duration": 1}},
            )
            self.assertEqual(response.status_code, 200)
            job = wait()
            self.assertEqual(job["status"], "completed", job)
            self.assertEqual(job["completed"], 2)
            self.assertEqual(r.snapshot(), before)
            response = client.post(
                "/api/trials",
                json={"revision": r.revision, "settings": {"attempts": 1000, "duration": 3600}},
            )
            job_id = response.json["id"]
            self.assertEqual(
                client.post("/api/trials", json={"revision": r.revision}).status_code, 409
            )
            client.post("/api/trials/cancel", json={"id": "stale-id"})
            self.assertEqual(manager.snapshot()["status"], "running")
            client.post("/api/trials/cancel", json={"id": job_id})
            self.assertEqual(wait()["status"], "cancelled")
            self.assertEqual(r.snapshot(), before)
        finally:
            manager.close()
