"""Four-block, variable-length genome. Pure deterministic development and mutation."""

from __future__ import annotations
import copy
import math
import random
from . import schema, generators, genome_import
from .development import coordinate, unique_coordinates, rgb, seed, expand_synapse, edge_count

VERSION = 2
DECODER = 2
PARAMETERS = {
    "threshold": (-10, 20, 1),
    "leak": (0, 1, 0.1),
    "bias": (-10, 10, 0.2),
    "refractory": (0, 100, 5),
    "noise_std": (0, 5, 0.1),
    "v_min": (-10000, 0, 10),
    "v_reset": (-10000, 10000, 1),
    "mod_tau_exc": (0.01, 3600, 1),
    "mod_tau_inh": (0.01, 3600, 1),
    "mod_gain_exc": (0, 100, 1),
    "mod_gain_inh": (0, 100, 1),
}


def settings(data):
    if not isinstance(data, dict):
        raise ValueError("settings: ожидается объект")
    ranges = {
        "population": (12, 2, 128, True),
        "generations": (20, 1, 10000, True),
        "elite": (2, 1, 127, True),
        "tournament": (3, 1, 128, True),
        "attempts": (3, 1, 100, True),
        "validation_attempts": (5, 1, 100, True),
        "duration": (30, 1, 3600, True),
        "seed": (42, 0, 2147483647, True),
        "search_seed": (1000, 0, 2147483547, True),
        "validation_seed": (100000, 0, 2147483547, True),
        "max_neurons": (256, 1, 100000, True),
        "max_ganglia": (8, 0, 128, True),
        "max_rules": (64, 1, 4096, True),
        "max_synapses": (10000, 0, schema.MAX_SYNAPSES, True),
        "max_pair_checks": (2000000, 1, 10000000, True),
        "memory_mb": (256, 16, 4096, True),
        "wall_seconds": (3600, 1, 86400, True),
        "workers": (1, 1, 1, True),
        "archive_size": (12, 1, 100, True),
        "add_rate": (0.35, 0, 1, False),
        "delete_rate": (0.15, 0, 1, False),
        "change_rate": (0.7, 0, 1, False),
        "scale": (0.2, 0.001, 5, False),
    }
    out = {k: schema.number(data.get(k, v[0]), k, *v[1:]) for k, v in ranges.items()}
    if out["elite"] >= out["population"]:
        raise ValueError("elite должен быть меньше population")
    if set(range(out["search_seed"], out["search_seed"] + out["attempts"])) & set(
        range(out["validation_seed"], out["validation_seed"] + out["validation_attempts"])
    ):
        raise ValueError("Поисковые и проверочные seed должны различаться")
    for key, default in {
        "randomize": True,
        "direct_exc": True,
        "direct_inh": True,
        "mod_exc": True,
        "mod_inh": True,
    }.items():
        if not isinstance(data.get(key, default), bool):
            raise ValueError(f"{key}: expected boolean")
        out[key] = data.get(key, default)
    out["preset"] = data.get("preset", "ganglia")
    if out["preset"] not in ("direct", "modulation", "ganglia"):
        raise ValueError("Неизвестный пресет")
    if out["preset"] == "direct":
        out["mod_exc"] = out["mod_inh"] = False
    out["mode"] = data.get("mode", "fresh")
    if out["mode"] not in ("fresh", "current", "continue"):
        raise ValueError("Неизвестный режим запуска")
    if not kinds(out):
        raise ValueError("Выберите хотя бы один тип связей")
    weights = data.get("fitness", {})
    if not isinstance(weights, dict):
        raise ValueError("fitness: ожидается объект")
    out["fitness"] = {
        "neuron_penalty": schema.number(
            weights.get("neuron_penalty", 0.01), "neuron_penalty", 0, 10000
        )
    }
    return out


def kinds(options):
    return (["direct"] if options["direct_exc"] or options["direct_inh"] else []) + [
        k for k in ("mod_exc", "mod_inh") if options[k]
    ]


def frozen(project):
    ids = {v for k, v in project["bindings"].items() if k in schema.SENSORS + schema.MOTORS and v}
    return {n["id"]: copy.deepcopy(n) for n in project["topology"]["neurons"] if n["id"] in ids}


def nodespace(g):
    internal = {nid for c in g["C"] for nid in c.get("members", [])}
    return [n for n in g["A"] if n["id"] not in internal] + [
        {"id": c["id"], "rgb": c["connector_rgb"]} for c in g["C"]
    ]


def selected(rule, elements, side):
    center = rule[side + "_rgb"]
    radius = rule[side + "_radius"]
    return [n for n in elements if math.dist(center, n["rgb"]) <= radius]


def prune(g):
    genome_import.prune_explicit(g)
    for block, elements in (("B", nodespace(g)), ("D", g["C"])):
        g[block] = [
            r
            for r in g[block]
            if genome_import.is_link(r)
            or (selected(r, elements, "source") and selected(r, elements, "target"))
        ]
    return g


def normalize(g, project, options):
    if not isinstance(g, dict) or (g.get("version"), g.get("decoder")) not in (
        (1, 1),
        (VERSION, DECODER),
    ):
        raise ValueError("Неизвестная версия генома / декодера")
    g = copy.deepcopy(g)
    ids = set()
    for block in "ABCD":
        limit = (
            options["max_neurons"]
            if block == "A"
            else options["max_ganglia"]
            if block == "C"
            else options["max_rules"]
        )
        if not isinstance(g.get(block), list) or len(g[block]) > limit:
            raise ValueError(f"Бюджет блока {block}")
        for item in g[block]:
            key = schema.identifier(item["id"])
            id_limit = (
                80
                if g["version"] >= 2 and (block == "A" or (block == "C" and "members" in item))
                else 48
            )
            if len(key) > id_limit or key in ids:
                raise ValueError("ID генома: повтор или превышение допустимой длины")
            ids.add(key)
        g[block].sort(key=lambda item: item["id"])
    if len(g["B"]) + len(g["D"]) > options["max_rules"]:
        raise ValueError("Бюджет правил")
    if options["preset"] != "ganglia" and (g["C"] or g["D"]):
        raise ValueError("Пресет запрещает ганглии")
    g["A"] = [schema.neuron(n) for n in g["A"]]
    fixed = frozen(project)
    by_id = {n["id"]: n for n in g["A"]}
    for nid, n in fixed.items():
        if nid not in by_id or any(
            by_id[nid].get(k) != v for k, v in n.items() if k not in ("x", "y")
        ):
            raise ValueError("Изменён замороженный нейрон " + nid)
        by_id[nid].update(n)
    if g.get("bindings") != project["bindings"] or g.get("frozen") != sorted(fixed):
        raise ValueError("Изменены замороженные bindings")
    total = len(g["A"])
    for c in g["C"]:
        c["rgb"] = rgb(c["rgb"])
        c["connector_rgb"] = rgb(c["connector_rgb"])
        if "members" in c:
            if "recipe" in c:
                raise ValueError("Ганглий не может одновременно содержать members и recipe")
            continue
        p = c["recipe"]
        p["count"] = schema.number(
            p["count"], "count", 1, min(schema.MAX_GANGLION_NEURONS, options["max_neurons"]), True
        )
        total += p["count"]
        # Decode validates the rest using the existing generator.
        p["kind"] = p.get("kind", "direct")
        if p["kind"] not in kinds(options):
            raise ValueError("Запрещённый тип внутренних связей")
        if p["kind"] == "direct":
            if not options["direct_inh"] and p.get("excitatory", 0.8) != 1:
                raise ValueError("Внутренние тормозящие связи запрещены")
            if not options["direct_exc"] and p.get("excitatory", 0.8) != 0:
                raise ValueError("Внутренние возбуждающие связи запрещены")
    if total > options["max_neurons"]:
        raise ValueError("Бюджет нейронов")
    unique_coordinates(g["C"])
    connectors = [{"id": c["id"], "rgb": c["connector_rgb"]} for c in g["C"]]
    # Reserve frozen coordinates, resolve mutable collisions without touching frozen ones.
    used = {tuple(n["rgb"]) for n in fixed.values()}
    for n in sorted(
        [n for n in g["A"] if n["id"] not in fixed] + connectors, key=lambda n: n["id"]
    ):
        value = rgb(n.get("rgb", coordinate(n["id"])))
        salt = 0
        while tuple(value) in used:
            salt += 1
            value = coordinate(n["id"], salt)
        n["rgb"] = value
        used.add(tuple(value))
    for c, n in zip(g["C"], connectors):
        c["connector_rgb"] = n["rgb"]
    if any(genome_import.is_link(r) for r in g["D"]):
        raise ValueError("Явные синапсы допустимы только в блоке B")
    explicit = genome_import.validate(g, options)
    canonical_edges = {s["id"]: s for s in explicit["synapses"]}
    for r in g["B"]:
        if genome_import.is_link(r):
            r["synapse"] = canonical_edges[r["synapse"]["id"]]
    for r in g["B"] + g["D"]:
        if genome_import.is_link(r):
            continue
        for side in ("source", "target"):
            r[side + "_rgb"] = rgb(r[side + "_rgb"])
            r[side + "_radius"] = schema.number(r[side + "_radius"], "radius", 0, math.sqrt(3))
            if r.get(side + "_polarity", "any") not in ("any", "exc", "inh"):
                raise ValueError("Неизвестный фильтр полярности")
            r.setdefault(side + "_polarity", "any")
        for key, lo, hi, integer in (
            ("density", 0, 1, False),
            ("weight", -100, 100, False),
            ("weight_std", 0, 100, False),
            ("delay", 1, 256, True),
            ("delay_max", 1, 256, True),
            ("seed", 0, 2147483647, True),
        ):
            r[key] = schema.number(
                r.get(key, r.get("delay", 1) if key == "delay_max" else 0), key, lo, hi, integer
            )
        if r["delay_max"] < r["delay"] or r["kind"] not in kinds(options):
            raise ValueError("Недопустимый тип связи / задержка")
        if r["kind"] == "direct" and (
            (r["weight"] < 0 and not options["direct_inh"])
            or (r["weight"] >= 0 and not options["direct_exc"])
        ):
            raise ValueError("Знак прямой связи запрещён")
    return prune(g)


def decode(genome, project, options, stop=None):
    if stop is not None and stop.is_set():
        raise InterruptedError("Развитие остановлено")
    g = normalize(genome, project, options)
    total = len(g["A"]) + sum(c["recipe"]["count"] for c in g["C"] if "recipe" in c)
    maximum_delay = max(
        [1]
        + [
            r["synapse"]["delay"] if genome_import.is_link(r) else r["delay_max"]
            for r in g["B"] + g["D"]
        ]
        + [c["recipe"].get("delay", 2) for c in g["C"] if "recipe" in c]
    )
    if (
        total * (4096 + (maximum_delay + 1) * 16) * (options["population"] + 4)
        > options["memory_mb"] * 1048576
    ):
        raise ValueError("Бюджет памяти популяции")
    memory_edges = int(
        (
            options["memory_mb"] * 1048576 / (options["population"] + 4)
            - total * (4096 + (maximum_delay + 1) * 16)
        )
        / 2048
    )
    edge_limit = min(options["max_synapses"], max(0, memory_edges))
    net = schema.topology(genome_import.explicit_topology(g))
    expanded = edge_count(net)
    if expanded > edge_limit:
        raise ValueError("Бюджет развёрнутых синапсов")
    # Internal geometry is canonical and never depends on editor positions.
    for c in g["C"]:
        if "members" in c:
            continue
        p = {
            **c["recipe"],
            "id": c["id"],
            "x": 0,
            "y": 0,
            "edge_limit": edge_limit - expanded + len(net["synapses"]),
        }
        net = generators.ganglion(net, p, stop)
        group = net["ganglia"][-1]
        group.update(rgb=c["rgb"], connector_rgb=c["connector_rgb"])
        member_ids = set(group["members"])
        for s in net["synapses"]:
            if s["source"] in member_ids and s["target"] in member_ids:
                s["kind"] = p.get("kind", "direct")
        expanded = edge_count(net)
        if expanded > edge_limit:
            raise ValueError("Бюджет развёрнутых синапсов")
    nodes = {n["id"]: n for n in net["neurons"]}
    groups = {c["id"]: c["members"] for c in net["ganglia"]}
    pairs = {(s["source"], s["target"], s["kind"]) for s in net["synapses"]}
    # An inherited connector edge also reserves all of its effective pairs.
    for s in net["synapses"]:
        if s["source"] in groups or s["target"] in groups:
            pairs.update((a, b, s["kind"]) for a, b, _ in expand_synapse(s, nodes, groups))
    checks = 0

    def add(s, r):
        nonlocal checks, expanded
        checks += len(groups.get(s["source"], [s["source"]])) * len(
            groups.get(s["target"], [s["target"]])
        )
        if checks > options["max_pair_checks"]:
            raise ValueError("Бюджет проверки пар")
        for i, (a, b, w) in enumerate(expand_synapse(s, nodes, groups)):
            if stop is not None and i % 256 == 0 and stop.is_set():
                raise InterruptedError("Развитие остановлено")
            if a == b:  # All developmental self edges are excluded.
                continue
            if r["source_polarity"] != "any" and nodes[a]["polarity"] != r["source_polarity"]:
                continue
            if r["target_polarity"] != "any" and nodes[b]["polarity"] != r["target_polarity"]:
                continue
            if s["kind"] == "direct":
                pol = nodes[a]["polarity"]
                if pol != "mixed":
                    w = abs(w) * (1 if pol == "exc" else -1)
                if (w < 0 and not options["direct_inh"]) or (w >= 0 and not options["direct_exc"]):
                    continue
            pair = (a, b, s["kind"])
            if pair in pairs:
                continue
            pairs.add(pair)
            net["synapses"].append(
                {**s, "id": f"e{seed(r['id'], a, b):016x}", "source": a, "target": b, "weight": w}
            )
            expanded += 1
            if expanded > edge_limit:
                raise ValueError("Бюджет развёрнутых синапсов")

    for block, space in (("B", nodespace(g)), ("D", g["C"])):
        for r in g[block]:
            if genome_import.is_link(r):
                continue
            sources, targets = selected(r, space, "source"), selected(r, space, "target")
            checks += len(sources) * len(targets)
            if checks > options["max_pair_checks"]:
                raise ValueError("Бюджет проверки пар")
            for a in sources:
                if stop is not None and stop.is_set():
                    raise InterruptedError("Развитие остановлено")
                for b in targets:
                    if stop is not None and stop.is_set():
                        raise InterruptedError("Развитие остановлено")
                    if a["id"] == b["id"]:
                        continue
                    rng = random.Random(seed("development", r["seed"], r["id"], a["id"], b["id"]))
                    if block == "B":
                        if rng.random() >= r["density"]:
                            continue
                        w = rng.gauss(r["weight"], r["weight_std"])
                        if r["kind"] == "direct" and not (
                            options["direct_exc"] and options["direct_inh"]
                        ):
                            w = abs(w) * (1 if options["direct_exc"] else -1)
                        add(
                            dict(
                                source=a["id"],
                                target=b["id"],
                                kind=r["kind"],
                                weight=w,
                                delay=rng.randint(r["delay"], r["delay_max"]),
                            ),
                            r,
                        )
                    else:
                        # Reuse existing sparse projection generator; canonical geometry only.
                        base = {**net, "synapses": []}
                        projection = generators.connect_ganglia(
                            base,
                            {
                                **r,
                                "source": a["id"],
                                "target": b["id"],
                                "max_distance": 0,
                                "seed": seed(r["seed"], a["id"], b["id"]) % 2147483648,
                                "edge_limit": edge_limit,
                            },
                            stop,
                        )
                        for s in projection["synapses"]:
                            local = random.Random(seed(r["seed"], s["source"], s["target"]))
                            w = local.gauss(s["weight"], r["weight_std"])
                            if r["kind"] == "direct" and not (
                                options["direct_exc"] and options["direct_inh"]
                            ):
                                w = abs(w) * (1 if options["direct_exc"] else -1)
                            s.update(weight=w, delay=local.randint(r["delay"], r["delay_max"]))
                            add(s, r)
    # Reserve external coordinates; internal coordinates never displace frozen endpoints.
    external = {tuple(n["rgb"]) for n in g["A"]} | {tuple(c["connector_rgb"]) for c in g["C"]}
    imported_groups = {c["id"] for c in g["C"] if "members" in c}
    for gid, members in groups.items():
        if gid in imported_groups:
            continue
        for nid in members:
            salt = 0
            value = coordinate(nid)
            while tuple(value) in external:
                salt += 1
                value = coordinate(nid, salt)
            nodes[nid]["rgb"] = value
            external.add(tuple(value))
    # Layout is a post-processing step. It has no influence on any edge.
    original_nodes = set(g.get("order", {}).get("neurons", []))
    imported_members = {nid for gid in imported_groups for nid in groups[gid]}
    for i, n in enumerate(g["A"]):
        if n["id"] in original_nodes or n["id"] in imported_members:
            continue
        nodes[n["id"]].update(x=100 + (i % 8) * 140, y=100 + (i // 8) * 100)
    for i, c in enumerate(net["ganglia"]):
        if c["id"] in imported_groups:
            continue
        x, y = 300 + (i % 4) * 500, 600 + (i // 4) * 500
        c.update(x=x, y=y)
        for nid in c["members"]:
            nodes[nid]["x"] += x
            nodes[nid]["y"] += y
    for key, order in g.get("order", {}).items():
        net[key] = genome_import.ordered(net[key], order)
    net = schema.topology(net)
    max_delay = max((s["delay"] for s in net["synapses"]), default=1)
    # Conservative kernel + Python document estimate; CPU, one worker only.
    estimate = len(nodes) * (4096 + (max_delay + 1) * 16) + edge_count(net) * 2048
    if estimate * (options["population"] + 4) > options["memory_mb"] * 1048576:
        raise ValueError("Бюджет памяти популяции")
    return net


def new_rule(identity, space, rng, options, anchor=None):
    a = anchor or rng.choice(space)
    b = rng.choice(space)
    kind = rng.choice(kinds(options))
    sign = 1 if options["direct_exc"] else -1
    if options["direct_exc"] and options["direct_inh"]:
        sign = rng.choice([-1, 1])
    return dict(
        id=identity,
        source_rgb=list(a["rgb"]),
        target_rgb=list(b["rgb"]),
        source_radius=0.12,
        target_radius=0.12,
        density=1.0,
        kind=kind,
        weight=sign * rng.uniform(0.2, 1.5),
        weight_std=0.0,
        delay=2,
        delay_max=2,
        source_polarity="any",
        target_polarity="any",
        seed=rng.randrange(2147483648),
    )


def initial(project, options):
    if options["mode"] == "current":
        return normalize(genome_import.from_project(project), project, options)
    if options["mode"] == "continue":
        extension = project.get("extensions", {}).get("evolution", {})
        if "genome" not in extension:
            raise ValueError("Для продолжения откройте сохранённый экземпляр эволюции")
        return normalize(extension["genome"], project, options)
    fixed = frozen(project)
    if not fixed:
        raise ValueError("Назначьте сенсоры и актуаторы перед эволюцией")
    g = dict(
        version=VERSION,
        decoder=DECODER,
        A=list(fixed.values()),
        B=[],
        C=[],
        D=[],
        frozen=sorted(fixed),
        bindings=copy.deepcopy(project["bindings"]),
    )
    rng = random.Random(seed("initial", options["seed"]))
    for i in range(min(4, max(0, options["max_neurons"] - len(fixed)))):
        nid = f"ev_n{i}"
        while nid in fixed:
            nid += "_"
        g["A"].append(schema.neuron(dict(id=nid, rgb=coordinate(nid), bias=rng.uniform(0, 0.2))))
    for i in range(min(8, options["max_rules"])):
        g["B"].append(new_rule(f"ev_b{i}", nodespace(g), rng, options))
    return normalize(g, project, options)


def mutate(parent, project, options, mutation_seed):
    g = copy.deepcopy(parent)
    rng = random.Random(seed("mutation", mutation_seed))
    scale = options["scale"]
    fixed = set(g["frozen"])

    def identity(block):
        return f"{block.lower()}_{rng.getrandbits(64):016x}"

    def perturb(value, low, high, unit=1):
        return max(low, min(high, value + rng.gauss(0, scale * unit)))

    def neuron_change(n):
        key = rng.choice(list(PARAMETERS) + ["rgb", "polarity", "reset_mode"])
        if key == "rgb":
            n[key] = [perturb(v, 0, 1) for v in n[key]]
        elif key == "polarity":
            n[key] = rng.choice(["mixed", "exc", "inh"])
        elif key == "reset_mode":
            n[key] = rng.choice(["retain", "reset"])
        else:
            lo, hi, unit = PARAMETERS[key]
            n[key] = perturb(n[key], lo, hi, unit)
            if key == "refractory":
                n[key] = round(n[key])

    # Coordinated additions give new structures an immediate connection opportunity.
    for block in "ACBD":
        if block in "CD" and options["preset"] != "ganglia":
            continue
        mutable = [n for n in g[block] if block != "A" or n["id"] not in fixed]
        if mutable and rng.random() < options["delete_rate"]:
            removed = rng.choice(mutable)
            g[block].remove(removed)
            if block == "C":
                genome_import.delete_group(g, removed)
            genome_import.prune_explicit(g)
        if rng.random() < options["add_rate"]:
            nid = identity(block)
            if block == "A":
                n = schema.neuron(dict(id=nid, rgb=coordinate(nid), bias=rng.uniform(0, 0.2)))
                g["A"].append(n)
                g["B"].append(new_rule(identity("B"), nodespace(g), rng, options, n))
            elif block == "C":
                c = dict(
                    id=nid,
                    rgb=coordinate(nid),
                    connector_rgb=coordinate(nid + ":connector"),
                    recipe=dict(
                        count=rng.randint(2, 8),
                        radius=100,
                        density=0.15,
                        excitatory=1
                        if not options["direct_inh"]
                        else 0
                        if not options["direct_exc"]
                        else 0.8,
                        weight=0.5,
                        delay=2,
                        mode="neurons",
                        kind=rng.choice(kinds(options)),
                        seed=rng.randrange(2147483648),
                        neuron={"bias": 0.03},
                    ),
                )
                g["C"].append(c)
                g["B"].append(
                    new_rule(
                        identity("B"),
                        nodespace(g),
                        rng,
                        options,
                        {"id": nid, "rgb": c["connector_rgb"]},
                    )
                )
            else:
                space = nodespace(g) if block == "B" else g["C"]
                if space:
                    g[block].append(new_rule(nid, space, rng, options))
        mutable = [n for n in g[block] if block != "A" or n["id"] not in fixed]
        if mutable and rng.random() < options["change_rate"]:
            n = rng.choice(mutable)
            if block == "A":
                neuron_change(n)
            elif block == "C" and "members" in n:
                genome_import.mutate_group(n, g, rng, options, identity, perturb, neuron_change)
            elif block == "C":
                p = n["recipe"]
                key = rng.choice(
                    [
                        "count",
                        "density",
                        "weight",
                        "delay",
                        "excitatory",
                        "neuron",
                        "rgb",
                        "connector_rgb",
                        "kind",
                        "radius",
                        "max_distance",
                        "mode",
                        "seed",
                    ]
                )
                if key in ("rgb", "connector_rgb"):
                    n[key] = [perturb(v, 0, 1) for v in n[key]]
                elif key == "neuron":
                    nn = schema.neuron(
                        {**p.get("neuron", {}), "id": "temporary", "rgb": coordinate("temporary")}
                    )
                    neuron_change(nn)
                    p["neuron"] = {
                        k: v
                        for k, v in nn.items()
                        if k in schema.NEURON and k not in ("x", "y", "label")
                    }
                elif key == "kind":
                    p[key] = rng.choice(kinds(options))
                elif key == "mode":
                    p[key] = rng.choice(["neurons", "synapses"])
                elif key == "seed":
                    p[key] = rng.randrange(2147483648)
                else:
                    lo, hi, unit = {
                        "count": (1, options["max_neurons"], 8),
                        "density": (0, 1, 1),
                        "weight": (0, 100, 2),
                        "delay": (1, 256, 10),
                        "excitatory": (0, 1, 1),
                        "radius": (30, 1000, 100),
                        "max_distance": (0, 3000, 100),
                    }[key]
                    p[key] = perturb(p.get(key, 0), lo, hi, unit)
                    if key in ("count", "delay"):
                        p[key] = round(p[key])
                if not options["direct_inh"]:
                    p["excitatory"] = 1
                if not options["direct_exc"]:
                    p["excitatory"] = 0
            elif genome_import.is_link(n):
                genome_import.mutate_link(n, g, rng, options, perturb)
            else:
                key = rng.choice(
                    [
                        "source_rgb",
                        "target_rgb",
                        "source_radius",
                        "target_radius",
                        "density",
                        "weight",
                        "weight_std",
                        "delay",
                        "delay_max",
                        "kind",
                        "seed",
                        "source_polarity",
                        "target_polarity",
                    ]
                )
                if key.endswith("rgb"):
                    n[key] = [perturb(v, 0, 1) for v in n[key]]
                elif key.endswith("polarity"):
                    n[key] = rng.choice(["any", "exc", "inh"])
                elif key == "kind":
                    n[key] = rng.choice(kinds(options))
                elif key == "seed":
                    n[key] = rng.randrange(2147483648)
                else:
                    lo, hi, unit = (
                        (0, math.sqrt(3), 1)
                        if key.endswith("radius")
                        else {
                            "density": (0, 1, 1),
                            "weight": (-100, 100, 2),
                            "weight_std": (0, 100, 1),
                            "delay": (1, 256, 10),
                            "delay_max": (1, 256, 10),
                        }[key]
                    )
                    n[key] = perturb(n[key], lo, hi, unit)
                    if key.startswith("delay"):
                        n[key] = round(n[key])
                    n["delay_max"] = max(n["delay"], n["delay_max"])
                if n["kind"] == "direct" and not (options["direct_exc"] and options["direct_inh"]):
                    n["weight"] = abs(n["weight"]) * (1 if options["direct_exc"] else -1)
    genome_import.repair_polarities(g)
    return normalize(prune(g), project, options)


def size(net):
    return dict(neurons=len(net["neurons"]), synapses=edge_count(net), ganglia=len(net["ganglia"]))
