"""Flask + Socket.IO host for the spiking-bug research playground."""

from __future__ import annotations

import json
import math
import sys
import threading
import time
from pathlib import Path

# --- PyInstaller hints -----------------------------------------------------
# Flask-SocketIO picks its async driver dynamically (importlib by string),
# which PyInstaller's static analyzer cannot detect. Importing these two
# modules explicitly forces them into the bundle.
import engineio.async_drivers.threading  # noqa: F401
import simple_websocket                  # noqa: F401
# ---------------------------------------------------------------------------

import numpy as np
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO

from environment import Environment
from snn import SpikingNetwork, preserved_kinds_map


# ---------------------------------------------------------------------- config

SIM_DT = 0.01           # 10 ms integration step (LIF time constant — keep fixed)
SIM_HZ_MAX = 100        # default and maximum steps per wall second
BROADCAST_HZ = 30       # frontend update rate
NEURON_CAPACITY = 512

# When frozen by PyInstaller, __file__ points inside the temp _MEIxxx extract
# directory which is deleted at exit. Persist saved networks next to the .exe;
# read bundled resources (templates, static) from the extract dir.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
    RESOURCE_DIR = Path(sys._MEIPASS)            # PyInstaller temp extract dir
else:
    BASE_DIR = Path(__file__).parent
    RESOURCE_DIR = BASE_DIR
SAVE_DIR = BASE_DIR / "saved_networks"
SAVE_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------- state

app = Flask(
    __name__,
    static_folder=str(RESOURCE_DIR / "static"),
    template_folder=str(RESOURCE_DIR / "templates"),
)
app.config["SECRET_KEY"] = "spiking-bug-playground"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

env = Environment()
snn = SpikingNetwork(capacity=NEURON_CAPACITY)
sim_lock = threading.Lock()
running = True
sim_time = 0.0
sim_hz = SIM_HZ_MAX     # tunable at runtime via 'set_sim_hz'
manual_motor = {"forward": False, "backward": False, "left": False, "right": False}


# ------------------------------------------------------------------- defaults

DEFAULT_NEURONS = []  # filled by build_default_network


SENSOR_LEAK = 0.02        # slow leak -> weak input still reaches threshold (slowly)
SENSOR_REFRACTORY = 2     # caps max firing rate near 30 Hz at dt=10ms
MOTOR_LEAK = 0.12


def build_default_network() -> None:
    """Place sensor & motor neurons that the environment wires to.

    These neuron IDs are special and must always be present.
    """
    defs = [
        # sensors
        ("sensor_food_left",   "Food L",   "sensor",  60,  60),
        ("sensor_food_right",  "Food R",   "sensor",  60, 110),
        ("sensor_threat_left", "Threat L", "sensor",  60, 170),
        ("sensor_threat_right","Threat R", "sensor",  60, 220),
        ("sensor_hunger",      "Hunger",   "sensor",  60, 280),
        ("sensor_fatigue",     "Fatigue",  "sensor",  60, 330),
        ("lidar_0",            "Lidar 1",  "sensor",  60, 400),
        ("lidar_1",            "Lidar 2",  "sensor",  60, 440),
        ("lidar_2",            "Lidar 3",  "sensor",  60, 480),
        ("lidar_3",            "Lidar 4",  "sensor",  60, 520),
        ("lidar_4",            "Lidar 5",  "sensor",  60, 560),
        # motors
        ("motor_forward",  "Forward",  "motor", 720, 100),
        ("motor_backward", "Back",     "motor", 720, 200),
        ("motor_left",     "Turn L",   "motor", 720, 300),
        ("motor_right",    "Turn R",   "motor", 720, 400),
    ]
    for nid, label, kind, x, y in defs:
        snn.add_neuron(
            nid,
            label=label,
            kind=kind,
            x=x,
            y=y,
            threshold=1.0,
            leak=MOTOR_LEAK if kind == "motor" else SENSOR_LEAK,
            v_reset=0.0,
            refractory=SENSOR_REFRACTORY if kind == "sensor" else 3,
            noise_std=0.0,
        )
        DEFAULT_NEURONS.append(nid)


build_default_network()
DEFAULT_NEURON_IDS = set(DEFAULT_NEURONS)


# ------------------------------------------------------- input signal scaling

# Sensor signal -> sensor neuron input current.
# Normalize raw signal to s ∈ [0, 1] vs a "strong" reference, then I = s * I_MAX.
# With sensor LIF params (leak=0.02, V_th=1, refr=2, dt=0.01):
#   I=0     -> silent
#   I=0.025 -> ~1.2 Hz  (corresponds to s ≈ 0.025)
#   I=1.0   -> ~33 Hz   (s = 1.0, raw signal at or above strong reference)
I_MAX = 1.0
# Saturation references — chosen so a faint, distant stimulus already gives a
# ~1 Hz spike and a nearby stimulus saturates at ~30 Hz.
FOOD_REF_STRONG   = 3.0
THREAT_REF_STRONG = 4.0
LIDAR_REF_STRONG  = 1.0   # proximity already in [0, 1]
HUNGER_REF_STRONG  = 1.0  # hunger ∈ [0, 1] already
FATIGUE_REF_STRONG = 1.0
MANUAL_MOTOR_DRIVE = 1.5  # injected current per step while a manual button is held


def signal_to_current(raw: float, strong_ref: float) -> float:
    s = 0.0 if strong_ref <= 0 else raw / strong_ref
    if s < 0.0:
        s = 0.0
    elif s > 1.0:
        s = 1.0
    return s * I_MAX


def compute_external_input() -> np.ndarray:
    ext = np.zeros(snn.capacity, dtype=np.float32)
    a = env.agent

    def idx(nid: str) -> int | None:
        return snn.id_to_idx.get(nid)

    if (i := idx("sensor_food_left")) is not None:
        ext[i] = signal_to_current(a.food_left_signal, FOOD_REF_STRONG)
    if (i := idx("sensor_food_right")) is not None:
        ext[i] = signal_to_current(a.food_right_signal, FOOD_REF_STRONG)
    if (i := idx("sensor_threat_left")) is not None:
        ext[i] = signal_to_current(a.threat_left_signal, THREAT_REF_STRONG)
    if (i := idx("sensor_threat_right")) is not None:
        ext[i] = signal_to_current(a.threat_right_signal, THREAT_REF_STRONG)
    if (i := idx("sensor_hunger")) is not None:
        ext[i] = signal_to_current(a.hunger, HUNGER_REF_STRONG)
    if (i := idx("sensor_fatigue")) is not None:
        ext[i] = signal_to_current(a.fatigue, FATIGUE_REF_STRONG)
    for k in range(a.lidar_count):
        if (i := idx(f"lidar_{k}")) is not None:
            d = a.lidar_distances[k]
            proximity = max(0.0, 1.0 - d / a.lidar_range)
            ext[i] = signal_to_current(proximity, LIDAR_REF_STRONG)

    # Manual motor injection
    if manual_motor["forward"]:
        if (i := idx("motor_forward")) is not None:
            ext[i] += MANUAL_MOTOR_DRIVE
    if manual_motor["backward"]:
        if (i := idx("motor_backward")) is not None:
            ext[i] += MANUAL_MOTOR_DRIVE
    if manual_motor["left"]:
        if (i := idx("motor_left")) is not None:
            ext[i] += MANUAL_MOTOR_DRIVE
    if manual_motor["right"]:
        if (i := idx("motor_right")) is not None:
            ext[i] += MANUAL_MOTOR_DRIVE

    return ext


# ----------------------------------------------------------------- sim thread

def simulation_loop() -> None:
    global sim_time
    last_broadcast = 0.0
    broadcast_interval = 1.0 / BROADCAST_HZ
    while True:
        loop_start = time.perf_counter()
        # Recomputed each iteration so the slider takes effect immediately.
        wall_dt = 1.0 / max(1, min(SIM_HZ_MAX, sim_hz))

        if running:
            with sim_lock:
                ext = compute_external_input()
                snn.step(ext)
                fwd_idx = snn.id_to_idx.get("motor_forward")
                back_idx = snn.id_to_idx.get("motor_backward")
                left_idx = snn.id_to_idx.get("motor_left")
                right_idx = snn.id_to_idx.get("motor_right")
                fwd = bool(snn.spikes[fwd_idx]) if fwd_idx is not None else False
                back = bool(snn.spikes[back_idx]) if back_idx is not None else False
                lt = bool(snn.spikes[left_idx]) if left_idx is not None else False
                rt = bool(snn.spikes[right_idx]) if right_idx is not None else False
                env.apply_motor(fwd, back, lt, rt)
                env.step(SIM_DT)
                sim_time += SIM_DT

        # Broadcast at a fixed visual rate, independent of sim_hz.
        if time.perf_counter() - last_broadcast >= broadcast_interval:
            with sim_lock:
                payload = build_state_payload()
            socketio.emit("state", payload)
            last_broadcast = time.perf_counter()

        # Pace the rest of this wall_dt slice.
        elapsed = time.perf_counter() - loop_start
        if elapsed < wall_dt:
            time.sleep(wall_dt - elapsed)


def build_state_payload() -> dict:
    return {
        "t": sim_time,
        "running": running,
        "sim_hz": sim_hz,
        "env": env.snapshot(),
        "activity": snn.snapshot_state(),
        "pulses": snn.snapshot_pulses(SIM_DT),
    }


def build_topology_payload() -> dict:
    return {"topology": snn.topology(), "default_neurons": sorted(DEFAULT_NEURON_IDS)}


# ----------------------------------------------------------------- HTTP route

@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/api/saved")
def list_saved():
    files = sorted(p.name for p in SAVE_DIR.glob("*.json"))
    return jsonify({"files": files})


@app.route("/api/saved/<name>")
def get_saved(name: str):
    path = SAVE_DIR / name
    if not path.exists() or path.suffix != ".json":
        return jsonify({"error": "not found"}), 404
    return jsonify(json.loads(path.read_text(encoding="utf-8")))


# ----------------------------------------------------------- socket handlers

@socketio.on("connect")
def on_connect():
    socketio.emit("topology", build_topology_payload(), to=request.sid)
    socketio.emit("state", build_state_payload(), to=request.sid)


@socketio.on("set_sim_hz")
def on_set_sim_hz(msg):
    global sim_hz
    try:
        v = int(msg.get("hz", SIM_HZ_MAX))
    except (TypeError, ValueError):
        return
    sim_hz = max(1, min(SIM_HZ_MAX, v))


@socketio.on("control")
def on_control(msg):
    global running, sim_time
    action = msg.get("action")
    if action == "play":
        running = True
    elif action == "pause":
        running = False
    elif action == "reset_agent":
        with sim_lock:
            env.reset_agent()
    elif action == "reset_network":
        with sim_lock:
            snn.V[:] = 0
            snn.refractory_left[:] = 0
            snn.spikes[:] = False
            snn.spike_count[:] = 0


@socketio.on("place_object")
def on_place_object(msg):
    kind = msg.get("kind")
    x = float(msg.get("x", 0))
    y = float(msg.get("y", 0))
    with sim_lock:
        if kind == "food":
            env.add_food(x, y)
        elif kind == "threat":
            env.add_threat(x, y, radius=float(msg.get("radius", 12)))
        elif kind == "obstacle":
            w = float(msg.get("w", 40))
            h = float(msg.get("h", 40))
            env.add_obstacle(x - w / 2, y - h / 2, w, h)
        elif kind == "agent":
            env.agent.x = x
            env.agent.y = y


@socketio.on("remove_object")
def on_remove_object(msg):
    with sim_lock:
        env.remove_object(msg.get("kind"), int(msg.get("id")))


@socketio.on("clear_objects")
def on_clear_objects(msg):
    with sim_lock:
        env.clear_objects(msg.get("kind"))


@socketio.on("world_params")
def on_world_params(msg):
    with sim_lock:
        if "food_target" in msg:
            env.food_target = max(0, int(msg["food_target"]))
        if "threat_target" in msg:
            env.threat_target = max(0, int(msg["threat_target"]))
        if "threat_lifetime" in msg:
            env.threat_lifetime = max(0.5, float(msg["threat_lifetime"]))
        if "hunger_rate" in msg:
            env.hunger_rate = max(0.0, float(msg["hunger_rate"]))
        if "fatigue_action_gain" in msg:
            env.fatigue_action_gain = max(0.0, float(msg["fatigue_action_gain"]))
        if "fatigue_decay" in msg:
            env.fatigue_decay = max(0.0, float(msg["fatigue_decay"]))


@socketio.on("world_size")
def on_world_size(msg):
    with sim_lock:
        env.resize(int(msg.get("width", env.width)), int(msg.get("height", env.height)))


@socketio.on("manual_motor")
def on_manual_motor(msg):
    for k in ("forward", "backward", "left", "right"):
        if k in msg:
            manual_motor[k] = bool(msg[k])


# Network editor
@socketio.on("add_neuron")
def on_add_neuron(msg):
    nid = msg.get("id")
    if not nid:
        return
    with sim_lock:
        if nid in snn.id_to_idx:
            return
        snn.add_neuron(
            nid,
            label=msg.get("label", nid),
            kind=msg.get("kind", "inter"),
            x=float(msg.get("x", 300)),
            y=float(msg.get("y", 300)),
            threshold=float(msg.get("threshold", 1.0)),
            leak=float(msg.get("leak", 0.1)),
            v_reset=float(msg.get("v_reset", 0.0)),
            refractory=int(msg.get("refractory", 2)),
            noise_std=float(msg.get("noise_std", 0.0)),
        )
    socketio.emit("topology", build_topology_payload())


@socketio.on("update_neuron")
def on_update_neuron(msg):
    nid = msg.get("id")
    if not nid:
        return
    with sim_lock:
        snn.update_neuron(nid, **{k: v for k, v in msg.items() if k != "id"})
    socketio.emit("topology", build_topology_payload())


@socketio.on("remove_neuron")
def on_remove_neuron(msg):
    nid = msg.get("id")
    if not nid:
        return
    with sim_lock:
        try:
            snn.remove_neuron(nid)
        except ValueError:
            pass
    socketio.emit("topology", build_topology_payload())


@socketio.on("add_synapse")
def on_add_synapse(msg):
    f = msg.get("from")
    t = msg.get("to")
    if not f or not t:
        return
    w = float(msg.get("weight", 1.0))
    d = int(msg.get("delay", 5))
    with sim_lock:
        try:
            snn.add_synapse(f, t, w, delay=d)
        except KeyError:
            return
    socketio.emit("topology", build_topology_payload())


@socketio.on("remove_synapse")
def on_remove_synapse(msg):
    with sim_lock:
        snn.remove_synapse(msg.get("from"), msg.get("to"))
    socketio.emit("topology", build_topology_payload())


@socketio.on("add_group")
def on_add_group(msg):
    gid = msg.get("id")
    if not gid:
        return
    with sim_lock:
        snn.add_group(
            gid,
            x=msg.get("x", 0), y=msg.get("y", 0),
            w=msg.get("w", 200), h=msg.get("h", 120),
            label=msg.get("label", ""),
            color=msg.get("color", "#3a5cff"),
            comment=msg.get("comment", ""),
        )
    socketio.emit("topology", build_topology_payload())


@socketio.on("update_group")
def on_update_group(msg):
    gid = msg.get("id")
    if not gid:
        return
    with sim_lock:
        snn.update_group(gid, **{k: v for k, v in msg.items() if k != "id"})
    socketio.emit("topology", build_topology_payload())


@socketio.on("remove_group")
def on_remove_group(msg):
    gid = msg.get("id")
    if not gid:
        return
    with sim_lock:
        snn.remove_group(gid)
    socketio.emit("topology", build_topology_payload())


@socketio.on("save_network")
def on_save_network(msg):
    name = (msg.get("name") or "network").strip()
    if not name.endswith(".json"):
        name += ".json"
    name = "".join(c for c in name if c.isalnum() or c in ("_", "-", ".")) or "network.json"
    path = SAVE_DIR / name
    with sim_lock:
        payload = snn.to_json()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    socketio.emit("saved", {"name": name})


@socketio.on("load_network")
def on_load_network(msg):
    data = msg.get("data")
    if data is None:
        name = msg.get("name")
        if not name:
            return
        path = SAVE_DIR / name
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
    with sim_lock:
        # Preserve sensor/motor positions if provided, but ensure defaults exist
        snn.load_json(data, preserved_kinds=DEFAULT_NEURON_IDS)
        # Ensure default neurons still exist (re-add missing)
        for nid in DEFAULT_NEURON_IDS:
            if nid not in snn.id_to_idx:
                # Re-add with sensible defaults
                build_one_default(nid)
    socketio.emit("topology", build_topology_payload())


def build_one_default(nid: str) -> None:
    kind = preserved_kinds_map(nid)
    label = nid
    snn.add_neuron(
        nid, label=label, kind=kind, x=300, y=300,
        threshold=1.0,
        leak=MOTOR_LEAK if kind == "motor" else SENSOR_LEAK,
        v_reset=0.0,
        refractory=SENSOR_REFRACTORY if kind == "sensor" else 3,
        noise_std=0.0,
    )


# --------------------------------------------------------------- thread start

_sim_thread = threading.Thread(target=simulation_loop, daemon=True)
_sim_thread.start()


if __name__ == "__main__":
    socketio.run(app, host="127.0.0.1", port=5000, debug=False, allow_unsafe_werkzeug=True)
