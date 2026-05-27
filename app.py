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

from environment import Environment, GymnasiumEnvironment
from snn import SpikingNetwork, preserved_kinds_map


# ---------------------------------------------------------------------- config

SIM_DT = 0.01           # 10 ms integration step (LIF time constant — keep fixed)
SIM_HZ_MAX = 100        # default and maximum steps per wall second
GYM_ENV_HZ_MAX = 240    # Gymnasium env.step calls per wall second
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
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

TASK_SPECS = {
    "BUG": {
        "label": "BUG",
        "kind": "bug",
        "factory": lambda: Environment(),
        "motors": ["motor_forward", "motor_backward", "motor_left", "motor_right"],
        "defaults": [
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
            ("motor_forward",      "Forward",  "motor", 720, 100),
            ("motor_backward",     "Back",     "motor", 720, 200),
            ("motor_left",         "Turn L",   "motor", 720, 300),
            ("motor_right",        "Turn R",   "motor", 720, 400),
        ],
    },
    "CartPole": {
        "label": "CartPole",
        "kind": "gym",
        "factory": lambda: GymnasiumEnvironment("CartPole", "CartPole-v1", ["left", "right"]),
        "motors": ["motor_left", "motor_right"],
        "reward_mode": "survival_up",
        "reward_steps": 500,
        "obs": [
            ("cart_position", "Cart X", 2.4),
            ("cart_velocity", "Cart V", 3.0),
            ("pole_angle", "Pole angle", 0.42),
            ("pole_angular_velocity", "Pole ang V", 3.5),
        ],
    },
    "MountainCar": {
        "label": "MountainCar",
        "kind": "gym",
        "factory": lambda: GymnasiumEnvironment(
            "MountainCar", "MountainCar-v0", ["left", "coast", "right"], default_action=1
        ),
        "motors": ["motor_left", "motor_coast", "motor_right"],
        "reward_mode": "time_budget_down",
        "reward_steps": 200,
        "obs": [
            ("position", "Position", 1.2),
            ("velocity", "Velocity", 0.07),
        ],
    },
}

current_task = "BUG"
env = Environment()
ENV_CACHE: dict[str, object] = {"BUG": env}
env_cache_lock = threading.Lock()
snn = SpikingNetwork(capacity=NEURON_CAPACITY)
sim_lock = threading.Lock()
running = True
sim_time = 0.0
sim_hz = SIM_HZ_MAX     # tunable at runtime via 'set_sim_hz'
gym_env_hz = 30         # tunable at runtime via 'set_gym_env_hz'
gym_env_accum = 0.0
manual_motor: dict[str, bool] = {}


# ------------------------------------------------------------------- defaults

DEFAULT_NEURONS: list[str] = []  # filled by build_default_network
DEFAULT_NEURON_IDS: set[str] = set()


SENSOR_LEAK = 0.02        # slow leak -> weak input still reaches threshold (slowly)
SENSOR_REFRACTORY = 2     # caps max firing rate near 30 Hz at dt=10ms
GYM_SENSOR_REFRACTORY = 0
MOTOR_LEAK = 0.12


def default_neuron_params(task: str, nid: str, kind: str) -> dict:
    threshold = 10.0 if task == "MountainCar" and nid == "sensor_reward" else 1.0
    sensor_refractory = GYM_SENSOR_REFRACTORY if TASK_SPECS[task]["kind"] == "gym" else SENSOR_REFRACTORY
    return {
        "threshold": threshold,
        "refractory": sensor_refractory if kind == "sensor" else 3,
    }


def gym_default_neurons(task: str) -> list[tuple[str, str, str, int, int]]:
    spec = TASK_SPECS[task]
    defs: list[tuple[str, str, str, int, int]] = []
    y = 70
    for obs_id, label, _ref in spec["obs"]:
        defs.append((f"sensor_{obs_id}_pos", f"{label} +", "sensor", 60, y))
        y += 45
        defs.append((f"sensor_{obs_id}_neg", f"{label} -", "sensor", 60, y))
        y += 55
    defs.append(("sensor_reward", "Reward", "sensor", 60, y + 20))
    my = 120
    for motor_id in spec["motors"]:
        label = motor_id.removeprefix("motor_").replace("_", " ").title()
        defs.append((motor_id, label, "motor", 720, my))
        my += 90
    return defs


def default_defs_for(task: str) -> list[tuple[str, str, str, int, int]]:
    spec = TASK_SPECS[task]
    if spec["kind"] == "gym":
        return gym_default_neurons(task)
    return list(spec["defaults"])


def build_default_network(task: str | None = None, reset: bool = False) -> None:
    """Place sensor & motor neurons that the environment wires to.

    These neuron IDs are special and must always be present.
    """
    global DEFAULT_NEURON_IDS
    task = task or current_task
    if reset:
        snn.load_json({"neurons": [], "synapses": [], "groups": []})
    DEFAULT_NEURONS.clear()
    defs = default_defs_for(task)
    for nid, label, kind, x, y in defs:
        if nid in snn.id_to_idx:
            DEFAULT_NEURONS.append(nid)
            continue
        params = default_neuron_params(task, nid, kind)
        snn.add_neuron(
            nid,
            label=label,
            kind=kind,
            x=x,
            y=y,
            threshold=params["threshold"],
            leak=MOTOR_LEAK if kind == "motor" else SENSOR_LEAK,
            v_reset=0.0,
            refractory=params["refractory"],
            noise_std=0.0,
        )
        DEFAULT_NEURONS.append(nid)
    DEFAULT_NEURON_IDS = set(DEFAULT_NEURONS)
    enforce_default_receptor_params(task)


def enforce_default_receptor_params(task: str | None = None) -> None:
    task = task or current_task
    if TASK_SPECS[task]["kind"] != "gym":
        return
    for nid in DEFAULT_NEURONS:
        rec = next((d for d in default_defs_for(task) if d[0] == nid), None)
        if rec and rec[2] == "sensor":
            snn.update_neuron(nid, refractory=GYM_SENSOR_REFRACTORY)


build_default_network()
manual_motor = {mid.removeprefix("motor_"): False for mid in TASK_SPECS[current_task]["motors"]}


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
REWARD_REF_STRONG = 1.0


def signal_to_current(raw: float, strong_ref: float) -> float:
    s = 0.0 if strong_ref <= 0 else raw / strong_ref
    if s < 0.0:
        s = 0.0
    elif s > 1.0:
        s = 1.0
    return s * I_MAX


def gym_reward_signal(env_task: str) -> float:
    spec = TASK_SPECS.get(env_task, {})
    step_attr = "last_episode_steps" if bool(getattr(env, "last_done", False)) else "episode_steps"
    steps = max(0, int(getattr(env, step_attr, 0)))
    ref_steps = max(1.0, float(spec.get("reward_steps", 1.0)))
    phase = max(0.0, min(1.0, steps / ref_steps))
    mode = spec.get("reward_mode")
    if mode == "survival_up":
        return phase
    if mode == "time_budget_down":
        return 1.0 - phase
    return max(0.0, min(1.0, float(getattr(env, "last_reward", 0.0))))


def gym_observation_components(
    env_task: str,
    obs_id: str,
    raw: float,
    strong_ref: float,
) -> tuple[float, float, float, float]:
    if env_task == "MountainCar" and obs_id == "position":
        min_pos = -1.2
        max_pos = 0.6
        neutral_pos = float(getattr(env, "position_neutral", -0.5))
        pos = max(0.0, raw - neutral_pos)
        neg = max(0.0, neutral_pos - raw)
        pos_ref = max(0.001, max_pos - neutral_pos)
        neg_ref = max(0.001, neutral_pos - min_pos)
        return pos, neg, pos_ref, neg_ref

    return max(0.0, raw), max(0.0, -raw), strong_ref, strong_ref


def compute_external_input() -> np.ndarray:
    ext = np.zeros(snn.capacity, dtype=np.float32)
    env_task = getattr(env, "task_id", current_task)

    def idx(nid: str) -> int | None:
        return snn.id_to_idx.get(nid)

    if env_task == "BUG":
        a = env.agent
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
    else:
        spec = TASK_SPECS[env_task]
        for (obs_id, _label, strong_ref), raw in zip(spec["obs"], env.obs):
            pos, neg, pos_ref, neg_ref = gym_observation_components(env_task, obs_id, float(raw), strong_ref)
            if (i := idx(f"sensor_{obs_id}_pos")) is not None:
                ext[i] = signal_to_current(pos, pos_ref)
            if (i := idx(f"sensor_{obs_id}_neg")) is not None:
                ext[i] = signal_to_current(neg, neg_ref)

    if (i := idx("sensor_reward")) is not None:
        if env_task == "BUG":
            reward = max(-REWARD_REF_STRONG, min(REWARD_REF_STRONG, float(getattr(env, "last_reward", 0.0))))
            ext[i] = reward / REWARD_REF_STRONG
        else:
            ext[i] = signal_to_current(gym_reward_signal(env_task), REWARD_REF_STRONG)

    # Manual motor injection
    for motor_id in TASK_SPECS[current_task]["motors"]:
        key = motor_id.removeprefix("motor_")
        if manual_motor.get(key):
            if (i := idx(motor_id)) is not None:
                ext[i] += MANUAL_MOTOR_DRIVE

    return ext


def active_motor_spikes() -> dict[str, bool]:
    motor_ids = TASK_SPECS[current_task]["motors"]
    if current_task != "BUG":
        manual_active = {
            motor_id: bool(manual_motor.get(motor_id.removeprefix("motor_")))
            for motor_id in motor_ids
        }
        if any(manual_active.values()):
            return manual_active

    active = {}
    for motor_id in motor_ids:
        motor_idx = snn.id_to_idx.get(motor_id)
        active[motor_id] = bool(snn.spikes[motor_idx]) if motor_idx is not None else False
    return active


# ----------------------------------------------------------------- sim thread

def simulation_loop() -> None:
    global sim_time, gym_env_accum
    last_broadcast = 0.0
    last_tick = time.perf_counter()
    broadcast_interval = 1.0 / BROADCAST_HZ
    while True:
        loop_start = time.perf_counter()
        wall_elapsed = loop_start - last_tick
        last_tick = loop_start
        # Recomputed each iteration so the slider takes effect immediately.
        wall_dt = 1.0 / max(1, min(SIM_HZ_MAX, sim_hz))

        if running:
            with sim_lock:
                ext = compute_external_input()
                snn.step(ext)
                env.apply_motor_actions(active_motor_spikes())
                if current_task == "BUG":
                    env.step(SIM_DT)
                    sim_time += SIM_DT
                else:
                    env_dt = 1.0 / max(1, min(GYM_ENV_HZ_MAX, gym_env_hz))
                    gym_env_accum += wall_elapsed
                    raw_steps_due = int(gym_env_accum / env_dt)
                    if raw_steps_due > 0:
                        steps_due = min(raw_steps_due, GYM_ENV_HZ_MAX)
                        for _ in range(steps_due):
                            env.step(env_dt)
                            sim_time += env_dt
                        if raw_steps_due > GYM_ENV_HZ_MAX:
                            gym_env_accum = 0.0
                        else:
                            gym_env_accum -= steps_due * env_dt

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
    env_snapshot = env.snapshot()
    if getattr(env, "task_id", current_task) != "BUG":
        env_snapshot["reward_signal"] = gym_reward_signal(getattr(env, "task_id", current_task))
    return {
        "t": sim_time,
        "running": running,
        "sim_hz": sim_hz,
        "gym_env_hz": gym_env_hz,
        "env": env_snapshot,
        "activity": snn.snapshot_state(),
        "pulses": snn.snapshot_pulses(SIM_DT),
    }


def build_topology_payload() -> dict:
    return {
        "topology": current_network_payload(),
        "default_neurons": sorted(DEFAULT_NEURON_IDS),
        "task": current_task,
        "tasks": [
            {"id": tid, "label": spec["label"], "kind": spec["kind"]}
            for tid, spec in TASK_SPECS.items()
        ],
        "motors": list(TASK_SPECS[current_task]["motors"]),
    }


def current_network_payload() -> dict:
    payload = snn.topology()
    payload["task"] = current_task
    payload["format_version"] = 2
    return payload


# ----------------------------------------------------------------- HTTP route

@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/api/saved")
def list_saved():
    groups = {tid: [] for tid in TASK_SPECS}
    files = []
    for p in sorted(SAVE_DIR.glob("*.json")):
        task = "BUG"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            task = normalize_task(data.get("task", "BUG"))
        except (OSError, json.JSONDecodeError):
            pass
        files.append(p.name)
        groups.setdefault(task, []).append(p.name)
    return jsonify({"files": files, "groups": groups})


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


@socketio.on("set_gym_env_hz")
def on_set_gym_env_hz(msg):
    global gym_env_hz
    try:
        v = int(msg.get("hz", gym_env_hz))
    except (TypeError, ValueError):
        return
    gym_env_hz = max(1, min(GYM_ENV_HZ_MAX, v))


@socketio.on("set_task")
def on_set_task(msg):
    task = normalize_task(msg.get("task", current_task))
    if task == current_task:
        socketio.emit("topology", build_topology_payload())
        socketio.emit("state", build_state_payload())
        return
    new_env = prepare_environment(task)
    with sim_lock:
        switch_task(task, reset_network=True, prepared_env=new_env)
    socketio.emit("topology", build_topology_payload())
    socketio.emit("state", build_state_payload())


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
    for motor_id in TASK_SPECS[current_task]["motors"]:
        k = motor_id.removeprefix("motor_")
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
            v_min=float(msg.get("v_min", -100.0)),
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
        payload = current_network_payload()
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
    task = normalize_task(data.get("task", "BUG"))
    new_env = prepare_environment(task) if task != current_task else None
    with sim_lock:
        if task != current_task:
            switch_task(task, reset_network=True, prepared_env=new_env)
        # Preserve sensor/motor positions if provided, but ensure defaults exist
        snn.load_json(data, preserved_kinds=DEFAULT_NEURON_IDS)
        # Ensure default neurons still exist (re-add missing)
        for nid in DEFAULT_NEURON_IDS:
            if nid not in snn.id_to_idx:
                # Re-add with sensible defaults
                build_one_default(nid)
        enforce_default_receptor_params(task)
    socketio.emit("topology", build_topology_payload())
    socketio.emit("state", build_state_payload())


def build_one_default(nid: str) -> None:
    rec = next((d for d in default_defs_for(current_task) if d[0] == nid), None)
    kind = rec[2] if rec else preserved_kinds_map(nid)
    label = rec[1] if rec else nid
    x = rec[3] if rec else 300
    y = rec[4] if rec else 300
    params = default_neuron_params(current_task, nid, kind)
    snn.add_neuron(
        nid, label=label, kind=kind, x=x, y=y,
        threshold=params["threshold"],
        leak=MOTOR_LEAK if kind == "motor" else SENSOR_LEAK,
        v_reset=0.0,
        refractory=params["refractory"],
        noise_std=0.0,
    )


def normalize_task(task: str | None) -> str:
    if task in TASK_SPECS:
        return task
    return "BUG"


def prepare_environment(task: str, reset_cached: bool = True):
    task = normalize_task(task)
    if task == "BUG":
        return TASK_SPECS[task]["factory"]()
    with env_cache_lock:
        cached = ENV_CACHE.get(task)
        if cached is not None:
            if reset_cached:
                cached.reset_agent()
            return cached

    new_env = TASK_SPECS[task]["factory"]()
    with env_cache_lock:
        existing = ENV_CACHE.setdefault(task, new_env)
        if existing is not new_env:
            if reset_cached:
                existing.reset_agent()
            return existing
    return new_env


def prewarm_gym_environments() -> None:
    for task, spec in TASK_SPECS.items():
        if spec["kind"] != "gym":
            continue
        try:
            prepare_environment(task, reset_cached=False)
        except Exception as exc:
            print(f"Failed to prewarm {task}: {exc}", file=sys.stderr)


def reset_manual_motor() -> None:
    manual_motor.clear()
    for motor_id in TASK_SPECS[current_task]["motors"]:
        manual_motor[motor_id.removeprefix("motor_")] = False


def switch_task(task: str, reset_network: bool = False, prepared_env=None) -> None:
    global current_task, env, sim_time, gym_env_accum
    task = normalize_task(task)
    new_env = prepared_env if prepared_env is not None else prepare_environment(task)
    current_task = task
    env = new_env
    sim_time = 0.0
    gym_env_accum = 0.0
    reset_manual_motor()
    build_default_network(task, reset=reset_network)


# --------------------------------------------------------------- thread start

prewarm_gym_environments()
_sim_thread = threading.Thread(target=simulation_loop, daemon=True)
_sim_thread.start()


if __name__ == "__main__":
    socketio.run(app, host="127.0.0.1", port=5000, debug=False, allow_unsafe_werkzeug=True)
