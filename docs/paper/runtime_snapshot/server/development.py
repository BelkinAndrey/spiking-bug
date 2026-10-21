"""Document-only developmental coordinates and connector expansion (no tick work)."""

import hashlib
from . import schema


def seed(*parts):
    return int.from_bytes(hashlib.sha256(repr(parts).encode()).digest()[:8], "big")


def boundary_coordinate(index):
    # Round-robin faces + low-discrepancy in-face coordinates, channel-order stable.
    xyz = [((index + 1) * 0.6180339887498949) % 1, ((index + 1) * 0.4142135623730951) % 1, 0.5]
    face = index % 6
    free = [xyz[0], xyz[1]]
    return [float(face % 2) if axis == face // 2 else free.pop(0) for axis in range(3)]


def coordinate(identity, salt=0, boundary=False):
    if boundary and salt == 0:
        standard_ids = list(schema.default_bindings().values())
        if identity in standard_ids:
            return boundary_coordinate(standard_ids.index(identity))
    raw = hashlib.sha256(f"rgb-v1:{identity}:{salt}".encode()).digest()
    xyz = [int.from_bytes(raw[i : i + 4], "big") / 4294967295 for i in (0, 4, 8)]
    if boundary:
        face = raw[12] % 6
        xyz[face // 2] = float(face % 2)
    return xyz


def rgb(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("RGB: ожидаются три координаты")
    return [schema.number(v, "RGB", 0, 1) for v in value]


def unique_coordinates(records, key="rgb", boundary=False):
    """Sorted IDs own collisions; rehash only losers, preserving JSON float values."""
    used = set()
    # Explicit coordinates take precedence over legacy defaults.
    ordered = sorted(records, key=lambda n: (key not in n, n["id"]))
    for item in ordered:
        value = rgb(item[key]) if key in item else coordinate(item["id"], boundary=boundary)
        salt = 0
        while tuple(value) in used:
            salt += 1
            value = coordinate(item["id"], salt, boundary)
        item[key] = value
        used.add(tuple(value))


def assign_coordinates(neurons, ganglia):
    unique_coordinates(ganglia)
    # All concrete neurons and connectors share a unique coordinate namespace.
    # Internal members are excluded from block B despite their document coordinates.
    connectors = [
        {"id": g["id"], **({"rgb": g["connector_rgb"]} if "connector_rgb" in g else {})}
        for g in ganglia
    ]
    unique_coordinates([*neurons, *connectors], boundary=True)
    for g, c in zip(ganglia, connectors):
        g["connector_rgb"] = c["rgb"]


def expand_synapse(s, nodes, groups):
    """Broadcast each member's spike. No averaging, extra state, or extra delay."""
    for source in groups.get(s["source"], [s["source"]]):
        weight = s["weight"]
        if s["source"] in groups and s["kind"] == "direct":
            polarity = nodes[source]["polarity"]
            if polarity != "mixed":
                weight = abs(weight) * (1 if polarity == "exc" else -1)
        for target in groups.get(s["target"], [s["target"]]):
            yield source, target, weight


def edge_count(net):
    sizes = {g["id"]: len(g["members"]) for g in net["ganglia"]}
    return sum(sizes.get(s["source"], 1) * sizes.get(s["target"], 1) for s in net["synapses"])
