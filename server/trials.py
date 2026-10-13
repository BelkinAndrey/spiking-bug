"""Isolated, unpaced evaluation of a frozen project; never edits the live runtime."""

from __future__ import annotations

import copy
import logging
import math
import multiprocessing as mp
import threading
import time
import uuid
import numpy as np
from . import schema
from .devices import create_network
from .world import World


def settings(data):
    if not isinstance(data, dict):
        raise ValueError("Ожидается JSON-объект команды")
    if "randomize" in data and not isinstance(data["randomize"], bool):
        raise ValueError("randomize: expected boolean")
    return dict(
        attempts=schema.number(data.get("attempts", 30), "attempts", 1, 1000, True),
        duration=schema.number(data.get("duration", 120), "duration", 1, 3600, True),
        seed=schema.number(data.get("seed", 42), "seed", 0, 2147483647, True),
        randomize=data.get("randomize", False) is True,
    )


def summarize(rows):
    if not rows:
        return None
    metrics = {}
    for key in (
        "duration",
        "food",
        "food_per_minute",
        "health",
        "damage",
        "distance",
        "blocked_pct",
        "firing_hz",
    ):
        values = np.array([r[key] for r in rows], dtype=float)
        metrics[key] = dict(
            mean=float(values.mean()),
            std=float(values.std()),
            min=float(values.min()),
            max=float(values.max()),
        )
    return dict(survival_pct=100 * sum(r["survived"] for r in rows) / len(rows), metrics=metrics)


def run_attempt(project, options, index, stop, progress):
    seed = (options["seed"] + index) % 2147483648
    world_data = copy.deepcopy(project["world"])
    world_data["config"]["seed"] = seed
    if options["randomize"]:
        world_data["objects"] = [o for o in world_data["objects"] if o["kind"] == "obstacle"]
    world = World(world_data)
    if options["randomize"]:
        # Same placement rules as a fresh interactive world, including food zones.
        for kind, radius in (("food", 7), ("threat", 16)):
            for _ in range(world.config[kind + "_target"]):
                p = world.random_point(radius, kind == "food")
                if p and (
                    kind == "food"
                    or math.hypot(p[0] - world.agent["x"], p[1] - world.agent["y"])
                    > world.config["threat_radius"]
                ):
                    world.add_object(dict(kind=kind, x=p[0], y=p[1]))
        world.sense()
    net = create_network(project["topology"], seed, project["compute"]["device"])
    bindings = project["bindings"]
    sensors = [
        (key, net.index[nid])
        for key, nid in bindings.items()
        if key in schema.SENSORS and nid in net.index
    ]
    motors = [
        (key, net.index[nid])
        for key, nid in bindings.items()
        if key in schema.MOTORS and nid in net.index
    ]
    external = np.zeros(net.n, np.float32)
    limit = round(options["duration"] / schema.DT)
    distance = spike_count = blocked = movement_commands = 0
    tick = 0
    last_report = time.monotonic()
    for tick in range(1, limit + 1):
        if tick % 32 == 1 and stop.is_set():
            progress(tick - 1, limit)
            return None
        external.fill(0)
        for key, i in sensors:
            external[i] += world.sensors[key]
        spikes = net.step(external)
        commands = {key: bool(spikes[i]) for key, i in motors}
        before = world.agent["x"], world.agent["y"]
        world.step(commands)
        moved = math.hypot(world.agent["x"] - before[0], world.agent["y"] - before[1])
        distance += moved
        spike_count += int(spikes.sum())
        if commands.get("forward") or commands.get("backward"):
            movement_commands += 1
            blocked += moved < 1e-9
        now = time.monotonic()
        if now - last_report >= 0.15:
            progress(tick, limit)
            last_report = now
        if world.agent["health"] <= 0:
            break
    seconds = tick * schema.DT
    agent = world.agent
    return dict(
        attempt=index + 1,
        seed=seed,
        duration=seconds,
        survived=agent["health"] > 0,
        food=agent["eaten"],
        food_per_minute=agent["eaten"] * 60 / seconds,
        health=agent["health"] * 100,
        damage=agent["damage"] * 100,
        distance=distance,
        blocked_pct=100 * blocked / max(1, movement_commands),
        firing_hz=spike_count / max(1, net.n) / seconds,
    )


def evaluate(project, options, stop, publish):
    rows = []
    start = time.monotonic()
    simulated = 0.0
    in_flight = 0.0

    def report(status, current=0.0, error=None):
        elapsed = time.monotonic() - start
        publish(
            dict(
                status=status,
                completed=len(rows),
                current_seconds=current,
                progress=(len(rows) + current / options["duration"]) / options["attempts"],
                elapsed_seconds=elapsed,
                simulated_seconds=simulated + current,
                speedup=(simulated + current) / max(elapsed, 1e-9),
                rows=list(rows),
                summary=summarize(rows),
                error=error,
            )
        )

    def on_progress(tick, limit):
        nonlocal in_flight
        in_flight = tick * schema.DT
        report("running", in_flight)

    try:
        report("running")
        for index in range(options["attempts"]):
            if stop.is_set():
                break
            row = run_attempt(
                project,
                options,
                index,
                stop,
                on_progress,
            )
            if row is None:
                break
            rows.append(row)
            simulated += row["duration"]
            in_flight = 0.0
            report("running")
        report("completed" if len(rows) == options["attempts"] else "cancelled", in_flight)
    except Exception as exc:
        logging.exception("Trial evaluation failed")
        report("failed", in_flight, error=str(exc))


def _worker(project, options, stop, pipe):
    try:
        evaluate(project, options, stop, pipe.send)
    finally:
        pipe.close()


class Trials:
    def __init__(self):
        self.lock = threading.RLock()
        self.job = None
        self.process = None
        self.stop = None
        self.context = mp.get_context("spawn")

    def start(self, runtime, data, revision):
        from .runtime import Conflict

        options = settings(data)
        with self.lock:
            if self.process is not None and self.process.is_alive():
                raise Conflict("Испытание уже выполняется")
            with runtime.lock:
                if revision != runtime.revision:
                    raise Conflict(
                        "Проект изменён в другом окне. Данные обновлены; повторите действие."
                    )
                project = copy.deepcopy(runtime.project())
            read, write = self.context.Pipe(duplex=False)
            self.stop = self.context.Event()
            self.job = dict(
                id=uuid.uuid4().hex,
                status="running",
                settings=options,
                project_name=project["name"],
                revision=revision,
                device=project["compute"]["device"],
                completed=0,
                current_seconds=0,
                progress=0,
                elapsed_seconds=0,
                simulated_seconds=0,
                speedup=0,
                rows=[],
                summary=None,
                error=None,
            )
            self.process = self.context.Process(
                target=_worker, args=(project, options, self.stop, write), daemon=True
            )
            try:
                self.process.start()
            except Exception:
                read.close()
                write.close()
                self.job = None
                self.process = None
                raise
            write.close()
            threading.Thread(
                target=self._collect, args=(self.process, read, self.job["id"]), daemon=True
            ).start()
            return copy.deepcopy(self.job)

    def _collect(self, process, pipe, job_id):
        try:
            while True:
                update = pipe.recv()
                with self.lock:
                    if self.job and self.job["id"] == job_id:
                        if self.job["status"] == "cancelling" and update["status"] == "running":
                            update["status"] = "cancelling"
                        self.job.update(update)
        except EOFError:
            pass
        finally:
            pipe.close()
            process.join()
            with self.lock:
                if (
                    self.job
                    and self.job["id"] == job_id
                    and self.job["status"] in ("running", "cancelling")
                ):
                    self.job.update(
                        status="failed", error="Процесс испытания завершился без результата"
                    )

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.job)

    def cancel(self, job_id):
        with self.lock:
            if (
                self.job
                and self.job["id"] == job_id
                and self.job["status"] in ("running", "cancelling")
            ):
                self.stop.set()
                self.job["status"] = "cancelling"
            return copy.deepcopy(self.job)

    def close(self):
        if self.process is not None:
            self.stop.set()
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=1)
