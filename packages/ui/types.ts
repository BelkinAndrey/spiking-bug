export type Mode = "environment" | "editor";
export interface Neuron {
  id: string;
  label: string;
  kind: "sensor" | "motor" | "inter";
  x: number;
  y: number;
  threshold: number;
  leak: number;
  v_min: number;
  v_reset: number;
  refractory: number;
  noise_std: number;
  bias: number;
  reset_mode: "retain" | "reset";
  mod_tau_exc: number;
  mod_tau_inh: number;
  mod_gain_exc: number;
  mod_gain_inh: number;
  polarity: "mixed" | "exc" | "inh";
}
export interface Synapse {
  id: string;
  source: string;
  target: string;
  weight: number;
  delay: number;
  kind: "direct" | "mod_exc" | "mod_inh";
}
export interface Ganglion {
  id: string;
  label: string;
  x: number;
  y: number;
  radius: number;
  members: string[];
}
export interface Topology {
  format_version: number;
  task: string;
  neurons: Neuron[];
  synapses: Synapse[];
  ganglia: Ganglion[];
  groups: {
    id: string;
    label: string;
    x: number;
    y: number;
    w: number;
    h: number;
    color: string;
    comment: string;
  }[];
}
export interface WorldConfig {
  width: number;
  height: number;
  food_target: number;
  food_interval: number;
  threat_target: number;
  threat_mode: string;
  threat_radius: number;
  threat_speed_ratio: number;
  chase_duration: number;
  cooldown: number;
  threat_lifetime: number;
  speed: number;
  turn_speed: number;
  sensor_range: number;
  lidar_range: number;
  hunger_rate: number;
  fatigue_gain: number;
  fatigue_decay: number;
  seed: number;
}
export interface WorldObject {
  id: string;
  kind: "obstacle" | "food" | "threat";
  x: number;
  y: number;
  w?: number;
  h?: number;
  radius?: number;
  mode?: string;
  state?: string;
  interest?: number;
  rest?: number;
  ttl?: number;
}
export interface Zone {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}
export interface Project {
  compute: { device: string };
  version: number;
  name: string;
  revision: number;
  topology: Topology;
  bindings: Record<string, string>;
  world: {
    config: WorldConfig;
    objects: WorldObject[];
    zones: Zone[];
    spawn: { x: number; y: number; heading: number };
  };
}
export interface Sample {
  t: number;
  rates: Record<string, number>;
  spikes: number;
}
export interface State {
  compute: { device: string; notice: string };
  revision: number;
  session: number;
  t: number;
  running: boolean;
  speed: number;
  world: {
    config: WorldConfig;
    agent: {
      x: number;
      y: number;
      heading: number;
      health: number;
      hunger: number;
      fatigue: number;
      eaten: number;
      damage: number;
    };
    objects: WorldObject[];
    zones: Zone[];
    lidar: number[];
    sensors: Record<string, number>;
  };
  activity: {
    ids: string[];
    v: number[];
    counts: number[];
    exc: number[];
    inh: number[];
    sampled: boolean;
    total: number;
  };
  history: Sample[];
  stats: {
    neurons: number;
    synapses: number;
    step_ms: number;
    memory_mb: number;
    overruns: number;
    backend: string;
  };
  error: string | null;
}
export interface ComputeDevices {
  device: string;
  notice: string;
  devices: { id: string; label: string; available: boolean; reason: string }[];
}
export const labels: Record<string, string> = {
  food_left: "Пища · слева",
  food_right: "Пища · справа",
  threat_left: "Угроза · слева",
  threat_right: "Угроза · справа",
  hunger: "Голод",
  fatigue: "Усталость",
  lidar_0: "Лидар · −50°",
  lidar_1: "Лидар · −25°",
  lidar_2: "Лидар · центр",
  lidar_3: "Лидар · +25°",
  lidar_4: "Лидар · +50°",
  forward: "Вперёд",
  backward: "Назад",
  left: "Поворот влево",
  right: "Поворот вправо",
};
export const neuronDefaults: Omit<Neuron, "id" | "x" | "y"> = {
  label: "Neuron",
  kind: "inter",
  threshold: 1,
  leak: 0.08,
  v_min: -100,
  v_reset: 0,
  refractory: 2,
  noise_std: 0,
  bias: 0,
  reset_mode: "retain",
  mod_tau_exc: 2,
  mod_tau_inh: 2,
  mod_gain_exc: 1,
  mod_gain_inh: 1,
  polarity: "mixed",
};
