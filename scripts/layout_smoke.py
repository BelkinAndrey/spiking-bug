"""Check graph geometry, port placement and preservation of live neural state.

Run: .venv/bin/python scripts/layout_smoke.py
"""

import copy
import math
from pathlib import Path
import sys
import time
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import schema
from server.app import create_app
from server.layout import arrange
from server.runtime import Conflict, Runtime


def geometry(net, bindings):
    nodes = {n["id"]: n for n in net["neurons"]}
    sensors = {bindings.get(c) for c in schema.SENSORS} - {None, ""}
    motors = {bindings.get(c) for c in schema.MOTORS} - {None, ""}
    middle = set(nodes) - sensors - motors
    if sensors:
        assert len({nodes[i]["x"] for i in sensors}) == 1
        assert all(nodes[s]["x"] < nodes[m]["x"] for s in sensors for m in middle | motors)
    if motors:
        assert len({nodes[i]["x"] for i in motors}) == 1
        assert all(nodes[m]["x"] > nodes[i]["x"] for m in motors for i in middle | sensors)
    points = np.array([[n["x"], n["y"]] for n in nodes.values()])
    assert np.isfinite(points).all()
    if len(points) < 300:
        for i, p in enumerate(points):
            delta = np.abs(points[i + 1 :] - p)
            assert not np.any((delta[:, 0] < 129.99) & (delta[:, 1] < 79.99)), "Overlapping nodes"
    for group in net["ganglia"]:
        for nid in group["members"]:
            n = nodes[nid]
            assert math.hypot(n["x"] - group["x"], n["y"] - group["y"]) < group["radius"]


def dynamics(net):
    result = copy.deepcopy(net)
    for n in result["neurons"]:
        for key in ("x", "y"):
            n.pop(key)
    for g in result["ganglia"]:
        for key in ("x", "y", "radius"):
            g.pop(key)
    for f in result["groups"]:
        for key in ("x", "y", "w", "h"):
            f.pop(key)
    return result


def main():
    runtime = Runtime()
    project = runtime.project()
    bindings = project["bindings"]
    net = copy.deepcopy(project["topology"])
    for i in range(80):
        net["neurons"].append(dict(id=f"hidden_{i:03}", x=i * 30, y=0))
    for i in range(80):
        net["synapses"].append(
            dict(
                id=f"cycle_{i}",
                source=f"hidden_{i:03}",
                target=f"hidden_{(i + 1) % 80:03}",
                weight=1,
            )
        )
    net["ganglia"] = [
        dict(id="cluster", x=400, y=0, radius=300, members=[f"hidden_{i:03}" for i in range(12)])
    ]
    net["synapses"] += [
        dict(id="input", source=bindings["food_left"], target="cluster", weight=1),
        dict(id="output", source="cluster", target=bindings["forward"], weight=1),
        dict(id="parallel", source="hidden_000", target="hidden_001", kind="mod_exc", weight=1),
        dict(id="self", source="hidden_001", target="hidden_001", weight=1),
    ]
    net["groups"] = [
        dict(
            id="frame", x=-10, y=-10, w=100, h=40, label="Remember", comment="Keep", color="#123456"
        )
    ]
    net = schema.topology(net)
    original = copy.deepcopy(net)
    arranged = arrange(net, bindings)
    assert net == original, "Layout mutated input"
    assert dynamics(arranged) == dynamics(net), "Layout changed network semantics"
    geometry(arranged, bindings)
    again = arrange(arranged, bindings)
    assert again["neurons"] == arranged["neurons"], "Layout is not repeatable"
    shuffled = copy.deepcopy(net)
    shuffled["neurons"].reverse()
    shuffled["synapses"].reverse()
    assert {n["id"]: n for n in arrange(shuffled, bindings)["neurons"]} == {
        n["id"]: n for n in arranged["neurons"]
    }
    frame = arranged["groups"][0]
    for n in arranged["neurons"]:
        before = next(v for v in net["neurons"] if v["id"] == n["id"])
        if -10 <= before["x"] <= 90 and -10 <= before["y"] <= 30:
            assert frame["x"] <= n["x"] <= frame["x"] + frame["w"]
            assert frame["y"] <= n["y"] <= frame["y"] + frame["h"]
    for n in net["neurons"]:
        if n["id"] in bindings.values():
            n["kind"] = "inter"
    geometry(arrange(net, bindings), bindings)
    empty = schema.topology({"neurons": [], "synapses": []})
    assert arrange(empty, {}) == empty
    one = schema.topology({"neurons": [{"id": "one"}], "synapses": []})
    assert len(arrange(one, {})["neurons"]) == 1

    # Layout must preserve the kernel object, delay queue, noise stream and world.
    reference = Runtime()
    for _ in range(15):
        runtime.step()
        reference.step()
    kernel = runtime.net
    state = runtime.snapshot()
    app = create_app(runtime)
    client = app.test_client()
    response = client.post(
        "/api/command", json=dict(action="layout", data={}, revision=runtime.revision)
    )
    assert response.status_code == 200, response.json
    assert runtime.net is kernel
    assert {k: v for k, v in runtime.snapshot().items() if k != "revision"} == {
        k: v for k, v in state.items() if k != "revision"
    }
    assert (
        client.post("/api/command", json=dict(action="layout", data={}, revision=0)).status_code
        == 409
    )
    for _ in range(50):
        runtime.step()
        reference.step()
    for field in runtime.net.state_fields:
        np.testing.assert_array_equal(
            runtime.net.host_values(field), reference.net.host_values(field)
        )
    assert runtime.world.snapshot() == reference.world.snapshot()
    runtime.command("topology", project["topology"], runtime.revision)
    assert runtime.net is kernel, "Undo rebuilt kernel"
    assert runtime.net.topology == project["topology"]
    # Reject a stale calculation atomically if another client edited meanwhile.
    original = copy.deepcopy(runtime.net.topology)

    def concurrent_edit(topology, bindings):
        runtime.command("name", {"name": "Concurrent"}, runtime.revision)
        return arranged

    with patch("server.runtime.arrange", side_effect=concurrent_edit):
        try:
            runtime.command("layout", {}, runtime.revision)
        except Conflict:
            pass
        else:
            raise AssertionError("Concurrent edit was overwritten")
    assert runtime.net.topology == original
    runtime.bindings["forward"] = bindings["food_left"]
    assert (
        client.post(
            "/api/command", json=dict(action="layout", data={}, revision=runtime.revision)
        ).status_code
        == 400
    )
    assert runtime.net.topology == original
    app.extensions["evolution"].close()

    large = schema.topology(
        dict(
            neurons=[dict(id=f"n{i:05}") for i in range(3000)],
            synapses=[
                dict(source=f"n{i:05}", target=f"n{i + 1:05}", weight=1) for i in range(2999)
            ],
        )
    )
    start = time.monotonic()
    result = arrange(large, {})
    assert len({(n["x"], n["y"]) for n in result["neurons"]}) == 3000
    print(
        f"PASS: anchors, cycles, connectors, frames, collisions, determinism, state, undo, conflicts; 3000 nodes in {time.monotonic() - start:.2f}s"
    )


if __name__ == "__main__":
    main()
