"""One authoritative clock and revision shared by both clients."""

from __future__ import annotations
import copy
import json
import logging
import os
from pathlib import Path
import threading
import time
from collections import deque
import numpy as np
from . import schema
from .devices import create_network, devices
from .world import World
from .generators import ganglion, maze, connect_ganglia


class Conflict(ValueError):
    pass


class Runtime:
    def __init__(self, path: Path | None = None):
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.path = path
        initial = dict(
            version=1,
            name="Forager · 01",
            topology=schema.default_topology(),
            bindings=schema.default_bindings(),
            world={},
        )
        if path and path.exists():
            initial = json.loads(path.read_text())
        p = schema.migrate_project(initial)
        self.name = p["name"]
        self.world = World(p["world"])
        self.device_notice = ""
        requested = initial.get("compute", {}).get("device", "cpu")
        try:
            self.net = create_network(p["topology"], self.world.config["seed"], requested)
        except ValueError as exc:
            self.device_notice = f"Устройство {requested} недоступно; выбран CPU. {exc}"
            self.net = create_network(p["topology"], self.world.config["seed"])
        self.bindings = p["bindings"]
        self.revision = 1
        self.running = False
        self.speed = 1.0
        self.ticks = 0
        self.session = 1
        self.manual = {}
        self.manual_until = 0.0
        self.inject = {}
        self.history = deque(maxlen=300)
        self.window_counts = np.zeros(self.net.n, np.int64)
        self.window_ticks = 0
        self.last_step_ms = 0.0
        self.overruns = 0
        self.error = None
        self._prime_world()

    def _prime_world(self):
        for _ in range(
            max(
                0,
                self.world.config["food_target"]
                - sum(o["kind"] == "food" for o in self.world.objects),
            )
        ):
            p = self.world.random_point(7, True)
            if p:
                self.world.add_object(dict(kind="food", x=p[0], y=p[1]))
        for _ in range(
            max(
                0,
                self.world.config["threat_target"]
                - sum(o["kind"] == "threat" for o in self.world.objects),
            )
        ):
            p = self.world.random_point(16)
            if (
                p
                and ((p[0] - self.world.agent["x"]) ** 2 + (p[1] - self.world.agent["y"]) ** 2)
                ** 0.5
                > self.world.config["threat_radius"]
            ):
                self.world.add_object(dict(kind="threat", x=p[0], y=p[1]))
        self.world.sense()

    def project(self):
        return dict(
            version=1,
            name=self.name,
            topology=self.net.topology,
            bindings=self.bindings,
            world=self.world.export(),
            revision=self.revision,
            compute=dict(device=self.net.device),
        )

    def save(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.project(), ensure_ascii=False, allow_nan=False))
        os.replace(temp, self.path)

    def _replace_net(self, net, preserve=True):
        new = create_network(net, self.world.config["seed"], self.net.device)
        if preserve:
            pairs = [
                (i, self.net.index[nid]) for i, nid in enumerate(new.ids) if nid in self.net.index
            ]
            for key in ("V", "refr", "sensitivity", "total"):
                before, after = self.net.host_values(key), new.host_values(key)
                for i, old in pairs:
                    after[i] = before[old]
                new.set_values(key, after)
            new.tick = self.net.tick
            new.rng.bit_generator.state = copy.deepcopy(self.net.rng.bit_generator.state)
        new.synchronize()
        self.net = new
        self.window_counts = np.zeros(new.n, np.int64)
        self.window_ticks = 0
        self.history.clear()
        self.session += 1

    def command(self, action, data, revision=None):
        with self.lock:
            if not isinstance(data, dict):
                raise ValueError("Ожидается JSON-объект команды")
            if action == "save":
                self.save()
                return {"revision": self.revision}
            if action == "control":
                mode = data.get("mode")
                if mode == "play":
                    self.running = True
                    self.error = None
                elif mode == "pause":
                    self.running = False
                elif mode == "step":
                    if self.running:
                        raise ValueError("Сначала поставьте симуляцию на паузу")
                    self.step()
                elif mode == "reset":
                    self.running = False
                    self.manual = {}
                    self.inject.clear()
                    self._replace_net(self.net.topology, False)
                    self.world.reset_agent()
                    self.world.sense()
                    self.ticks = 0
                else:
                    raise ValueError("Неизвестная команда")
                return {"revision": self.revision}
            if action == "speed":
                self.speed = schema.number(data.get("value"), "speed", 0.1, 5)
                return {"revision": self.revision}
            if action == "manual":
                self.manual = {k: bool(data.get(k, False)) for k in schema.MOTORS}
                self.manual_until = time.monotonic() + 0.35
                return {"revision": self.revision}
            if action == "inject":
                nid = data.get("id")
                if nid not in self.net.index:
                    raise ValueError("Нейрон не найден")
                self.inject[nid] = schema.number(data.get("current", 2), "current", -100, 100)
                return {"revision": self.revision}
            if revision != self.revision:
                raise Conflict(
                    "Проект изменён в другом окне. Данные обновлены; повторите действие."
                )
            if action == "compute":
                device = data.get("device")
                if not isinstance(device, str):
                    raise ValueError("Укажите вычислительное устройство")
                if device != self.net.device:
                    # Construct and transfer first: a rejected switch leaves the old kernel intact.
                    new = create_network(self.net.topology, self.world.config["seed"], device)
                    for key in self.net.state_fields:
                        new.set_values(key, self.net.host_values(key))
                    new.tick = self.net.tick
                    new.rng.bit_generator.state = copy.deepcopy(self.net.rng.bit_generator.state)
                    new.synchronize()
                    self.net = new
                    self.last_step_ms = 0.0
                self.device_notice = ""
            elif action == "topology":
                net = schema.topology(data)
                b = {
                    k: v if v in {n["id"] for n in net["neurons"]} else ""
                    for k, v in self.bindings.items()
                }
                old = self.net.topology
                visual_keys = {"x", "y", "label"}

                def neuron_dynamics(ns):
                    return [{k: v for k, v in n.items() if k not in visual_keys} for n in ns]

                def group_members(gs):
                    return [(g["id"], g["members"]) for g in gs]

                if (
                    neuron_dynamics(old["neurons"]) == neuron_dynamics(net["neurons"])
                    and old["synapses"] == net["synapses"]
                    and group_members(old["ganglia"]) == group_members(net["ganglia"])
                ):
                    self.net.topology = net
                else:
                    self._replace_net(net)
                self.bindings = b
            elif action == "positions":
                updates = data.get("positions", [])
                valid = []
                for u in updates:
                    if u["id"] not in self.net.index:
                        raise ValueError("Нейрон не найден")
                    valid.append(
                        (
                            u["id"],
                            schema.number(u["x"], "x", -100000, 100000),
                            schema.number(u["y"], "y", -100000, 100000),
                        )
                    )
                for nid, x, y in valid:
                    n = self.net.topology["neurons"][self.net.index[nid]]
                    n["x"] = x
                    n["y"] = y
            elif action == "ganglion":
                self._replace_net(ganglion(self.net.topology, data))
            elif action == "connect_ganglia":
                net = connect_ganglia(self.net.topology, data)
                added = len(net["synapses"]) - len(self.net.topology["synapses"])
                if added:
                    self._replace_net(net)
                self.revision += 1
                self.save()
                return {"revision": self.revision, "added_synapses": added}
            elif action == "move_ganglion":
                group = next(
                    (g for g in self.net.topology["ganglia"] if g["id"] == data.get("id")), None
                )
                if group is None:
                    raise ValueError("Ганглий не найден")
                dx = schema.number(data.get("dx"), "dx", -200000, 200000)
                dy = schema.number(data.get("dy"), "dy", -200000, 200000)
                members = [
                    self.net.topology["neurons"][self.net.index[nid]] for nid in group["members"]
                ]
                for item in [group, *members]:
                    schema.number(item["x"] + dx, "x", -100000, 100000)
                    schema.number(item["y"] + dy, "y", -100000, 100000)
                for item in [group, *members]:
                    item["x"] += dx
                    item["y"] += dy
            elif action == "bindings":
                self.bindings = schema.bindings(data, self.net.topology)
            elif action == "new_document":
                self._replace_net(schema.default_topology(), preserve=False)
                self.bindings = schema.default_bindings()
                self.name = "Новая нервная система"
                self.running = False
                self.manual = {}
                self.manual_until = 0.0
                self.inject.clear()
                self.ticks = 0
                self.error = None
                self.last_step_ms = 0.0
                self.overruns = 0
            elif action == "import":
                p = schema.migrate_project(data)
                world = World(p["world"])
                net = create_network(p["topology"], world.config["seed"], self.net.device)
                self.running = False
                self.manual = {}
                self.inject.clear()
                self.name = p["name"]
                self.world = world
                self.net = net
                self.bindings = p["bindings"]
                self.ticks = 0
                self.history.clear()
                self.window_counts = np.zeros(net.n, np.int64)
                self.window_ticks = 0
                self.session += 1
            elif action in ("world_config", "place", "zone", "remove", "clear", "maze", "spawn"):
                w = copy.deepcopy(self.world)
                if action == "world_config":
                    cfg = schema.world_config({**w.config, **data})
                    w.config = cfg
                    if not w.free(w.agent["x"], w.agent["y"]):
                        raise ValueError("Жук окажется вне новой арены")
                    for o in w.objects:
                        if (
                            o["x"] + o.get("w", o.get("radius", 0)) > cfg["width"]
                            or o["y"] + o.get("h", o.get("radius", 0)) > cfg["height"]
                        ):
                            raise ValueError("Объекты окажутся вне новой арены")
                    for z in w.zones:
                        if z["x"] + z["w"] > cfg["width"] or z["y"] + z["h"] > cfg["height"]:
                            raise ValueError("Зоны окажутся вне новой арены")
                    if "seed" in data:
                        w.rng.seed(cfg["seed"])
                    for kind in ("food", "threat"):
                        matches = [o for o in w.objects if o["kind"] == kind]
                        for o in matches[int(cfg[kind + "_target"]) :]:
                            w.objects.remove(o)
                    if "threat_mode" in data:
                        for o in w.objects:
                            if o["kind"] == "threat":
                                o.update(
                                    mode=cfg["threat_mode"], state="idle", rest=0.0, interest=0.0
                                )
                elif action == "place":
                    w.add_object(data)
                elif action == "zone":
                    w.add_zone(data)
                elif action == "remove":
                    w.objects = [o for o in w.objects if o["id"] != data["id"]]
                    w.zones = [z for z in w.zones if z["id"] != data["id"]]
                elif action == "clear":
                    kind = data.get("kind", "obstacle")
                    if kind not in ("obstacle", "food", "threat", "zone"):
                        raise ValueError("Неизвестный вид объектов")
                    if kind == "zone":
                        w.zones = []
                    else:
                        w.objects = [o for o in w.objects if o["kind"] != kind]
                elif action == "spawn":
                    x = schema.number(data["x"], "x", 0, w.config["width"])
                    y = schema.number(data["y"], "y", 0, w.config["height"])
                    if not w.free(x, y):
                        raise ValueError("Здесь недостаточно места для жука")
                    w.spawn = dict(x=x, y=y, heading=0.0)
                    w.reset_agent()
                elif action == "maze":
                    walls, spawn = maze(
                        w.config["width"],
                        w.config["height"],
                        data.get("cols", 12),
                        data.get("rows", 8),
                        data.get("seed", 42),
                    )
                    w.objects = []
                    w.zones = []
                    w.spawn = spawn
                    w.agent["x"] = spawn["x"]
                    w.agent["y"] = spawn["y"]
                    for o in walls:
                        w.add_object(o)
                    w.reset_agent()
                w.sense()
                self.world = w
            elif action == "name":
                self.name = schema.text(data["name"])
            else:
                raise ValueError("Неизвестное действие")
            self.revision += 1
            self.save()
            return {"revision": self.revision}

    def step(self):
        start = time.perf_counter()
        external = np.zeros(self.net.n, np.float32)
        for channel, value in self.world.sensors.items():
            i = self.net.index.get(self.bindings.get(channel))
            if i is not None:
                external[i] += value
        for nid, value in self.inject.items():
            if nid in self.net.index:
                external[self.net.index[nid]] += value
        self.inject.clear()
        spikes = self.net.step(external)
        motors = {
            k: bool(spikes[self.net.index[v]]) if v in self.net.index else False
            for k, v in self.bindings.items()
            if k in schema.MOTORS
        }
        self.world.step(motors, manual=self.active_manual())
        self.ticks += 1
        self.window_ticks += 1
        self.window_counts += spikes
        if self.window_ticks >= 10:
            duration = self.window_ticks * schema.DT
            rates = {"all": float(self.window_counts.sum() / max(1, self.net.n) / duration)}
            for gid, idx in self.net.groups.items():
                rates[gid] = float(self.window_counts[idx].sum() / len(idx) / duration)
            self.history.append(
                dict(t=self.ticks * schema.DT, rates=rates, spikes=int(self.window_counts.sum()))
            )
            self.window_ticks = 0
            self.window_counts.fill(0)
        self.last_step_ms = 0.95 * self.last_step_ms + 0.05 * (time.perf_counter() - start) * 1000

    def snapshot(self):
        with self.lock:
            n = self.net
            # Cumulative spike counts cannot be consumed by one client or lost between frames.
            limit = 2000
            potential = n.host_values("V", limit)
            counts = n.host_values("total", limit)
            sensitivity = n.host_values("sensitivity", limit)
            return dict(
                revision=self.revision,
                session=self.session,
                t=round(self.ticks * schema.DT, 3),
                running=self.running,
                speed=self.speed,
                world=self.world.snapshot(),
                activity=dict(
                    ids=n.ids[:limit],
                    v=potential.tolist(),
                    counts=counts.tolist(),
                    exc=sensitivity[:, 0].tolist(),
                    inh=sensitivity[:, 1].tolist(),
                    sampled=n.n > limit,
                    total=n.n,
                ),
                history=list(self.history),
                stats=dict(
                    neurons=n.n,
                    synapses=len(n.sources),
                    step_ms=round(self.last_step_ms, 3),
                    memory_mb=round(n.memory_bytes / 1048576, 2),
                    overruns=self.overruns,
                    backend=n.backend,
                ),
                compute=dict(device=n.device, notice=self.device_notice),
                error=self.error,
            )

    def compute_devices(self):
        with self.lock:
            return dict(devices=devices(), device=self.net.device, notice=self.device_notice)

    def active_manual(self):
        return (
            self.manual
            if time.monotonic() < self.manual_until and any(self.manual.values())
            else None
        )

    def jog(self, duration):
        """Move the paused bug manually without advancing neural or world time."""
        manual = self.active_manual()
        if manual:
            self.world.drive(manual, min(duration, 0.05))
            self.world.sense()

    def loop(self):
        last = time.monotonic()
        acc = 0.0
        while not self.stop_event.wait(0.002):
            now = time.monotonic()
            elapsed = now - last
            last = now
            with self.lock:
                if not self.running:
                    self.jog(elapsed)
                    acc = 0.0
                    continue
                acc += elapsed * self.speed
                steps = min(20, int(acc / schema.DT))
                try:
                    for _ in range(steps):
                        self.step()
                        acc -= schema.DT
                    if acc > 0.5:
                        self.overruns += 1
                        acc = 0.0
                except Exception as exc:
                    logging.exception("Simulation paused after runtime error")
                    self.running = False
                    self.error = str(exc)
