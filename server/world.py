"""BUG world: continuous collision detection by substeps, ray sensors, pursuit."""

from __future__ import annotations
import copy
import math
import random
from .schema import DT, SENSORS, number, world_config


class World:
    radius = 12.0
    exhaustion_damage_rate = 0.01  # Health per simulated second of movement at full fatigue.

    def __init__(self, data):
        self.config = world_config(data.get("config", {}))
        self.rng = random.Random(self.config["seed"])
        self.objects = []
        self.zones = []
        self.next_id = 1
        self.spawn = data.get("spawn", dict(x=300.0, y=800.0, heading=0.0))
        for k in ("x", "y", "heading"):
            number(self.spawn[k], k, -100000, 100000)
        for z in data.get("zones", []):
            self.add_zone(z)
        for o in data.get("objects", []):
            self.add_object(o)
        self.agent = dict(
            x=0.0, y=0.0, heading=0.0, health=1.0, hunger=0.0, fatigue=0.0, eaten=0, damage=0.0
        )
        self.reset_agent()
        self.food_clock = 0.0
        self.elapsed = 0.0
        self.sensors = {k: 0.0 for k in SENSORS}
        self.lidar = [self.config["lidar_range"]] * 5
        self.sense()

    @property
    def obstacles(self):
        return [o for o in self.objects if o["kind"] == "obstacle"]

    def new_id(self):
        result = f"o{self.next_id}"
        self.next_id += 1
        return result

    def free(self, x, y, r=12):
        c = self.config
        if not r <= x <= c["width"] - r or not r <= y <= c["height"] - r:
            return False
        for o in self.obstacles:
            cx = max(o["x"], min(x, o["x"] + o["w"]))
            cy = max(o["y"], min(y, o["y"] + o["h"]))
            if (x - cx) ** 2 + (y - cy) ** 2 < r * r:
                return False
        return True

    def random_point(self, r=12, zones=False):
        for _ in range(400):
            if zones and self.zones:
                z = self.rng.choice(self.zones)
                x = self.rng.uniform(z["x"] + r, z["x"] + z["w"] - r)
                y = self.rng.uniform(z["y"] + r, z["y"] + z["h"] - r)
            else:
                x = self.rng.uniform(r, self.config["width"] - r)
                y = self.rng.uniform(r, self.config["height"] - r)
            if self.free(x, y, r):
                return x, y
        return None

    def add_zone(self, z):
        if len(self.zones) >= 100:
            raise ValueError("Лимит: 100 зон пищи")
        zone = {
            k: number(z[k], k, 0 if k in ("x", "y") else 30, 12000) for k in ("x", "y", "w", "h")
        }
        if (
            zone["x"] + zone["w"] > self.config["width"]
            or zone["y"] + zone["h"] > self.config["height"]
        ):
            raise ValueError("Зона вне арены")
        zone["id"] = self.new_id()
        self.zones.append(zone)
        return zone

    def add_object(self, data):
        if len(self.objects) >= 2500:
            raise ValueError("Лимит: 2500 объектов")
        kind = data.get("kind")
        if kind not in ("food", "threat", "obstacle"):
            raise ValueError("Неизвестный объект")
        x = number(data["x"], "x", 0, self.config["width"])
        y = number(data["y"], "y", 0, self.config["height"])
        o = dict(id=self.new_id(), kind=kind, x=x, y=y)
        if kind == "obstacle":
            o.update(w=number(data["w"], "w", 4, 12000), h=number(data["h"], "h", 4, 12000))
            if x + o["w"] > self.config["width"] or y + o["h"] > self.config["height"]:
                raise ValueError("Препятствие вне арены")
            if hasattr(self, "agent"):
                a = self.agent
                cx = max(x, min(a["x"], x + o["w"]))
                cy = max(y, min(a["y"], y + o["h"]))
                if (a["x"] - cx) ** 2 + (a["y"] - cy) ** 2 < self.radius**2:
                    raise ValueError("Препятствие пересекает жука")
        else:
            r = 7 if kind == "food" else 16
            if not self.free(x, y, r):
                raise ValueError("Объект пересекает стену")
            o["radius"] = r
            if kind == "threat":
                mode = data.get("mode", self.config["threat_mode"])
                if mode not in ("static", "pursuit"):
                    raise ValueError("Неизвестный режим угрозы")
                o.update(
                    mode=mode,
                    state="idle",
                    interest=0.0,
                    rest=0.0,
                    ttl=self.config["threat_lifetime"],
                )
        self.objects.append(o)
        return o

    def reset_agent(self):
        x, y = self.spawn["x"], self.spawn["y"]
        if not self.free(x, y):
            point = self.random_point()
            if point is None:
                raise ValueError("Нет свободного места для жука")
            x, y = point
        self.agent = dict(
            x=x,
            y=y,
            heading=self.spawn["heading"],
            health=1.0,
            hunger=0.0,
            fatigue=0.0,
            eaten=0,
            damage=0.0,
        )

    def raycast(self, x, y, angle, limit):
        dx, dy = math.cos(angle), math.sin(angle)
        # Slab ray/AABB intersection. Exact wall distances; no marching loop.
        distance = limit
        for direction, pos, maximum in [
            (dx, x, self.config["width"]),
            (dy, y, self.config["height"]),
        ]:
            if abs(direction) > 1e-10:
                distance = min(distance, ((maximum - pos) if direction > 0 else -pos) / direction)
        for o in self.obstacles:
            near = 0.0
            far = limit
            for p, d, lo, hi in [
                (x, dx, o["x"], o["x"] + o["w"]),
                (y, dy, o["y"], o["y"] + o["h"]),
            ]:
                if abs(d) < 1e-10:
                    if not lo <= p <= hi:
                        far = -1
                        break
                else:
                    a, b = (lo - p) / d, (hi - p) / d
                    near = max(near, min(a, b))
                    far = min(far, max(a, b))
            if near <= far and far >= 0:
                distance = min(distance, near)
        return max(0.0, distance)

    def move(self, obj, dx, dy, r):
        steps = max(1, math.ceil(math.hypot(dx, dy) / max(1, r / 2)))
        for _ in range(steps):
            nx = obj["x"] + dx / steps
            ny = obj["y"] + dy / steps
            if self.free(nx, ny, r):
                obj["x"], obj["y"] = nx, ny
            elif self.free(nx, obj["y"], r):
                obj["x"] = nx
            elif self.free(obj["x"], ny, r):
                obj["y"] = ny

    def sense(self):
        a = self.agent
        c = self.config
        s = {k: 0.0 for k in SENSORS}
        s["hunger"] = a["hunger"]
        s["fatigue"] = a["fatigue"]
        for i in range(5):
            self.lidar[i] = self.raycast(
                a["x"], a["y"], a["heading"] + (i - 2) * math.radians(25), c["lidar_range"]
            )
            s[f"lidar_{i}"] = 1 - self.lidar[i] / c["lidar_range"]
        for o in self.objects:
            if o["kind"] not in ("food", "threat"):
                continue
            dx, dy = o["x"] - a["x"], o["y"] - a["y"]
            d = math.hypot(dx, dy)
            if d > c["sensor_range"]:
                continue
            absolute = math.atan2(dy, dx)
            relative = (absolute - a["heading"] + math.pi) % math.tau - math.pi
            if self.raycast(a["x"], a["y"], absolute, d) < d - 1:
                continue
            limit = math.radians(120 if o["kind"] == "food" else 150)
            overlap = math.radians(2) if o["kind"] == "food" else 0
            strength = min(1.0, (1500 / 3 if o["kind"] == "food" else 2500 / 4) / max(d * d, 1))
            if -limit <= relative <= overlap:
                s[o["kind"] + "_left"] += strength
            if -overlap <= relative <= limit:
                s[o["kind"] + "_right"] += strength
        self.sensors = {k: min(1.0, v) for k, v in s.items()}
        return self.sensors

    def drive(self, motors, duration=DT):
        """Apply a direct motor command with collisions; no clock or physiology update."""
        a, c = self.agent, self.config
        a["heading"] = (
            a["heading"]
            + (motors.get("right", False) - motors.get("left", False)) * c["turn_speed"] * duration
        ) % math.tau
        distance = (
            (motors.get("forward", False) - 0.7 * motors.get("backward", False))
            * c["speed"]
            * duration
        )
        self.move(
            a, math.cos(a["heading"]) * distance, math.sin(a["heading"]) * distance, self.radius
        )

    def step(self, motors, manual=None):
        c = self.config
        a = self.agent
        self.elapsed += DT
        exhausted = a["fatigue"] >= 1.0
        pose = (a["x"], a["y"], a["heading"])
        self.drive(motors if manual is None else manual, 0.04 if manual is None else DT)
        a["hunger"] = min(1.0, a["hunger"] + c["hunger_rate"] * DT)
        a["fatigue"] = max(
            0.0,
            min(
                1.0,
                a["fatigue"]
                + sum(motors.values()) * c["fatigue_gain"]
                - c["fatigue_decay"] * DT,
            ),
        )
        moved = pose != (a["x"], a["y"], a["heading"])
        if moved and (exhausted or a["fatigue"] >= 1.0):
            damage = min(a["health"], self.exhaustion_damage_rate * DT)
            a["health"] -= damage
            a["damage"] += damage
        for o in list(self.objects):
            d = math.hypot(o["x"] - a["x"], o["y"] - a["y"])
            if o["kind"] == "food" and d < self.radius + 7:
                self.objects.remove(o)
                a["eaten"] += 1
                a["hunger"] = 0.0
                a["health"] = min(1.0, a["health"] + 0.12)
            if o["kind"] != "threat":
                continue
            o["ttl"] -= DT
            if o["ttl"] <= 0:
                self.objects.remove(o)
                continue
            angle = math.atan2(a["y"] - o["y"], a["x"] - o["x"])
            visible = d < c["threat_radius"] and self.raycast(o["x"], o["y"], angle, d) >= d - 1
            if o["mode"] == "pursuit":
                if o["rest"] > 0:
                    o["rest"] = max(0.0, o["rest"] - DT)
                    o["state"] = "rest"
                elif o["state"] == "chasing":
                    o["interest"] -= DT
                    if not visible or o["interest"] <= 0:
                        o["state"] = "rest"
                        o["rest"] = c["cooldown"]
                    else:
                        self.move(
                            o,
                            math.cos(angle) * c["speed"] * c["threat_speed_ratio"] * DT,
                            math.sin(angle) * c["speed"] * c["threat_speed_ratio"] * DT,
                            16,
                        )
                elif visible:
                    o["state"] = "chasing"
                    o["interest"] = c["chase_duration"]
                else:
                    o["state"] = "idle"
            if math.hypot(o["x"] - a["x"], o["y"] - a["y"]) < self.radius + 16:
                damage = min(a["health"], 0.25 * DT)
                a["health"] -= damage
                a["damage"] += damage
        if a["hunger"] >= 1:
            a["health"] = max(0.0, a["health"] - 0.015 * DT)
        self.food_clock += DT
        if self.food_clock >= c["food_interval"]:
            self.food_clock = 0.0
            if sum(o["kind"] == "food" for o in self.objects) < c["food_target"]:
                p = self.random_point(7, True)
                if p:
                    self.add_object(dict(kind="food", x=p[0], y=p[1]))
        if sum(o["kind"] == "threat" for o in self.objects) < c["threat_target"]:
            p = self.random_point(16)
            if p and math.hypot(p[0] - a["x"], p[1] - a["y"]) > c["threat_radius"]:
                self.add_object(dict(kind="threat", x=p[0], y=p[1]))
        self.sense()

    def export(self):
        return dict(
            config=copy.deepcopy(self.config),
            spawn=copy.deepcopy(self.spawn),
            zones=copy.deepcopy(self.zones),
            objects=[
                {k: v for k, v in o.items() if k in ("id", "kind", "x", "y", "w", "h", "mode")}
                for o in self.objects
            ],
        )

    def snapshot(self):
        return dict(
            config=self.config,
            agent=self.agent,
            objects=self.objects,
            zones=self.zones,
            lidar=self.lidar,
            sensors=self.sensors,
        )
