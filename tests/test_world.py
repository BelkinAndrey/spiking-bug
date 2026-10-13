import unittest
from server.world import World
from server.generators import maze, ganglion
from server.schema import topology


def world(**config):
    return World(
        dict(
            config=dict(width=600, height=600, food_target=0, threat_target=0, **config),
            spawn=dict(x=300, y=300, heading=0),
        )
    )


class WorldTests(unittest.TestCase):
    def test_exhausted_movement_costs_one_percent_health_per_second(self):
        for manual in (None, dict(right=True)):
            with self.subTest(manual=manual):
                w = world()
                w.agent["fatigue"] = 1.0
                for _ in range(100):
                    w.step(dict(right=True), manual=manual)
                self.assertAlmostEqual(w.agent["health"], 0.99)
                self.assertAlmostEqual(w.agent["damage"], 0.01)

    def test_fatigue_threshold_and_recovery(self):
        w = world()
        w.agent["fatigue"] = 0.9
        w.step(dict(forward=True))
        self.assertEqual(w.agent["health"], 1.0)
        w.agent["fatigue"] = 0.99
        w.step(dict(forward=True))
        self.assertEqual(w.agent["fatigue"], 1.0)
        self.assertLess(w.agent["health"], 1.0)
        health = w.agent["health"]
        for _ in range(100):
            w.step({})
        w.step(dict(forward=True))
        self.assertLess(w.agent["fatigue"], 1.0)
        self.assertEqual(w.agent["health"], health)

    def test_exhaustion_requires_actual_movement(self):
        for motors, manual in (
            ({}, None),
            (dict(left=True, right=True), None),
            (dict(forward=True), {}),
        ):
            with self.subTest(motors=motors, manual=manual):
                w = world()
                w.agent["fatigue"] = 1.0
                w.step(motors, manual=manual)
                self.assertEqual(w.agent["health"], 1.0)
        w = world()
        w.agent.update(x=588, fatigue=1.0)
        w.step(dict(forward=True))
        self.assertEqual(w.agent["x"], 588)
        self.assertEqual(w.agent["health"], 1.0)

    def test_zero_health_does_not_stop_neural_movement(self):
        w = world()
        w.agent.update(fatigue=1.0, health=0.00005)
        w.step(dict(forward=True))
        self.assertEqual(w.agent["health"], 0.0)
        self.assertAlmostEqual(w.agent["damage"], 0.00005)
        x = w.agent["x"]
        w.step(dict(forward=True))
        self.assertGreater(w.agent["x"], x)
        self.assertEqual(w.agent["health"], 0.0)
        self.assertAlmostEqual(w.agent["damage"], 0.00005)

    def test_zero_health_keeps_manual_movement_and_collisions(self):
        for paused in (False, True):
            with self.subTest(paused=paused):
                w = world()
                w.agent["health"] = 0.0
                def drive(motors):
                    if paused:
                        w.drive(motors)
                    else:
                        w.step({}, manual=motors)
                drive(dict(forward=True, right=True))
                self.assertGreater(w.agent["x"], 300)
                self.assertGreater(w.agent["heading"], 0)
                w.agent.update(x=588, heading=0)
                drive(dict(forward=True))
                self.assertEqual(w.agent["x"], 588)
                drive(dict(backward=True))
                self.assertLess(w.agent["x"], 588)
                self.assertEqual(w.agent["health"], 0.0)

    def test_zero_health_continues_physiology_and_food_can_restore_health(self):
        w = world()
        w.agent.update(health=0.0, fatigue=1.0, hunger=0.5)
        w.step({})
        self.assertLess(w.agent["fatigue"], 1.0)
        self.assertGreater(w.agent["hunger"], 0.5)
        w.add_object(dict(kind="food", x=300, y=300))
        w.step({})
        self.assertAlmostEqual(w.agent["health"], 0.12)
        self.assertEqual(w.agent["hunger"], 0.0)
        self.assertEqual(w.agent["eaten"], 1)

    def test_direct_paused_movement_does_not_apply_exhaustion_damage(self):
        w = world()
        w.agent["fatigue"] = 1.0
        w.drive(dict(forward=True))
        self.assertGreater(w.agent["x"], 300)
        self.assertEqual(w.agent["health"], 1.0)

    def test_collision_no_tunnelling(self):
        w = world()
        w.add_object(dict(kind="obstacle", x=330, y=100, w=5, h=400))
        w.move(w.agent, 200, 0, 12)
        self.assertLessEqual(w.agent["x"], 318)

    def test_raycast_wall_occlusion(self):
        w = world()
        w.add_object(dict(kind="obstacle", x=330, y=100, w=5, h=400))
        self.assertEqual(w.raycast(300, 300, 0, 180), 30)
        w.add_object(dict(kind="food", x=345, y=300))
        w.sense()
        self.assertEqual(w.sensors["food_left"], 0)
        self.assertEqual(w.sensors["food_right"], 0)

    def test_pursuit_loses_interest_and_rests(self):
        w = world(chase_duration=0.1, cooldown=1, threat_radius=200)
        t = w.add_object(dict(kind="threat", x=200, y=300, mode="pursuit"))
        for _ in range(8):
            w.step({})
        self.assertGreater(t["x"], 200)
        self.assertEqual(t["state"], "chasing")
        for _ in range(10):
            w.step({})
        self.assertEqual(t["state"], "rest")
        position = t["x"]
        w.step({})
        self.assertEqual(t["x"], position)

    def test_pursuit_stops_on_loss_of_visibility(self):
        w = world(threat_radius=200)
        t = w.add_object(dict(kind="threat", x=200, y=300, mode="pursuit"))
        w.step({})
        w.add_object(dict(kind="obstacle", x=250, y=200, w=10, h=200))
        w.step({})
        self.assertEqual(t["state"], "rest")

    def test_static_threat_does_not_move(self):
        w = world()
        t = w.add_object(dict(kind="threat", x=200, y=300, mode="static"))
        for _ in range(50):
            w.step({})
        self.assertEqual(t["x"], 200)

    def test_food_zone_and_reproducibility(self):
        a = world()
        b = world()
        for w in (a, b):
            w.add_zone(dict(x=30, y=30, w=60, h=60))
            w.config["food_target"] = 3
            for _ in range(100):
                w.step({})
        self.assertEqual(a.objects, b.objects)
        self.assertTrue(all(30 < o["x"] < 90 and 30 < o["y"] < 90 for o in a.objects))

    def test_maze_is_connected(self):
        walls, spawn = maze(600, 600, 6, 6, 42)
        w = World(
            dict(
                config=dict(width=600, height=600, food_target=0, threat_target=0),
                objects=walls,
                spawn=spawn,
            )
        )
        seen = {(0, 0)}
        stack = [(0, 0)]
        while stack:
            x, y = stack.pop()
            for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < 6 and 0 <= ny < 6) or (nx, ny) in seen:
                    continue
                if w.free((x + nx + 1) * 50, (y + ny + 1) * 50, 12):
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        self.assertEqual(len(seen), 36)
        self.assertEqual(maze(600, 600, 6, 6, 42), (walls, spawn))

    def test_generator_dales_rule(self):
        net = topology(dict(format_version=3, neurons=[], synapses=[]))
        net = ganglion(net, dict(id="g", count=40, density=0.2, seed=42, mode="neurons"))
        polarities = {n["id"]: n["polarity"] for n in net["neurons"]}
        for s in net["synapses"]:
            self.assertEqual(s["weight"] > 0, polarities[s["source"]] == "exc")
        self.assertEqual(
            net,
            ganglion(
                topology(dict(neurons=[], synapses=[])),
                dict(id="g", count=40, density=0.2, seed=42, mode="neurons"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
