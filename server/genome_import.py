"""Lossless explicit genes for starting evolution from an edited phenotype.

Imported links retain self edges, parallel edges and explicit access to ganglion
members. Newly generated sphere rules still only see external endpoints.
"""

import copy
from . import schema
from .development import seed, expand_synapse, edge_count


def is_link(record):
    return record.get("type") == "synapse"


def from_project(project):
    from .genome import VERSION, DECODER, frozen

    net = schema.topology(project["topology"])
    genes = dict(
        version=VERSION,
        decoder=DECODER,
        A=copy.deepcopy(net["neurons"]),
        B=[],
        C=copy.deepcopy(net["ganglia"]),
        D=[],
        frozen=sorted(frozen(project)),
        bindings=copy.deepcopy(project["bindings"]),
        order={
            key: [item["id"] for item in net[key]] for key in ("neurons", "synapses", "ganglia")
        },
        frames=copy.deepcopy(net["groups"]),
    )
    used = {n["id"] for n in genes["A"] + genes["C"]}
    for edge in net["synapses"]:
        salt = 0
        while True:
            identity = f"link_{seed(edge['id'], salt):016x}"
            if identity not in used:
                break
            salt += 1
        used.add(identity)
        genes["B"].append(dict(id=identity, type="synapse", synapse=copy.deepcopy(edge)))
    return genes


def prune_explicit(g):
    nodes = {n["id"] for n in g["A"]}
    for c in g["C"]:
        if "members" in c:
            c["members"] = [nid for nid in c["members"] if nid in nodes]
    g["C"] = [c for c in g["C"] if "members" not in c or c["members"]]
    endpoints = nodes | {c["id"] for c in g["C"]}
    g["B"] = [
        r
        for r in g["B"]
        if not is_link(r)
        or (r["synapse"]["source"] in endpoints and r["synapse"]["target"] in endpoints)
    ]


def ordered(items, order):
    priority = {identity: i for i, identity in enumerate(order)}
    return sorted(items, key=lambda item: (priority.get(item["id"], len(priority)), item["id"]))


def explicit_topology(g):
    order = g.get("order", {})
    return dict(
        format_version=3,
        neurons=ordered(g["A"], order.get("neurons", [])),
        ganglia=ordered([c for c in g["C"] if "members" in c], order.get("ganglia", [])),
        synapses=ordered([r["synapse"] for r in g["B"] if is_link(r)], order.get("synapses", [])),
        groups=g.get("frames", []),
    )


def validate(g, options):
    """Validate explicit memberships, edges, signs and real expanded budgets."""
    if (
        g.get("order")
        or g.get("frames")
        or any(is_link(r) for r in g["B"])
        or any("members" in c for c in g["C"])
    ) and g["version"] < 2:
        raise ValueError("Явная архитектура требует геном версии 2")
    if not isinstance(g.get("order", {}), dict):
        raise ValueError("Некорректный порядок элементов генома")
    for key, values in g.get("order", {}).items():
        if key not in ("neurons", "synapses", "ganglia") or not isinstance(values, list):
            raise ValueError("Некорректный порядок элементов генома")
        for value in values:
            schema.identifier(value)
        if len(set(values)) != len(values):
            raise ValueError("Некорректный порядок элементов генома")
    # Explicit links can only reference concrete A neurons or explicit C groups;
    # mutations never introduce addressed links into generated recipe internals.
    net = schema.topology(explicit_topology(g))
    if edge_count(net) > options["max_synapses"]:
        raise ValueError("Бюджет развёрнутых синапсов")
    nodes = {n["id"]: n for n in net["neurons"]}
    groups = {c["id"]: c["members"] for c in net["ganglia"]}
    from .genome import kinds

    for s in net["synapses"]:
        if s["kind"] not in kinds(options):
            raise ValueError("Текущая сеть содержит запрещённый тип связи")
        if s["kind"] == "direct":
            for _, _, w in expand_synapse(s, nodes, groups):
                if (w < 0 and not options["direct_inh"]) or (w > 0 and not options["direct_exc"]):
                    raise ValueError("Текущая сеть содержит запрещённый знак прямой связи")
    return net


def delete_group(g, c):
    if "members" in c:
        removed = set(c["members"]) - set(g["frozen"])
        g["A"] = [n for n in g["A"] if n["id"] not in removed]


def repair_polarities(g):
    """Mutated polarity must agree with addressed direct edges; import never repairs."""
    nodes = {n["id"]: n for n in g["A"]}
    for r in g["B"]:
        if not is_link(r):
            continue
        s = r["synapse"]
        node = nodes.get(s["source"])
        if node and s["kind"] == "direct" and node["polarity"] != "mixed":
            s["weight"] = abs(s["weight"]) * (1 if node["polarity"] == "exc" else -1)


def mutate_link(r, g, rng, options, perturb):
    from .genome import kinds, nodespace

    s = r["synapse"]
    key = rng.choice(["weight", "delay", "kind", "source", "target"])
    if key == "weight":
        s[key] = perturb(s[key], -10000, 10000, 2)
    elif key == "delay":
        s[key] = round(perturb(s[key], 1, 256, 10))
    elif key == "kind":
        s[key] = rng.choice(kinds(options))
    else:
        # Rewiring preserves the scope: member endpoints stay in their own group.
        group = next((c for c in g["C"] if s[key] in c.get("members", [])), None)
        candidates = group["members"] if group else [n["id"] for n in nodespace(g)]
        if candidates:
            s[key] = rng.choice(candidates)
    if s["kind"] == "direct" and not (options["direct_exc"] and options["direct_inh"]):
        s["weight"] = abs(s["weight"]) * (1 if options["direct_exc"] else -1)


def mutate_group(c, g, rng, options, identity, perturb, neuron_change, guided=False):
    from .genome import kinds
    from .development import coordinate
    from .genome_growth import vacant_coordinate

    key = rng.choice(["count", "neuron", "rgb", "connector_rgb", "radius", "connections"])
    nodes = {n["id"]: n for n in g["A"]}
    members = [nid for nid in c["members"] if nid in nodes]
    mutable = [nid for nid in members if nid not in g["frozen"]]

    def connect(a, b):
        kind = rng.choice(kinds(options))
        w = rng.uniform(0.2, 1)
        if kind == "direct":
            pol = nodes[a]["polarity"]
            if pol == "inh" or (pol == "mixed" and not options["direct_exc"]):
                w = -w
        rid = identity("B")
        g["B"].append(
            dict(
                id=rid,
                type="synapse",
                synapse=dict(id=rid, source=a, target=b, kind=kind, weight=w, delay=2),
            )
        )

    if key in ("rgb", "connector_rgb"):
        if guided:
            from .genome import nodespace

            space = g["C"] if key == "rgb" else nodespace(g)
            c[key] = vacant_coordinate([n for n in space if n["id"] != c["id"]], rng)
        else:
            c[key] = [perturb(v, 0, 1) for v in c[key]]
    elif key == "radius":
        c[key] = perturb(c[key], 30, schema.MAX_GANGLION_RADIUS, 100)
    elif key == "neuron" and mutable:
        neuron_change(nodes[rng.choice(mutable)])
    elif key == "count" and members:
        if mutable and rng.random() < 0.5:
            nid = rng.choice(mutable)
            g["A"] = [n for n in g["A"] if n["id"] != nid]
            c["members"].remove(nid)
        else:
            n = copy.deepcopy(nodes[rng.choice(members)])
            n.update(id=identity("A"))
            n["rgb"] = (
                vacant_coordinate([nodes[nid] for nid in members], rng)
                if guided
                else coordinate(n["id"])
            )
            g["A"].append(n)
            c["members"].append(n["id"])
            nodes[n["id"]] = n
            # A new internal neuron is immediately reachable within its group.
            connect(rng.choice(members), n["id"])
            connect(n["id"], rng.choice(members))
    elif key == "connections" and len(members) > 1:
        a, b = rng.sample(members, 2)
        matches = [
            r
            for r in g["B"]
            if is_link(r) and r["synapse"]["source"] == a and r["synapse"]["target"] == b
        ]
        if matches:
            g["B"].remove(rng.choice(matches))
        else:
            connect(a, b)
