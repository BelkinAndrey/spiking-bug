"""Deterministic spring layout of the editor drawing; never changes neural dynamics."""

from collections import defaultdict, deque
import copy
import math

import numpy as np

from . import schema


def _distances(adjacency, starts):
    distances = np.full(len(adjacency), -1, dtype=np.int32)
    queue = deque(starts)
    for i in starts:
        distances[i] = 0
    while queue:
        i = queue.popleft()
        for j in adjacency[i]:
            if distances[j] < 0:
                distances[j] = distances[i] + 1
                queue.append(j)
    return distances


def arrange(topology, bindings):
    net = copy.deepcopy(topology)
    neurons = sorted(net["neurons"], key=lambda n: n["id"])
    if not neurons:
        return net
    ganglia = sorted(net["ganglia"], key=lambda g: g["id"])
    # Virtual connector vertices avoid expanding a compact group-to-group edge.
    elements = neurons + ganglia
    index = {n["id"]: i for i, n in enumerate(elements)}
    count = len(elements)
    sensor_ids = {bindings.get(c) for c in schema.SENSORS} - {None, ""}
    motor_ids = {bindings.get(c) for c in schema.MOTORS} - {None, ""}
    if sensor_ids & motor_ids:
        raise ValueError(
            "Один нейрон назначен и рецептором, и мотором: разделите назначения перед раскладкой"
        )
    assigned = sensor_ids | motor_ids
    sensor_ids |= {n["id"] for n in neurons if n["kind"] == "sensor" and n["id"] not in assigned}
    motor_ids |= {n["id"] for n in neurons if n["kind"] == "motor" and n["id"] not in assigned}

    def ports(channels, ids):
        ordered = list(dict.fromkeys(bindings.get(c) for c in channels))
        return [index[nid] for nid in ordered if nid in ids] + [
            index[nid] for nid in sorted(ids) if nid not in ordered
        ]

    left, right = ports(schema.SENSORS, sensor_ids), ports(schema.MOTORS, motor_ids)
    fixed = np.zeros(count, dtype=bool)
    fixed[left + right] = True
    edges = {}
    for edge in net["synapses"]:
        a, b = index[edge["source"]], index[edge["target"]]
        if a != b:
            edges[a, b] = 1.0
    for group in ganglia:
        a = index[group["id"]]
        for nid in group["members"]:
            b = index[nid]
            edges.setdefault((a, b), 0.35)
            edges.setdefault((b, a), 0.35)
    outgoing = [[] for _ in elements]
    incoming = [[] for _ in elements]
    for a, b in sorted(edges):
        outgoing[a].append(b)
        incoming[b].append(a)
    from_sensors = _distances(outgoing, left)
    to_motors = _distances(incoming, right)
    layers = max(3, min(32, math.ceil(math.sqrt(count))))
    rank = np.full(count, layers // 2, dtype=int)
    for i in range(count):
        a, b = from_sensors[i], to_motors[i]
        if a >= 0 and b >= 0:
            rank[i] = round(layers * a / max(1, a + b))
        elif a >= 0:
            rank[i] = min(layers - 1, a)
        elif b >= 0:
            rank[i] = max(1, layers - b)
        else:
            rank[i] = 1 + i % (layers - 1)
    rank = np.clip(rank, 1, layers - 1)
    rank[left], rank[right] = 0, layers
    columns = [np.flatnonzero(rank == i).tolist() for i in range(layers + 1)]
    columns[0], columns[-1] = left, right
    # Barycentric sweeps reduce crossings before the spring relaxation.
    order = np.zeros(count)
    for _ in range(6):
        for column in columns:
            for j, i in enumerate(column):
                order[i] = (j + 0.5) / max(1, len(column))
        for layer in range(1, layers):
            columns[layer].sort(
                key=lambda i: (
                    float(np.mean([order[j] for j in incoming[i] + outgoing[i]]))
                    if incoming[i] or outgoing[i]
                    else order[i],
                    elements[i]["id"],
                )
            )
    width = max(900.0, math.sqrt(count) * 180)
    height = max(600.0, max(map(len, columns)) * 95.0)
    positions = np.zeros((count, 2), dtype=float)
    for layer, column in enumerate(columns):
        for j, i in enumerate(column):
            positions[i] = (layer / layers * width, (j + 0.5) / len(column) * height)
    targets = positions.copy()
    pairs = sorted(edges)
    sources = np.array([a for a, _ in pairs], dtype=int)
    dests = np.array([b for _, b in pairs], dtype=int)
    weights = np.array([edges[p] for p in pairs])
    degree = np.maximum(1, np.bincount(np.concatenate((sources, dests)), minlength=count))
    # Exact repulsion for small graphs; deterministic sampled repulsion for large
    # ones. Chunks bound temporary memory rather than allocating an N x N matrix.
    sample_count = count if count <= 512 else 64
    samples = np.linspace(0, count - 1, sample_count, dtype=int)
    for iteration in range(64):
        force = np.zeros_like(positions)
        for start in range(0, count, 256):
            delta = positions[start : start + 256, None, :] - positions[samples][None, :, :]
            squared = np.maximum(25.0, np.sum(delta * delta, axis=2))
            force[start : start + 256] = (
                np.sum(delta * (140**2 / squared)[:, :, None], axis=1) * count / sample_count
            )
        if pairs:
            delta = positions[dests] - positions[sources]
            distance = np.maximum(1.0, np.linalg.norm(delta, axis=1))
            spring = delta * (weights * distance / 140)[:, None]
            np.add.at(force, sources, spring / np.sqrt(degree[sources])[:, None])
            np.add.at(force, dests, -spring / np.sqrt(degree[dests])[:, None])
        force += (targets - positions) * 0.4
        length = np.maximum(1.0, np.linalg.norm(force, axis=1))
        temperature = 45 * (1 - iteration / 64) + 1
        positions += force * np.minimum(temperature / length, 1)[:, None]
        positions[:, 0] = np.clip(positions[:, 0], 140, width - 140)
        positions[fixed] = targets[fixed]
    # Resolve node/label collisions with a spatial grid. Ports stay fixed.
    occupied = defaultdict(list)

    def cell(x, y):
        return math.floor(x / 130), math.floor(y / 80)

    for i in left + right:
        occupied[cell(*positions[i])].append(i)
    free = sorted(
        (i for i in range(len(neurons)) if not fixed[i]),
        key=lambda i: (positions[i, 1], positions[i, 0], i),
    )
    for i in free:
        x, y = positions[i]
        while True:
            cx, cy = cell(x, y)
            neighbors = (
                j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in occupied[cx + dx, cy + dy]
            )
            if not any(
                abs(x - positions[j, 0]) < 130 and abs(y - positions[j, 1]) < 80 for j in neighbors
            ):
                break
            y += 80
        positions[i, 1] = y
        occupied[cell(x, y)].append(i)
    # Leave enough room for group outlines and frames within the document bounds.
    low, high = positions.min(axis=0), positions.max(axis=0)
    positions -= (low + high) / 2
    positions *= min(1.0, 60000 / max(1.0, float(np.max(high - low))))
    for i, neuron in enumerate(neurons):
        neuron.update(x=round(float(positions[i, 0]), 3), y=round(float(positions[i, 1]), 3))
    for group in ganglia:
        points = positions[[index[nid] for nid in group["members"]]]
        center = (points.min(axis=0) + points.max(axis=0)) / 2
        group.update(
            x=float(center[0]),
            y=float(center[1]),
            radius=max(40.0, float(np.linalg.norm(points - center, axis=1).max()) + 45),
        )
    old = {n["id"]: n for n in topology["neurons"]}
    for frame in net["groups"]:
        members = [
            n
            for n in neurons
            if frame["x"] <= old[n["id"]]["x"] <= frame["x"] + frame["w"]
            and frame["y"] <= old[n["id"]]["y"] <= frame["y"] + frame["h"]
        ]
        if members:
            x0, x1 = min(n["x"] for n in members) - 45, max(n["x"] for n in members) + 45
            y0, y1 = min(n["y"] for n in members) - 65, max(n["y"] for n in members) + 45
            frame.update(x=x0, y=y0, w=x1 - x0, h=y1 - y0)
    return schema.topology(net)
