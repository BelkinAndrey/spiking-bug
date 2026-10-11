"""Seeded, bounded generators. Generator settings are data, never executable input."""

import math
import random
from .schema import number, identifier, neuron, topology, MAX_SYNAPSES


def ganglion(net, params):
    gid = identifier(params.get("id", "g1"))
    count = number(params.get("count", 40), "count", 1, 2000, True)
    radius = number(params.get("radius", 180), "radius", 30, 5000)
    density = number(params.get("density", 0.08), "density", 0, 1)
    max_distance = number(params.get("max_distance", 0), "max_distance", 0, 300000)
    fraction = number(params.get("excitatory", 0.8), "excitatory", 0, 1)
    weight = number(params.get("weight", 0.5), "weight", 0, 100)
    delay = number(params.get("delay", 2), "delay", 1, 256, True)
    mode = params.get("mode", "neurons")
    if mode not in ("neurons", "synapses"):
        raise ValueError("Неизвестный режим полярности")
    seed = number(params.get("seed", 42), "seed", 0, 2147483647, True)
    x = number(params.get("x", 550), "x", -90000, 90000)
    y = number(params.get("y", 400), "y", -90000, 90000)
    rng = random.Random(seed)
    members = []
    ns = []
    ss = []
    for i in range(count):
        a = rng.random() * math.tau
        r = math.sqrt(rng.random()) * radius * 0.86
        nid = f"{gid}.n{i + 1}"
        members.append(nid)
        polarity = ("exc" if rng.random() < fraction else "inh") if mode == "neurons" else "mixed"
        ns.append(
            neuron(
                {
                    **params.get("neuron", {}),
                    "id": nid,
                    "label": f"{i + 1}",
                    "x": x + math.cos(a) * r,
                    "y": y + math.sin(a) * r,
                    "polarity": polarity,
                }
            )
        )
    # Geometric skips generate Bernoulli edges without a dense adjacency matrix.
    for i, n in enumerate(ns):
        j = -1
        while density > 0:
            j += 1 if density == 1 else 1 + int(math.log1p(-rng.random()) / math.log1p(-density))
            if j >= count:
                break
            if j == i:
                continue
            if max_distance and math.hypot(n["x"] - ns[j]["x"], n["y"] - ns[j]["y"]) > max_distance:
                continue
            sign = (
                1
                if n["polarity"] == "exc" or (n["polarity"] == "mixed" and rng.random() < fraction)
                else -1
            )
            ss.append(
                dict(
                    id=f"{gid}.s{len(ss)}",
                    source=n["id"],
                    target=members[j],
                    kind="direct",
                    weight=weight * sign,
                    delay=delay,
                )
            )
            if len(ss) + len(net["synapses"]) > MAX_SYNAPSES:
                raise ValueError("Слишком много связей; уменьшите плотность")
    return topology(
        {
            **net,
            "neurons": net["neurons"] + ns,
            "synapses": net["synapses"] + ss,
            "ganglia": net["ganglia"]
            + [
                dict(
                    id=gid,
                    label=params.get("label", "Ganglion"),
                    x=x,
                    y=y,
                    radius=radius,
                    members=members,
                )
            ],
        }
    )


def maze(width, height, cols=12, rows=8, seed=42):
    cols = number(cols, "cols", 2, 40, True)
    rows = number(rows, "rows", 2, 40, True)
    rng = random.Random(number(seed, "seed", 0, 2147483647, True))
    cellw = width / cols
    cellh = height / rows
    if min(cellw, cellh) < 50:
        raise ValueError("Коридоры должны быть шире 50 единиц")
    visited = {(0, 0)}
    stack = [(0, 0)]
    passages = set()
    while stack:
        x, y = stack[-1]
        choices = [
            (nx, ny)
            for nx, ny in [(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)]
            if 0 <= nx < cols and 0 <= ny < rows and (nx, ny) not in visited
        ]
        if not choices:
            stack.pop()
            continue
        nxt = rng.choice(choices)
        passages.add(frozenset(((x, y), nxt)))
        visited.add(nxt)
        stack.append(nxt)
    walls = []
    for y in range(rows):
        for x in range(cols):
            if x + 1 < cols and frozenset(((x, y), (x + 1, y))) not in passages:
                walls.append(
                    dict(
                        kind="obstacle",
                        x=(x + 1) * cellw - 5,
                        y=y * cellh,
                        w=10,
                        h=min(cellh + 5, height - y * cellh),
                    )
                )
            if y + 1 < rows and frozenset(((x, y), (x, y + 1))) not in passages:
                walls.append(
                    dict(
                        kind="obstacle",
                        x=x * cellw,
                        y=(y + 1) * cellh - 5,
                        w=min(cellw + 5, width - x * cellw),
                        h=10,
                    )
                )
    return walls, dict(x=cellw / 2, y=cellh / 2, heading=0.0)


def connect_ganglia(net, params):
    """Generate directed neuron-to-neuron edges, excluding existing same-kind pairs."""
    groups = {g["id"]: g for g in net["ganglia"]}
    source, target = params.get("source"), params.get("target")
    if source not in groups or target not in groups or source == target:
        raise ValueError("Выберите два разных существующих ганглия")
    density = number(params.get("density", 0.1), "density", 0, 1)
    weight = number(params.get("weight", 0.5), "weight", -10000, 10000)
    delay = number(params.get("delay", 1), "delay", 1, 256, True)
    seed = number(params.get("seed", 42), "seed", 0, 2147483647, True)
    max_distance = number(params.get("max_distance", 0), "max_distance", 0, 300000)
    kind = params.get("kind", "direct")
    if kind not in ("direct", "mod_exc", "mod_inh"):
        raise ValueError("Неизвестный тип связи")
    prefix = identifier(params.get("id", f"projection_{seed}"))
    rng = random.Random(seed)
    nodes = {n["id"]: n for n in net["neurons"]}
    pairs = {(s["source"], s["target"], s["kind"]) for s in net["synapses"]}
    used_ids = {s["id"] for s in net["synapses"]}
    additions = []
    destinations = groups[target]["members"]
    for i, src in enumerate(groups[source]["members"]):
        j = -1
        while density > 0:
            j += 1 if density == 1 else 1 + int(math.log1p(-rng.random()) / math.log1p(-density))
            if j >= len(destinations):
                break
            dst = destinations[j]
            if (src, dst, kind) in pairs:
                continue
            a, b = nodes[src], nodes[dst]
            if max_distance and math.hypot(a["x"] - b["x"], a["y"] - b["y"]) > max_distance:
                continue
            w = weight
            if kind == "direct" and a["polarity"] != "mixed":
                w = abs(weight) * (1 if a["polarity"] == "exc" else -1)
            sid = f"{prefix}.{i}.{j}"
            suffix = len(used_ids)
            while sid in used_ids:
                sid = f"{prefix}.{suffix}"
                suffix += 1
            used_ids.add(sid)
            additions.append(dict(id=sid, source=src, target=dst, kind=kind, weight=w, delay=delay))
            if len(net["synapses"]) + len(additions) > MAX_SYNAPSES:
                raise ValueError("Слишком много связей; уменьшите плотность")
    return topology({**net, "synapses": net["synapses"] + additions})
