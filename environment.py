"""2D environment with a bug agent, food, threats, obstacles, hunger, fatigue."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

PI = math.pi
TAU = 2 * PI


def _hour_angle(h: float) -> float:
    """Clock hour (0..12, can wrap) -> agent-relative angle.
    12 = 0 (forward), 3 = +π/2 (right), 6 = ±π (back), 9 = -π/2 (left).
    """
    return (h - 12) * PI / 6


# Sensor sectors, agent-relative (forward = 0).
# Food cones meet at the front with a small 4° overlap (±2° around 12 o'clock).
# Threat cones share only the forward direction (single point).
_FOOD_OVERLAP_HALF = math.radians(2.0)   # half of the 4° forward overlap
SENSOR_ARCS: dict[str, tuple[float, float]] = {
    "food_left":    (_hour_angle(8),  _FOOD_OVERLAP_HALF),       # -120° .. +2°
    "food_right":   (-_FOOD_OVERLAP_HALF, _hour_angle(16)),      #   -2° .. +120°
    "threat_left":  (_hour_angle(7),  _hour_angle(12)),          # -150° .. 0
    "threat_right": (_hour_angle(12), _hour_angle(17)),          #    0° .. +150°
}


def _wrap_pi(a: float) -> float:
    while a > PI:  a -= TAU
    while a < -PI: a += TAU
    return a


def _in_arc(angle: float, arc: tuple[float, float]) -> bool:
    a, b = arc
    angle = _wrap_pi(angle)
    a = _wrap_pi(a)
    b = _wrap_pi(b)
    if a <= b:
        return a <= angle <= b
    # Wrap around ±π
    return angle >= a or angle <= b


@dataclass
class Food:
    id: int
    x: float
    y: float
    size: float = 6.0


@dataclass
class Threat:
    id: int
    x: float
    y: float
    radius: float = 12.0
    ttl_left: float = 12.0    # seconds remaining before the threat is replaced


@dataclass
class Obstacle:
    id: int
    x: float
    y: float
    w: float
    h: float


@dataclass
class Agent:
    x: float
    y: float
    heading: float = 0.0  # radians, 0 = +x
    radius: float = 9.0
    speed_per_spike: float = 1.6
    turn_per_spike: float = 0.08
    lidar_count: int = 5
    lidar_range: float = 110.0
    lidar_fov: float = math.pi * 0.55
    lidar_distances: list[float] = field(default_factory=list)

    # Sensor signals (raw, before LIF current mapping)
    food_left_signal: float = 0.0
    food_right_signal: float = 0.0
    threat_left_signal: float = 0.0
    threat_right_signal: float = 0.0

    # Internal state
    health: float = 1.0
    hunger: float = 0.0     # 0 (sated) .. 1 (starving)
    fatigue: float = 0.0    # 0 (rested) .. 1 (exhausted)
    food_eaten: int = 0
    damage_taken: float = 0.0

    def __post_init__(self) -> None:
        if not self.lidar_distances:
            self.lidar_distances = [self.lidar_range] * self.lidar_count

    @property
    def lidar_angles(self) -> list[float]:
        if self.lidar_count == 1:
            return [0.0]
        half = self.lidar_fov / 2
        step = self.lidar_fov / (self.lidar_count - 1)
        return [-half + i * step for i in range(self.lidar_count)]


class Environment:
    def __init__(self, width: int = 1100, height: int = 700):
        self.width = width
        self.height = height
        self.obstacles: list[Obstacle] = []
        self.foods: list[Food] = []
        self.threats: list[Threat] = []
        self.agent = Agent(x=width / 2, y=height / 2)
        self.agent.lidar_distances = [self.agent.lidar_range] * self.agent.lidar_count
        # New spawn model:
        #   food_target — keep N foods on the field; new food spawns when one
        #     is eaten. If 0, nothing new appears (existing food still consumable).
        #   threat_target — keep N threats; each threat has a lifetime, when it
        #     expires it is removed and a new one spawns elsewhere. If 0, all
        #     threats vanish.
        self.food_target = 5
        self.threat_target = 0
        self.threat_lifetime = 12.0        # seconds per threat
        # Internal-state dynamics
        self.hunger_rate = 0.05
        self.fatigue_action_gain = 0.02
        self.fatigue_decay = 0.10
        self._next_id = 1

    # --------------------------------------------------------------- object ops
    def _gen_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def add_food(self, x: float, y: float, size: float = 6.0) -> Food:
        f = Food(self._gen_id(), x, y, size); self.foods.append(f); return f

    def add_threat(self, x: float, y: float, radius: float = 12.0,
                   ttl: float | None = None) -> Threat:
        if ttl is None:
            ttl = self.threat_lifetime
        t = Threat(self._gen_id(), x, y, radius, ttl)
        self.threats.append(t)
        return t

    def add_obstacle(self, x: float, y: float, w: float, h: float) -> Obstacle:
        o = Obstacle(self._gen_id(), x, y, w, h); self.obstacles.append(o); return o

    def remove_object(self, kind: str, oid: int) -> None:
        coll = {"food": self.foods, "threat": self.threats, "obstacle": self.obstacles}.get(kind)
        if coll is None: return
        for i, obj in enumerate(coll):
            if obj.id == oid:
                coll.pop(i); return

    def clear_objects(self, kind: str | None = None) -> None:
        if kind in (None, "food"):     self.foods.clear()
        if kind in (None, "threat"):   self.threats.clear()
        if kind in (None, "obstacle"): self.obstacles.clear()

    def reset_agent(self) -> None:
        self.agent.x = self.width / 2
        self.agent.y = self.height / 2
        self.agent.heading = 0.0
        self.agent.health = 1.0
        self.agent.hunger = 0.0
        self.agent.fatigue = 0.0
        self.agent.food_eaten = 0
        self.agent.damage_taken = 0.0

    def resize(self, width: int, height: int) -> None:
        self.width = max(200, int(width))
        self.height = max(200, int(height))
        a = self.agent
        a.x = min(max(a.radius, a.x), self.width - a.radius)
        a.y = min(max(a.radius, a.y), self.height - a.radius)

    # ------------------------------------------------------------ physics utils
    def _point_in_obstacle(self, x: float, y: float) -> bool:
        for o in self.obstacles:
            if o.x <= x <= o.x + o.w and o.y <= y <= o.y + o.h:
                return True
        return False

    def _circle_free(self, x: float, y: float, r: float) -> bool:
        if x - r < 0 or x + r > self.width or y - r < 0 or y + r > self.height:
            return False
        for o in self.obstacles:
            cx = max(o.x, min(x, o.x + o.w))
            cy = max(o.y, min(y, o.y + o.h))
            if (x - cx) ** 2 + (y - cy) ** 2 < r * r:
                return False
        return True

    def raycast(self, x: float, y: float, angle: float, max_range: float) -> float:
        dx = math.cos(angle); dy = math.sin(angle)
        step = 2.0; d = 0.0
        while d < max_range:
            d += step
            px = x + dx * d; py = y + dy * d
            if px < 0 or px >= self.width or py < 0 or py >= self.height:
                return d
            if self._point_in_obstacle(px, py):
                return d
        return max_range

    # -------------------------------------------------------------------- step
    def step(self, dt: float) -> dict:
        events = {"ate": 0, "hit": 0.0}
        a = self.agent

        # --- Threat lifetime / rotation ---
        # Decay TTL; drop expired.
        live_threats = []
        for t in self.threats:
            t.ttl_left -= dt
            if t.ttl_left > 0:
                live_threats.append(t)
        self.threats = live_threats
        # Trim if target lowered (also handles target=0 -> clear all).
        while len(self.threats) > self.threat_target:
            self.threats.pop(0)
        # Top up to target (fresh threats get fixed lifetime; first wave gets
        # jitter so they don't all expire in sync).
        attempts = 0
        while len(self.threats) < self.threat_target and attempts < 10:
            attempts += 1
            jitter = random.uniform(0.5, 1.0) if len(self.threats) == 0 else random.uniform(0.85, 1.0)
            self._spawn_random_threat(ttl=self.threat_lifetime * jitter)

        # --- Lidars ---
        for i, ang in enumerate(a.lidar_angles):
            a.lidar_distances[i] = self.raycast(a.x, a.y, a.heading + ang, a.lidar_range)

        # Sensor signals with angular sector gating
        K_FOOD = 1500.0
        K_TH   = 2500.0
        a.food_left_signal = 0.0
        a.food_right_signal = 0.0
        a.threat_left_signal = 0.0
        a.threat_right_signal = 0.0

        food_left_arc   = SENSOR_ARCS["food_left"]
        food_right_arc  = SENSOR_ARCS["food_right"]
        threat_left_arc = SENSOR_ARCS["threat_left"]
        threat_right_arc= SENSOR_ARCS["threat_right"]

        for f in self.foods:
            dx = f.x - a.x; dy = f.y - a.y
            d2 = dx * dx + dy * dy + 4.0
            rel = _wrap_pi(math.atan2(dy, dx) - a.heading)
            contribution = K_FOOD / d2
            if _in_arc(rel, food_left_arc):
                a.food_left_signal += contribution
            if _in_arc(rel, food_right_arc):
                a.food_right_signal += contribution

        for t in self.threats:
            dx = t.x - a.x; dy = t.y - a.y
            d2 = dx * dx + dy * dy + 4.0
            rel = _wrap_pi(math.atan2(dy, dx) - a.heading)
            contribution = K_TH / d2
            if _in_arc(rel, threat_left_arc):
                a.threat_left_signal += contribution
            if _in_arc(rel, threat_right_arc):
                a.threat_right_signal += contribution

        # Food consumption (resets hunger fully)
        survivors: list[Food] = []
        for f in self.foods:
            if (a.x - f.x) ** 2 + (a.y - f.y) ** 2 < (a.radius + f.size) ** 2:
                a.food_eaten += 1
                a.health = min(1.0, a.health + 0.1)
                a.hunger = 0.0
                events["ate"] += 1
            else:
                survivors.append(f)
        self.foods = survivors

        # Replenish food up to target (no spawning if target == 0)
        attempts = 0
        while len(self.foods) < self.food_target and attempts < 10:
            attempts += 1
            self._spawn_random_food()

        # Threat damage
        for t in self.threats:
            d2 = (a.x - t.x) ** 2 + (a.y - t.y) ** 2
            if d2 < (a.radius + t.radius) ** 2:
                dmg = 0.4 * dt
                a.health = max(0.0, a.health - dmg)
                a.damage_taken += dmg
                events["hit"] += dmg

        # Hunger creeps up over time; fatigue decays toward 0
        a.hunger  = min(1.0, a.hunger  + self.hunger_rate  * dt)
        a.fatigue = max(0.0, a.fatigue - self.fatigue_decay * dt)

        return events

    def _spawn_random_food(self):
        for _ in range(20):
            x = random.uniform(15, self.width - 15)
            y = random.uniform(15, self.height - 15)
            if self._circle_free(x, y, 8.0):
                return self.add_food(x, y)

    def _spawn_random_threat(self, ttl: float | None = None):
        for _ in range(20):
            x = random.uniform(20, self.width - 20)
            y = random.uniform(20, self.height - 20)
            if (x - self.agent.x) ** 2 + (y - self.agent.y) ** 2 < 80 ** 2:
                continue
            if self._circle_free(x, y, 14.0):
                return self.add_threat(x, y, ttl=ttl)

    # ------------------------------------------------------------ motor effect
    def apply_motor(self, fwd: bool, back: bool, left: bool, right: bool) -> None:
        a = self.agent
        # Fatigue cost
        n_spikes = int(fwd) + int(back) + int(left) + int(right)
        if n_spikes > 0:
            a.fatigue = min(1.0, a.fatigue + self.fatigue_action_gain * n_spikes)

        if left:  a.heading -= a.turn_per_spike
        if right: a.heading += a.turn_per_spike
        a.heading = _wrap_pi(a.heading)
        if fwd:  self._try_move(a.speed_per_spike)
        if back: self._try_move(-a.speed_per_spike * 0.7)

    def _try_move(self, dist: float) -> None:
        a = self.agent
        nx = a.x + math.cos(a.heading) * dist
        ny = a.y + math.sin(a.heading) * dist
        if self._circle_free(nx, ny, a.radius):
            a.x = nx; a.y = ny
        else:
            if   self._circle_free(nx, a.y, a.radius): a.x = nx
            elif self._circle_free(a.x, ny, a.radius): a.y = ny

    # -------------------------------------------------------------- snapshots
    def snapshot(self) -> dict:
        a = self.agent
        return {
            "width": self.width,
            "height": self.height,
            "agent": {
                "x": a.x, "y": a.y, "heading": a.heading, "radius": a.radius,
                "lidar_angles": a.lidar_angles,
                "lidar_distances": list(a.lidar_distances),
                "lidar_range": a.lidar_range,
                "food_left":  a.food_left_signal,
                "food_right": a.food_right_signal,
                "threat_left":  a.threat_left_signal,
                "threat_right": a.threat_right_signal,
                "health":  a.health,
                "hunger":  a.hunger,
                "fatigue": a.fatigue,
                "food_eaten": a.food_eaten,
            },
            "foods":   [{"id": f.id, "x": f.x, "y": f.y, "size": f.size} for f in self.foods],
            "threats": [{"id": t.id, "x": t.x, "y": t.y, "radius": t.radius} for t in self.threats],
            "obstacles":[
                {"id": o.id, "x": o.x, "y": o.y, "w": o.w, "h": o.h} for o in self.obstacles
            ],
            "food_target":         self.food_target,
            "threat_target":       self.threat_target,
            "threat_lifetime":     self.threat_lifetime,
            "hunger_rate":         self.hunger_rate,
            "fatigue_action_gain": self.fatigue_action_gain,
            "fatigue_decay":       self.fatigue_decay,
            "sensor_arcs": {k: list(v) for k, v in SENSOR_ARCS.items()},
        }
