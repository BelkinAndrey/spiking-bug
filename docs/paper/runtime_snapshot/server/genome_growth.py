"""Seeded mutation proposals biased toward vacant coordinates and unused endpoints.

This changes the proposal distribution, never fitness or decoding of saved genomes.
All connectivity measurements come from the developed, effective graph.
"""

import math
from collections import Counter
from . import schema
from .development import expand_synapse


def vacant_coordinate(space, rng):
    """Best of 32 uniform samples by distance to the nearest occupied coordinate."""
    candidates = [[rng.random() for _ in range(3)] for _ in range(32)]
    if not space:
        return candidates[0]
    return max(candidates, key=lambda p: min(math.dist(p, n["rgb"]) for n in space))


def reachable(starts, edges):
    seen = set(starts)
    todo = list(starts)
    while todo:
        for other in edges.get(todo.pop(), ()):
            if other not in seen:
                seen.add(other)
                todo.append(other)
    return seen


class Coverage:
    def __init__(self, g, net, space, options, stop=None):
        self.space = space
        self.nodes = {n["id"]: n for n in net["neurons"]}
        groups = {c["id"]: c["members"] for c in net["ganglia"]}
        self.members = {n["id"]: groups.get(n["id"], [n["id"]]) for n in space}
        owners = {member: nid for nid, members in self.members.items() for member in members}
        self.incoming = {n["id"]: set() for n in space}
        self.outgoing = {n["id"]: set() for n in space}
        forward, backward = {}, {}
        self.pairs = set()
        direct = options["direct_exc"] or options["direct_inh"]
        checked = 0
        for edge in net["synapses"]:
            for a, b, weight in expand_synapse(edge, self.nodes, groups):
                if stop is not None and checked % 256 == 0 and stop.is_set():
                    raise InterruptedError("Развитие остановлено")
                checked += 1
                if a == b or weight == 0:
                    continue
                source, target = owners.get(a), owners.get(b)
                if source is not None and target is not None and source != target:
                    self.pairs.add((source, target, edge["kind"]))
                    if not direct or edge["kind"] == "direct":
                        self.outgoing[source].add(target)
                        self.incoming[target].add(source)
                if not direct or edge["kind"] == "direct":
                    forward.setdefault(a, set()).add(b)
                    backward.setdefault(b, set()).add(a)
        sensors = {g["bindings"].get(key) for key in schema.SENSORS} - {None}
        motors = {g["bindings"].get(key) for key in schema.MOTORS} - {None}
        self.sensors = {nid for nid, ms in self.members.items() if set(ms) & sensors}
        self.motors = {nid for nid, ms in self.members.items() if set(ms) & motors}
        from_sensors = reachable(sensors, forward)
        to_motors = reachable(motors, backward)
        self.from_sensors = {nid for nid, ms in self.members.items() if set(ms) & from_sensors}
        self.to_motors = {nid for nid, ms in self.members.items() if set(ms) & to_motors}
        self.regions = {}
        for side, degrees in (("source", self.outgoing), ("target", self.incoming)):
            cells = Counter()
            for n in space:
                cells[self.cell(n)] += len(degrees[n["id"]])
            self.regions[side] = cells

    @staticmethod
    def cell(n):
        return tuple(min(3, int(v * 4)) for v in n["rgb"])

    def weight(self, n, side):
        nid = n["id"]
        degrees = self.outgoing if side == "source" else self.incoming
        degree = len(degrees[nid])
        isolated = not self.outgoing[nid] and not self.incoming[nid]
        weight = (1 + 8 * (degree == 0) + 16 * isolated) / (1 + degree)
        weight /= 1 + self.regions[side][self.cell(n)]
        # Sensors primarily need outputs; motors primarily need inputs.
        if nid in (self.motors if side == "source" else self.sensors):
            weight *= 0.05
        return weight

    def source_allowed(self, n, options, kind):
        if kind != "direct":
            return True
        return any(
            self.nodes[nid]["polarity"] == "mixed"
            or options["direct_" + self.nodes[nid]["polarity"]]
            for nid in self.members[n["id"]]
        )

    def choose_pair(self, rng, options, kind, anchor=None, side=None):
        sources = [n for n in self.space if self.source_allowed(n, options, kind)]
        if side == "source":
            sources = [n for n in sources if n["id"] == anchor]
        elif side == "target":
            sources = [n for n in sources if n["id"] != anchor]
            connected = [n for n in sources if n["id"] in self.from_sensors]
            sources = connected or sources
        for _ in range(min(8, len(sources))):
            weights = [self.weight(n, "source") for n in sources]
            a = rng.choices(sources, weights=weights)[0]
            targets = [
                n
                for n in self.space
                if n["id"] != a["id"]
                and (a["id"], n["id"], kind) not in self.pairs
                and (side != "target" or n["id"] == anchor)
            ]
            if targets:
                if side == "source":
                    connected = [n for n in targets if n["id"] in self.to_motors]
                    targets = connected or targets
                weights = [self.weight(n, "target") for n in targets]
                return a, rng.choices(targets, weights=weights)[0]
            sources.remove(a)
        return None


def fill_connections(
    g, project, options, rng, identity, anchors=(), requests=(), stop=None, max_additions=None
):
    from .genome import decode, kinds, new_rule, nodespace

    net = decode(g, project, options, stop)
    added = 0

    def add(block, anchor=None, side=None):
        nonlocal net, added
        if len(g["B"]) + len(g["D"]) >= options["max_rules"]:
            return
        if max_additions is not None and added >= max_additions:
            return
        space = nodespace(g) if block == "B" else g["C"]
        coverage = Coverage(g, net, space, options, stop)
        # A modulatory-only link does not carry ordinary spikes into an unused neuron.
        kind = (
            "direct"
            if anchor is not None and (options["direct_exc"] or options["direct_inh"])
            else rng.choice(kinds(options))
        )
        pair = coverage.choose_pair(rng, options, kind, anchor, side)
        if pair is None:
            return
        a, b = pair
        rule = new_rule(identity(block), space, rng, options, a, b)
        rule["kind"] = kind
        for end, node in (("source", a), ("target", b)):
            # A sparse rule selects its anchor, avoiding an accidental fan-out into a cluster.
            nearest = min(
                (math.dist(node["rgb"], n["rgb"]) for n in space if n["id"] != node["id"]),
                default=0.24,
            )
            rule[end + "_radius"] = min(0.12, nearest / 2)
        g[block].append(rule)
        try:
            developed = decode(g, project, options, stop)
        except ValueError:
            # Optional growth must not discard a valid child when an expanded budget is full.
            g[block].pop()
            return
        updated = Coverage(g, developed, space, options, stop)
        if not updated.pairs.difference(coverage.pairs):
            g[block].pop()
            return
        net = developed
        added += 1

    space = nodespace(g)
    coverage = Coverage(g, net, space, options, stop)
    if not anchors:
        unused = [
            n
            for n in space
            if (n["id"] not in coverage.sensors and n["id"] not in coverage.from_sensors)
            or (n["id"] not in coverage.motors and n["id"] not in coverage.to_motors)
        ]
        if unused:
            anchors = [
                rng.choices(
                    unused,
                    weights=[
                        coverage.weight(n, "source") + coverage.weight(n, "target") for n in unused
                    ],
                )[0]["id"]
            ]
    for anchor in anchors:
        for side in ("target", "source"):
            coverage = Coverage(g, net, nodespace(g), options, stop)
            if anchor not in coverage.members:
                continue
            if side == "target":
                needed = anchor not in coverage.sensors and anchor not in coverage.from_sensors
            else:
                needed = anchor not in coverage.motors and anchor not in coverage.to_motors
            if needed:
                add("B", anchor, side)
    for block in requests:
        add(block)
    return g
