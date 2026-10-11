"""Versioned experiment contract. Validation is independent of the runtime."""

from __future__ import annotations

import copy
import math
import re
from typing import Any

DT = 0.01
MAX_NEURONS = 20000
MAX_SYNAPSES = 500000
MAX_DELAY = 256
KINDS = ("direct", "mod_exc", "mod_inh")
SENSORS = ["food_left", "food_right", "threat_left", "threat_right", "hunger", "fatigue"] + [
    f"lidar_{i}" for i in range(5)
]
MOTORS = ["forward", "backward", "left", "right"]
NEURON = dict(
    label="",
    kind="inter",
    x=0.0,
    y=0.0,
    threshold=1.0,
    leak=0.08,
    v_reset=0.0,
    v_min=-100.0,
    refractory=2,
    noise_std=0.0,
    bias=0.0,
    reset_mode="retain",
    mod_tau_exc=2.0,
    mod_tau_inh=2.0,
    mod_gain_exc=1.0,
    mod_gain_inh=1.0,
    polarity="mixed",
)
WORLD = dict(
    width=2400.0,
    height=1600.0,
    food_target=35,
    food_interval=0.3,
    threat_target=3,
    threat_mode="pursuit",
    threat_radius=280.0,
    threat_speed_ratio=0.72,
    chase_duration=5.0,
    cooldown=4.0,
    threat_lifetime=60.0,
    speed=150.0,
    turn_speed=3.0,
    sensor_range=380.0,
    lidar_range=180.0,
    hunger_rate=0.012,
    fatigue_gain=0.025,
    fatigue_decay=0.07,
    seed=42,
)


def number(value: Any, name: str, low: float, high: float, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name}: ожидается конечное число")
    if not low <= value <= high or (integer and int(value) != value):
        raise ValueError(f"{name}: диапазон {low}…{high}")
    return int(value) if integer else float(value)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[\w.:-]{1,80}", value):
        raise ValueError("ID: 1–80 букв, цифр, _, ., : или -")
    return value


def text(value, limit=160):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"Текст: не более {limit} символов")
    return value


def neuron(data):
    if not isinstance(data, dict):
        raise ValueError("Нейрон должен быть объектом")
    n = {**NEURON, **{k: v for k, v in data.items() if k in NEURON}, "id": identifier(data["id"])}
    n["label"] = text(n["label"]) or n["id"]
    for k, bounds in dict(
        x=(-100000, 100000),
        y=(-100000, 100000),
        threshold=(-10000, 10000),
        leak=(0, 1),
        v_reset=(-10000, 10000),
        v_min=(-10000, 0),
        noise_std=(0, 100),
        bias=(-100, 100),
        mod_tau_exc=(0.01, 3600),
        mod_tau_inh=(0.01, 3600),
        mod_gain_exc=(0, 100),
        mod_gain_inh=(0, 100),
    ).items():
        n[k] = number(n[k], k, *bounds)
    n["refractory"] = number(n["refractory"], "refractory", 0, 10000, True)
    for k, options in dict(
        kind=("sensor", "motor", "inter"),
        reset_mode=("reset", "retain"),
        polarity=("mixed", "exc", "inh"),
    ).items():
        if n[k] not in options:
            raise ValueError(f"{k}: неизвестный режим")
    return n


def topology(data):
    if not isinstance(data, dict):
        raise ValueError("Ожидается объект сети")
    if data.get("task", "BUG") != "BUG":
        raise ValueError("Поддерживается только среда BUG")
    if data.get("format_version", 2) not in (1, 2, 3):
        raise ValueError("Неизвестная версия сети")
    ns = data.get("neurons", [])
    ss = data.get("synapses", [])
    if not isinstance(ns, list) or len(ns) > MAX_NEURONS:
        raise ValueError("Лимит: 20 000 нейронов")
    if not isinstance(ss, list) or len(ss) > MAX_SYNAPSES:
        raise ValueError("Лимит: 500 000 связей")
    neurons = [
        neuron(
            {
                **n,
                **(
                    {"reset_mode": "reset"}
                    if data.get("format_version", 2) < 3 and "reset_mode" not in n
                    else {}
                ),
            }
        )
        for n in ns
    ]
    ids = {n["id"] for n in neurons}
    if len(ids) != len(neurons):
        raise ValueError("Повторяющиеся ID нейронов")
    ganglia = []
    gids = set()
    membership = set()
    ganglion_data = data.get("ganglia", [])
    frame_data = data.get("groups", [])
    if not isinstance(ganglion_data, list) or len(ganglion_data) > MAX_NEURONS:
        raise ValueError("Некорректный список ганглиев")
    if not isinstance(frame_data, list) or len(frame_data) > MAX_NEURONS:
        raise ValueError("Некорректный список рамок")
    for g in ganglion_data:
        if not isinstance(g, dict):
            raise ValueError("Ганглий должен быть объектом")
        gid = identifier(g["id"])
        if gid in gids or gid in ids:
            raise ValueError("Повторяющийся ID ганглия")
        gids.add(gid)
        members = g.get("members", [])
        if not isinstance(members, list) or not all(isinstance(m, str) for m in members):
            raise ValueError("Участники ганглия должны быть списком ID")
        if not members or len(members) != len(set(members)) or not set(members) <= ids:
            raise ValueError("Некорректные участники ганглия")
        if set(members) & membership:
            raise ValueError("Нейрон может входить только в один ганглий")
        membership.update(members)
        ganglia.append(
            dict(
                id=gid,
                label=text(g.get("label", "Ganglion")),
                members=members,
                x=number(g["x"], "x", -100000, 100000),
                y=number(g["y"], "y", -100000, 100000),
                radius=number(g["radius"], "radius", 30, 5000),
            )
        )
    synapses = []
    sids = set()
    expanded = 0
    group_sizes = {g["id"]: len(g["members"]) for g in ganglia}
    polarities = {n["id"]: n["polarity"] for n in neurons}
    for i, s in enumerate(ss):
        if not isinstance(s, dict):
            raise ValueError("Синапс должен быть объектом")
        source = s.get("source", s.get("from"))
        target = s.get("target", s.get("to"))
        if source not in ids or target not in ids | gids:
            raise ValueError(f"Связь {i}: неизвестный ID")
        kind = s.get("kind", "direct")
        if kind not in KINDS:
            raise ValueError("Неизвестный тип синапса")
        weight = number(s.get("weight", 1), "weight", -10000, 10000)
        if kind == "direct" and (
            (polarities[source] == "exc" and weight < 0)
            or (polarities[source] == "inh" and weight > 0)
        ):
            raise ValueError(f"{source}: знак связи противоречит полярности нейрона")
        sid = identifier(s.get("id", f"s{i}"))
        if sid in sids:
            raise ValueError("Повторяющийся ID синапса")
        sids.add(sid)
        expanded += group_sizes.get(target, 1)
        if expanded > MAX_SYNAPSES:
            raise ValueError("С учётом коннекторов превышен лимит 500 000 связей")
        synapses.append(
            dict(
                id=sid,
                source=source,
                target=target,
                kind=kind,
                weight=weight,
                delay=number(s.get("delay", 1), "delay", 1, MAX_DELAY, True),
            )
        )
    groups = []
    for g in frame_data:
        if not isinstance(g, dict):
            raise ValueError("Рамка должна быть объектом")
        groups.append(
            dict(
                id=identifier(str(g.get("id", f"frame{len(groups)}"))),
                label=text(g.get("label", "")),
                comment=text(g.get("comment", ""), 2000),
                color=text(g.get("color", "#657586"), 32),
                **{
                    k: number(g[k], k, -100000 if k in ("x", "y") else 1, 100000)
                    for k in ("x", "y", "w", "h")
                },
            )
        )
    return dict(
        format_version=3,
        task="BUG",
        neurons=neurons,
        synapses=synapses,
        ganglia=ganglia,
        groups=groups,
    )


def world_config(data):
    if not isinstance(data, dict):
        raise ValueError("Настройки мира должны быть объектом")
    d = {**WORLD, **{k: v for k, v in data.items() if k in WORLD}}
    ranges = dict(
        width=(400, 12000),
        height=(400, 12000),
        food_target=(0, 500),
        food_interval=(0.01, 60),
        threat_target=(0, 100),
        threat_radius=(20, 2000),
        threat_speed_ratio=(0.05, 0.95),
        chase_duration=(0.1, 120),
        cooldown=(0.1, 120),
        threat_lifetime=(1, 3600),
        speed=(10, 400),
        turn_speed=(0.1, 10),
        sensor_range=(20, 2000),
        lidar_range=(20, 2000),
        hunger_rate=(0, 1),
        fatigue_gain=(0, 1),
        fatigue_decay=(0, 1),
        seed=(0, 2147483647),
    )
    for k, b in ranges.items():
        d[k] = number(d[k], k, *b, k in ("food_target", "threat_target", "seed"))
    if d["threat_mode"] not in ("static", "pursuit"):
        raise ValueError("Неизвестный режим угрозы")
    return d


def bindings(data, net):
    if not isinstance(data, dict):
        raise ValueError("Назначения должны быть объектом")
    ids = {n["id"] for n in net["neurons"]}
    out = {}
    for channel in SENSORS + MOTORS:
        nid = data.get(channel, "")
        if nid and nid not in ids:
            raise ValueError(f"{channel}: нейрон {nid} не существует")
        out[channel] = nid
    return out


def default_bindings():
    return {c: (c if c.startswith("lidar") else "sensor_" + c) for c in SENSORS} | {
        c: "motor_" + c for c in MOTORS
    }


def default_topology():
    b = default_bindings()
    ns = []
    for i, c in enumerate(SENSORS):
        ns.append(
            dict(
                id=b[c],
                label=c.replace("_", " ").title(),
                kind="sensor",
                x=100,
                y=80 + i * 66,
                leak=0.02,
            )
        )
    for i, c in enumerate(MOTORS):
        ns.append(
            dict(
                id=b[c],
                label=c.title(),
                kind="motor",
                x=1000,
                y=200 + i * 125,
                leak=0.12,
                refractory=3,
            )
        )
    ns += [
        dict(id="drive", label="Tonic drive", x=560, y=160, bias=0.16, leak=0.02),
        dict(id="explore", label="Explore", x=560, y=460, bias=0.018, noise_std=0.025, leak=0.01),
    ]
    ss = []

    def edge(a, b, w=1.0, d=3):
        ss.append(dict(source=a, target=b, weight=w, delay=d))

    edge("drive", "motor_forward", 1.2)
    edge("explore", "motor_right", 0.8)
    for side, opposite in [("left", "right"), ("right", "left")]:
        edge("sensor_food_" + side, "motor_" + side, 0.65)
        edge("sensor_threat_" + side, "motor_" + opposite, 1.5)
        edge("sensor_threat_" + side, "motor_forward", 0.8)
    edge("lidar_0", "motor_right", 1.2)
    edge("lidar_4", "motor_left", 1.2)
    edge("lidar_2", "motor_backward", 1.2)
    edge("lidar_2", "motor_left", 1.3)
    edge("sensor_fatigue", "motor_forward", -0.3)
    return topology(dict(format_version=3, neurons=ns, synapses=ss))


def migrate_project(data):
    if not isinstance(data, dict):
        raise ValueError("Ожидается JSON-объект")
    if "topology" in data and data.get("version", 1) != 1:
        raise ValueError("Неизвестная версия эксперимента")
    net = topology(data.get("topology", data))
    ids = {n["id"] for n in net["neurons"]}
    b = data.get("bindings", {k: v if v in ids else "" for k, v in default_bindings().items()})
    world = data.get("world", {})
    if not isinstance(world, dict):
        raise ValueError("Мир должен быть объектом")
    for key in ("objects", "zones"):
        if not isinstance(world.get(key, []), list) or not all(
            isinstance(o, dict) for o in world.get(key, [])
        ):
            raise ValueError("Объекты и зоны должны быть списками объектов")
    if not isinstance(world.get("spawn", {}), dict):
        raise ValueError("Точка старта должна быть объектом")
    return dict(
        version=1,
        name=text(data.get("name", "Untitled experiment")),
        topology=net,
        bindings=bindings(b, net),
        world={
            "config": world_config(world.get("config", {})),
            "objects": copy.deepcopy(world.get("objects", [])),
            "zones": copy.deepcopy(world.get("zones", [])),
            "spawn": copy.deepcopy(world.get("spawn", {"x": 300.0, "y": 800.0, "heading": 0.0})),
        },
    )
