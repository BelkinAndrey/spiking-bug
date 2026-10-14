import { t } from "./i18n";
import { Connection, escape, handle, toast, uid } from "./api";
import { Viewport, circle, type Point } from "./canvas";
import { field, input, select, onForm } from "./forms";
import {
  labels,
  neuronDefaults,
  type Neuron,
  type Synapse,
  type Ganglion,
  type Topology,
} from "./types";

type Frame = Topology["groups"][number];
type FrameHandle = "nw" | "n" | "ne" | "e" | "se" | "s" | "sw" | "w";
const frameHandles: [FrameHandle, number, number][] = [
  ["nw", 0, 0],
  ["n", 0.5, 0],
  ["ne", 1, 0],
  ["e", 1, 0.5],
  ["se", 1, 1],
  ["s", 0.5, 1],
  ["sw", 0, 1],
  ["w", 0, 0.5],
];
const frameCursors: Record<FrameHandle, string> = {
  nw: "nwse-resize",
  n: "ns-resize",
  ne: "nesw-resize",
  e: "ew-resize",
  se: "nwse-resize",
  s: "ns-resize",
  sw: "nesw-resize",
  w: "ew-resize",
};

export class EditorView {
  tool = "select";
  tab = "inspect";
  selected = new Set<string>();
  selectedEdge?: string;
  selectedGanglion?: string;
  selectedFrame?: string;
  source?: string;
  private draft?: Synapse;
  private cursor?: Point;
  private frameColor?: { id: string; color: string };
  private projectionSource?: string;
  private projectionTarget?: string;
  nodes = new Map<string, Neuron>();
  groups = new Map<string, Ganglion>();
  private drag?: {
    start: Point;
    last: Point;
    pan: boolean;
    positions: Map<string, Point>;
    moved: boolean;
    group?: { id: string; x: number; y: number };
    frame?: { original: Frame; handle?: FrameHandle; revision: number };
    ganglia?: Map<string, Point>;
  };
  private clipboard?: { neurons: Neuron[]; synapses: Synapse[] };
  private undo: Topology[] = [];
  private flashes = new Map<string, number>();
  private counts = new Map<string, number>();
  private frameSession = 0;
  constructor(
    public api: Connection,
    public view: Viewport,
    public side: HTMLElement,
  ) {
    view.canvas.addEventListener("pointerdown", (e) => this.down(e));
    view.canvas.addEventListener("pointermove", (e) => this.move(e));
    view.canvas.addEventListener("pointerup", () => this.up());
    view.canvas.addEventListener("pointercancel", () => {
      this.cancelFrameDrag();
      this.drag = undefined;
      this.view.canvas.style.cursor = "default";
      handle(api.refresh());
    });
    document.addEventListener("keydown", (e) => {
      if ((e.target as HTMLElement).closest("input,select,textarea,dialog"))
        return;
      if ((e.metaKey || e.ctrlKey) && e.key === "c") {
        this.copy();
        e.preventDefault();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "v") {
        this.paste();
        e.preventDefault();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "z") {
        this.restore();
        e.preventDefault();
      }
      if (e.key === "Delete" || e.key === "Backspace") {
        this.remove();
        e.preventDefault();
      }
      if (e.key === "Escape") {
        this.cancelFrameDrag();
        this.source = undefined;
        this.selected.clear();
        this.selectedEdge = undefined;
        this.selectedGanglion = undefined;
        this.selectedFrame = undefined;
        this.setTool("select");
        this.renderSide();
      }
    });
  }
  resetDocument() {
    this.selected.clear();
    this.selectedEdge = undefined;
    this.selectedGanglion = undefined;
    this.selectedFrame = undefined;
    this.drag = undefined;
    this.clipboard = undefined;
    this.undo = [];
    this.flashes.clear();
    this.counts.clear();
    this.tab = "inspect";
    this.setTool("select");
    this.fit();
  }
  rebuild() {
    if (
      this.drag?.frame &&
      this.drag.frame.revision !== this.api.project.revision
    ) {
      this.drag = undefined;
      this.view.canvas.style.cursor = "default";
    }
    this.nodes = new Map(
      this.api.project.topology.neurons.map((n) => [n.id, n]),
    );
    this.groups = new Map(
      this.api.project.topology.ganglia.map((g) => [g.id, g]),
    );
    for (const id of this.selected)
      if (!this.nodes.has(id)) this.selected.delete(id);
  }
  fit() {
    const ns = this.api.project.topology.neurons;
    if (!ns.length) {
      this.view.fit(0, 0, 1000, 700);
      return;
    }
    let left = Infinity,
      top = Infinity,
      right = -Infinity,
      bottom = -Infinity;
    for (const n of ns) {
      left = Math.min(left, n.x);
      top = Math.min(top, n.y);
      right = Math.max(right, n.x);
      bottom = Math.max(bottom, n.y);
    }
    for (const g of this.groups.values()) {
      left = Math.min(left, g.x - g.radius);
      top = Math.min(top, g.y - g.radius);
      right = Math.max(right, g.x + g.radius);
      bottom = Math.max(bottom, g.y + g.radius);
    }
    this.view.fit(left - 70, top - 90, right - left + 200, bottom - top + 160);
  }
  toolbar() {
    return [
      ["select", "↖", t("Выбрать / переместить")],
      ["pan", "↔", t("Панорама")],
      ["neuron", "⊕", t("Создать нейрон")],
      ["connect", "↗", t("Создать синапс")],
      ["ganglion", "◉", t("Нарисовать ганглий")],
      ["projection", "⇢", t("Связать ганглии")],
      ["box", "▣", t("Выделить область")],
      ["frame", "▱", t("Создать рамку")],
    ];
  }
  setTool(tool: string) {
    this.tool = tool;
    this.source = undefined;
    this.draft = undefined;
    this.projectionSource = undefined;
    this.projectionTarget = undefined;
    document
      .querySelectorAll<HTMLElement>("[data-tool]")
      .forEach((b) => b.classList.toggle("active", b.dataset.tool === tool));
    this.view.canvas.style.cursor =
      tool === "pan" ? "grab" : tool === "select" ? "default" : "crosshair";
    document.getElementById("stage-hint")!.textContent = (
      {
        select: t(
          "Перетаскивание — переместить · Shift — добавить к выбору · ⌘C / ⌘V",
        ),
        pan: t("Перетаскивание — панорама · колесо — масштаб"),
        neuron: t("Щёлкните по полю, чтобы создать нейрон"),
        connect: t("Выберите источник, затем нейрон или коннектор ганглия"),
        ganglion: t("От центра потяните до края будущего ганглия"),
        box: t("Выделите прямоугольную область"),
        frame: t("Нарисуйте рамку вокруг функциональной группы"),
        projection: t("Выберите ганглий-источник, затем ганглий-получатель"),
      } as Record<string, string>
    )[tool];
    if (tool === "projection") this.tab = "inspect";
    if (this.api.project) this.renderSide();
  }
  async commit(
    topology: Topology,
    previous = structuredClone(this.api.project.topology),
  ) {
    await this.api.command("topology", topology);
    this.undo.push(previous);
    if (this.undo.length > 20) this.undo.shift();
  }
  restore() {
    const topology = this.undo.pop();
    if (topology)
      handle(
        this.api
          .command("topology", topology)
          .then(() => toast(t("Предыдущее изменение восстановлено"))),
      );
  }
  copy() {
    const net = this.api.project.topology;
    this.clipboard = {
      neurons: structuredClone(
        net.neurons.filter((n) => this.selected.has(n.id)),
      ),
      synapses: structuredClone(
        net.synapses.filter(
          (s) => this.selected.has(s.source) && this.selected.has(s.target),
        ),
      ),
    };
    toast(t("Скопировано нейронов: {0}", this.clipboard.neurons.length));
  }
  paste() {
    if (!this.clipboard?.neurons.length) return;
    const net = structuredClone(this.api.project.topology),
      mapping = new Map(this.clipboard.neurons.map((n) => [n.id, uid("n")]));
    const ns = this.clipboard.neurons.map((n) => ({
      ...n,
      id: mapping.get(n.id)!,
      x: n.x + 50,
      y: n.y + 50,
    }));
    net.neurons.push(...ns);
    net.synapses.push(
      ...this.clipboard.synapses.map((s) => ({
        ...s,
        id: uid("s"),
        source: mapping.get(s.source)!,
        target: mapping.get(s.target)!,
      })),
    );
    this.selected = new Set(ns.map((n) => n.id));
    handle(this.commit(net));
  }
  remove() {
    const net = structuredClone(this.api.project.topology);
    if (this.selectedFrame) {
      net.groups = net.groups.filter((f) => f.id !== this.selectedFrame);
      this.selectedFrame = undefined;
      handle(this.commit(net));
      return;
    }
    if (this.selectedEdge) {
      net.synapses = net.synapses.filter((s) => s.id !== this.selectedEdge);
      this.selectedEdge = undefined;
      handle(this.commit(net));
      return;
    } else if (this.selectedGanglion) {
      const g = this.groups.get(this.selectedGanglion);
      if (g) for (const n of g.members) this.selected.add(n);
      net.ganglia = net.ganglia.filter((g) => g.id !== this.selectedGanglion);
    }
    net.neurons = net.neurons.filter((n) => !this.selected.has(n.id));
    net.ganglia = net.ganglia
      .map((g) => ({
        ...g,
        members: g.members.filter((n) => !this.selected.has(n)),
      }))
      .filter((g) => g.members.length);
    const ids = new Set([
      ...net.neurons.map((n) => n.id),
      ...net.ganglia.map((g) => g.id),
    ]);
    net.synapses = net.synapses.filter(
      (s) => ids.has(s.source) && ids.has(s.target),
    );
    this.selected.clear();
    this.selectedEdge = undefined;
    this.selectedGanglion = undefined;
    this.selectedFrame = undefined;
    handle(this.commit(net));
  }
  renderSide() {
    this.view.canvas.dataset.revision = String(this.api.project.revision);
    this.frameColor = undefined;
    this.rebuild();
    this.side.innerHTML = `<div class="side-tabs">${[
      ["inspect", t("Инспектор")],
      ["build", t("Генератор")],
      ["list", t("Нейроны")],
    ]
      .map(
        ([id, t]) =>
          `<button data-tab="${id}" class="${this.tab === id ? "active" : ""}">${t}</button>`,
      )
      .join("")}</div><div id="side-content"></div>`;
    this.side.querySelectorAll<HTMLElement>("[data-tab]").forEach(
      (b) =>
        (b.onclick = () => {
          this.tab = b.dataset.tab!;
          if (this.tool === "projection" || this.draft) this.setTool("select");
          else this.renderSide();
        }),
    );
    const content = this.side.querySelector<HTMLElement>("#side-content")!;
    if (this.tool === "projection") {
      this.projectionForm(content);
      return;
    }
    if (this.draft && this.tool === "connect") {
      if (this.target(this.draft.source) && this.target(this.draft.target)) {
        this.synapseForm(content, this.draft, true);
        return;
      }
      this.draft = undefined;
      this.source = undefined;
    }
    if (this.tab === "build") {
      this.generator(content);
      return;
    }
    if (this.tab === "list") {
      content.innerHTML = `<div class="section"><h3>${t("Нервная система")}</h3><input id="neuron-search" class="search" placeholder="${t("Поиск по ID или имени")}" aria-label="${t("Поиск нейронов")}"><div class="list" id="neuron-list"></div><p class="help">${t("Показаны первые 200 совпадений. Выбор нейрона открывает параметры и центрирует поле.")}</p></div>`;
      const render = (q = "") => {
        const ns = this.api.project.topology.neurons
          .filter((n) =>
            (n.id + " " + n.label).toLowerCase().includes(q.toLowerCase()),
          )
          .slice(0, 200);
        content.querySelector("#neuron-list")!.innerHTML = ns
          .map(
            (n) =>
              `<button data-id="${escape(n.id)}"><span class="dot" style="background:${this.color(n)}"></span>${escape(n.label)}<small>${escape(n.id)}</small></button>`,
          )
          .join("");
        content.querySelectorAll<HTMLElement>("[data-id]").forEach(
          (b) =>
            (b.onclick = () => {
              this.selected = new Set([b.dataset.id!]);
              this.selectedEdge = undefined;
              this.selectedGanglion = undefined;
              this.selectedFrame = undefined;
              this.tab = "inspect";
              const n = this.nodes.get(b.dataset.id!)!;
              this.view.x = this.view.width / 2 - n.x * this.view.zoom;
              this.view.y = this.view.height / 2 - n.y * this.view.zoom;
              this.renderSide();
            }),
        );
      };
      render();
      content.querySelector<HTMLInputElement>("#neuron-search")!.oninput = (
        e,
      ) => render((e.target as HTMLInputElement).value);
      return;
    }
    const frame = this.api.project.topology.groups.find(
      (f) => f.id === this.selectedFrame,
    );
    if (frame) {
      const palette = [
        ["#657586", t("Серый")],
        ["#84bcca", t("Голубой")],
        ["#82a8ed", t("Синий")],
        ["#bba8ed", t("Фиолетовый")],
        ["#dc94b5", t("Розовый")],
        ["#e69586", t("Коралловый")],
        ["#e3ba7e", t("Золотой")],
        ["#bad881", t("Зелёный")],
      ];
      // Canvas accepts legacy CSS colors; normalize them for the native color input.
      const probe = document.createElement("canvas").getContext("2d")!;
      probe.fillStyle = "#657586";
      probe.fillStyle = frame.color;
      const pickerColor = /^#[0-9a-f]{6}$/i.test(probe.fillStyle)
        ? probe.fillStyle
        : "#657586";
      content.innerHTML = `<form id="frame-form" class="section"><h3>${t("Визуальная рамка")}</h3><div class="fields">${input("label", t("Название"), frame.label, true)}<div class="full frame-colors"><label>${t("Цвет")}<input name="color" type="color" value="${escape(pickerColor)}"></label><div class="frame-palette" role="group" aria-label="${t("Палитра")}">${palette.map(([color, label]) => `<button type="button" class="frame-swatch" data-color="${color}" style="--swatch:${color}" aria-label="${label}" title="${label}" aria-pressed="${color === pickerColor}"></button>`).join("")}</div></div><label class="full">${t("Комментарий")}<textarea name="comment">${escape(frame.comment)}</textarea></label></div><button class="primary wide">${t("Сохранить рамку")}</button><button type="button" class="wide danger" id="delete-frame">${t("Удалить только рамку")}</button><p class="help">${t("Тяните заголовок или границу, чтобы переместить рамку вместе с нейронами внутри. Ручки по краям меняют только размер рамки.")}</p></form>`;
      const colorInput = content.querySelector<HTMLInputElement>(
        'input[name="color"]',
      )!;
      const updateColor = () => {
        this.frameColor = { id: frame.id, color: colorInput.value };
        content
          .querySelectorAll<HTMLButtonElement>("[data-color]")
          .forEach((button) => {
            button.setAttribute(
              "aria-pressed",
              String(button.dataset.color === colorInput.value),
            );
          });
      };
      colorInput.oninput = updateColor;
      content
        .querySelectorAll<HTMLButtonElement>("[data-color]")
        .forEach((button) => {
          button.onclick = () => {
            colorInput.value = button.dataset.color!;
            updateColor();
          };
        });
      onForm(content, "frame-form", (v) => {
        if (!this.frameColor) v.color = frame.color;
        const net = structuredClone(this.api.project.topology);
        net.groups = net.groups.map((f) =>
          f.id === frame.id ? { ...f, ...v } : f,
        );
        handle(this.commit(net));
      });
      content.querySelector<HTMLElement>("#delete-frame")!.onclick = () =>
        this.remove();
      return;
    }
    const n = this.nodes.get([...this.selected][0]);
    const s = this.api.project.topology.synapses.find(
      (s) => s.id === this.selectedEdge,
    );
    const g = this.groups.get(this.selectedGanglion!);
    if (s) {
      this.synapseForm(content, s);
      return;
    }
    if (g) {
      content.innerHTML = `<div class="section"><h3>${t("Ганглий")}</h3><h2>${escape(g.label)}</h2><p class="mono subtle">${escape(g.id)}</p><div class="live-values">${g.members.length} ${t("нейронов · r =")} ${g.radius.toFixed(0)}</div><p class="help">${t("Коннектор принимает сигнал для всех участников и передаёт спайки каждого участника наружу. Собственной динамики нет; знак прямой связи следует полярности источника.")}</p><button class="wide" id="select-members">${t("Выделить все нейроны")}</button><button class="wide" id="rename-group">${t("Переименовать")}</button><button class="wide danger" id="delete">${t("Удалить ганглий и его нейроны")}</button></div>`;
      content.insertAdjacentHTML(
        "beforeend",
        `<form id="ganglion-rgb" class="section"><h3>${t("Координаты развития")}</h3><p class="help">${t("RGB ганглия и коннектора принадлежат разным пространствам. Перемещение на холсте их не меняет.")}</p><div class="fields">${["rgb", "connector_rgb"].map((key) => ["R", "G", "B"].map((label, i) => field(key + "_" + i, (key === "rgb" ? t("Ганглий") : t("Коннектор")) + " · " + label, (key === "rgb" ? g.rgb : g.connector_rgb)?.[i] ?? 0, "any", 0, 1)).join("")).join("")}</div><button class="primary wide">${t("Сохранить координаты")}</button></form>`,
      );
      onForm(content, "ganglion-rgb", (v) => {
        const net = structuredClone(this.api.project.topology);
        const group = net.ganglia.find((item) => item.id === g.id)!;
        group.rgb = [v.rgb_0, v.rgb_1, v.rgb_2];
        group.connector_rgb = [
          v.connector_rgb_0,
          v.connector_rgb_1,
          v.connector_rgb_2,
        ];
        handle(this.commit(net));
      });
      content.querySelector<HTMLElement>("#select-members")!.onclick = () => {
        this.selected = new Set(g.members);
        this.selectedGanglion = undefined;
        this.selectedFrame = undefined;
        this.renderSide();
      };
      content.querySelector<HTMLElement>("#rename-group")!.onclick = () => {
        const label = prompt(t("Название ганглия"), g.label);
        if (label) {
          const net = structuredClone(this.api.project.topology);
          net.ganglia.find((x) => x.id === g.id)!.label = label;
          handle(this.commit(net));
        }
      };
      content.querySelector<HTMLElement>("#delete")!.onclick = () =>
        this.remove();
      return;
    }
    if (n) {
      const bound = Object.entries(this.api.project.bindings).filter(([, id]) =>
        this.selected.has(id),
      );
      content.innerHTML = `<form id="neuron-form"><div class="section"><div class="row spread"><h3>${this.selected.size > 1 ? t("{0} нейронов", this.selected.size) : t("Нейрон")}</h3><span class="pill">LIF</span></div><p class="mono small subtle">${escape(n.id)}</p><div class="live-values" id="neuron-live">V — · E — · I —</div><div class="fields">${this.selected.size === 1 ? input("label", t("Название"), n.label, true) : ""}${this.selected.size === 1 ? ["R", "G", "B"].map((label, i) => field("rgb_" + i, "RGB · " + label, n.rgb?.[i] ?? 0, "any", 0, 1)).join("") : ""}${field("threshold", t("Порог"), n.threshold, 0.05, -10000, 10000)}${field("leak", t("Утечка / такт"), n.leak, 0.01, 0, 1)}${field("refractory", t("Рефрактерность, такты"), n.refractory, 1, 0, 10000)}${field("bias", t("Постоянный ток"), n.bias, 0.01, -100, 100)}${field("noise_std", t("Шум · σ / такт"), n.noise_std, 0.01, 0, 100)}${field("v_min", t("Нижняя граница V"), n.v_min, 0.1, -10000, 0)}${select("reset_mode", t("После спайка"), n.reset_mode, { retain: t("Сохранить потенциал"), reset: t("Сбросить потенциал в 0") }, true)}${select("polarity", t("Полярность исходящих связей"), n.polarity, { mixed: t("Любой знак"), exc: t("Только возбуждающие"), inh: t("Только тормозящие") }, true)}</div><p class="help">${t("Утечка и входящие токи действуют постоянно. Рефрактерный период запрещает только спайк. 1 такт = 10 мс.")}</p></div><div class="section"><h3>${t("Модуляция чувствительности")}</h3><div class="fields">${field("mod_tau_exc", t("Возврат E · τ, с"), n.mod_tau_exc, 0.1, 0.01, 3600)}${field("mod_tau_inh", t("Возврат I · τ, с"), n.mod_tau_inh, 0.1, 0.01, 3600)}${field("mod_gain_exc", t("Отклик E"), n.mod_gain_exc, 0.1, 0, 100)}${field("mod_gain_inh", t("Отклик I"), n.mod_gain_inh, 0.1, 0, 100)}</div><p class="help">${t("E — возбуждение, I — торможение. Коэффициенты возвращаются к 1 экспоненциально и ограничены диапазоном 0…10.")}</p><button class="primary wide">${this.selected.size > 1 ? t("Применить ко всем выбранным") : t("Применить параметры")}</button></div></form><div class="section"><h3>${t("Связь с окружением")}</h3>${bound.length ? bound.map(([c, id]) => `<p class="help">${labels[c]} → <span class="mono">${escape(id)}</span></p>`).join("") : `<p class="help">${t("Не назначен ни одному каналу. Назначения доступны во вкладке «Нейроны» окружения.")}</p>`}<div class="button-row"><button id="inject">${t("Импульс +2")}</button><button id="connect">${t("Связать ↗")}</button></div><div class="button-row"><button id="copy">${t("Копировать")}</button><button class="danger" id="delete">${t("Удалить")}</button></div></div>`;
      const related = this.api.project.topology.synapses.filter(
        (s) => this.selected.has(s.source) || this.selected.has(s.target),
      );
      content.insertAdjacentHTML(
        "beforeend",
        `<div class="section"><h3>${t("Связи ·")} ${related.length}</h3><div class="list">${related
          .slice(0, 200)
          .map(
            (s) =>
              `<button data-edge="${escape(s.id)}"><span>${escape(s.source)} → ${escape(s.target)}<br><small>${s.kind} · w ${s.weight} · ${s.delay * 10} ms</small></span></button>`,
          )
          .join(
            "",
          )}</div>${related.length > 200 ? `<p class="help">${t("Показаны первые 200 связей выбранных нейронов.")}</p>` : ""}</div>`,
      );
      content.querySelectorAll<HTMLElement>("[data-edge]").forEach(
        (b) =>
          (b.onclick = () => {
            this.selectedEdge = b.dataset.edge;
            this.selected.clear();
            this.renderSide();
          }),
      );
      onForm(content, "neuron-form", (v) => {
        if (this.selected.size === 1) {
          v.rgb = [v.rgb_0, v.rgb_1, v.rgb_2];
          delete v.rgb_0;
          delete v.rgb_1;
          delete v.rgb_2;
        }
        const net = structuredClone(this.api.project.topology);
        net.neurons = net.neurons.map((n) =>
          this.selected.has(n.id) ? { ...n, ...v } : n,
        );
        handle(this.commit(net));
      });
      content.querySelector<HTMLElement>("#inject")!.onclick = () =>
        handle(
          this.api
            .command("inject", { id: n.id, current: 2 }, false)
            .then(() => toast(t("Импульс подан на следующий такт"))),
        );
      content.querySelector<HTMLElement>("#connect")!.onclick = () => {
        this.setTool("connect");
        this.source = n.id;
        toast(t("Выберите нейрон-получатель или коннектор"));
      };
      content.querySelector<HTMLElement>("#copy")!.onclick = () => this.copy();
      content.querySelector<HTMLElement>("#delete")!.onclick = () =>
        this.remove();
      return;
    }
    content.innerHTML = `<div class="section"><h3>${t("Инспектор")}</h3><p class="empty">${t("Выберите нейрон, синапс или ганглий, чтобы увидеть параметры.")}</p><div class="button-row"><button id="new-neuron">${t("＋ Нейрон")}</button><button id="new-ganglion">${t("◉ Ганглий")}</button></div></div><div class="section"><h3>${t("Три вида связей")}</h3><p class="help"><span style="color:#bad881">━━</span> ${t("Прямая: положительный вес возбуждает, отрицательный тормозит.")}</p><p class="help"><span style="color:#bba8ed">┄┄</span> ${t("Модуляция E: изменяет чувствительность к возбуждению.")}</p><p class="help"><span style="color:#82bfd0">┄┄</span> ${t("Модуляция I: изменяет чувствительность к торможению.")}</p></div><div class="section"><h3>${t("Быстрые действия")}</h3><p class="help">${t("⌘ / Ctrl + C, V — копировать и вставить")}<br>${t("⌘ / Ctrl + Z — отменить изменение сети")}<br>${t("Delete — удалить выбранное")}<br>${t("Shift + щелчок — множественный выбор")}<br>${t("Средняя кнопка — панорама")}<br>${t("Колесо — масштаб под курсором")}</p><button class="wide" id="undo">${t("Отменить изменение сети")}</button></div>`;
    content.querySelector<HTMLElement>("#new-neuron")!.onclick = () =>
      this.setTool("neuron");
    content.querySelector<HTMLElement>("#new-ganglion")!.onclick = () => {
      this.tab = "build";
      this.renderSide();
    };
    content.querySelector<HTMLElement>("#undo")!.onclick = () => this.restore();
  }
  generator(content: HTMLElement, center?: Point, radius = 180) {
    const p =
      center ??
      this.view.world({ x: this.view.width / 2, y: this.view.height / 2 });
    content.innerHTML = `<form id="ganglion-form"><div class="section"><h3>${t("Создать ганглий")}</h3><div class="fields">${input("label", t("Название"), "Ganglion", true)}${field("count", t("Число нейронов"), 40, 1, 1, 200000)}${field("radius", t("Радиус области"), Math.round(radius), 1, 30, 50000)}${field("x", t("Центр X"), Math.round(p.x))}${field("y", t("Центр Y"), Math.round(p.y))}${field("density", t("Вероятность связи"), 0.08, 0.01, 0, 1)}${field("max_distance", t("Макс. расстояние · 0 = без лимита"), 0, "any", 0, 300000)}${field("excitatory", t("Доля возбуждающих"), 0.8, 0.05, 0, 1)}${select("mode", t("Как распределить знаки"), "neurons", { neurons: t("Возбуждающие / тормозящие нейроны"), synapses: t("Случайный знак каждой связи") }, true)}${field("weight", t("Модуль веса"), 0.5, 0.05, 0, 100)}${field("delay", t("Задержка, такты"), 2, 1, 1, 256)}${field("seed", t("Seed генерации"), 42, 1, 0, 2147483647)}</div><p class="help">${t("Нейроны равномерно распределены по площади круга. Плотность — вероятность связи среди пар в пределах максимального расстояния; самосвязи исключены. 0 — без ограничения дальности. Лимит сети — 500 000 связей; для 200 000 нейронов без ограничения дальности используйте вероятность около 0,00001 или меньше.")}</p></div><div class="section"><h3>${t("Параметры новых нейронов")}</h3><div class="fields">${field("threshold", t("Порог"), 1, 0.05, 0.001, 10000)}${field("leak", t("Утечка / такт"), 0.08, 0.01, 0, 1)}${field("refractory", t("Рефрактерность"), 2, 1, 0, 10000)}${field("bias", t("Постоянный ток"), 0, 0.01, -100, 100)}${select("reset_mode", t("После спайка"), "retain", { retain: t("Сохранить потенциал"), reset: t("Сбросить в 0") }, true)}</div><button class="primary wide">${t("Сгенерировать ганглий")}</button><p class="help">${t("Коннектор справа от круга передаёт любой выбранный тип воздействия всем нейронам внутри.")}</p></div></form>`;
    onForm(content, "ganglion-form", (v) => {
      const { threshold, leak, refractory, bias, reset_mode, ...params } = v;
      const previous = structuredClone(this.api.project.topology);
      handle(
        this.api
          .command("ganglion", {
            ...params,
            id: uid("g"),
            neuron: { threshold, leak, refractory, bias, reset_mode },
          })
          .then(() => {
            this.undo.push(previous);
            this.tab = "inspect";
            this.selected.clear();
            this.selectedGanglion =
              this.api.project.topology.ganglia.at(-1)?.id;
            this.renderSide();
            toast(t("Ганглий создан"));
          }),
      );
    });
  }
  synapseForm(content: HTMLElement, s: Synapse, isNew = false) {
    if (isNew) this.draft = s;
    content.innerHTML = `<form id="synapse-form" class="section"><h3>${isNew ? t("Новая связь") : t("Синапс")}</h3><div class="fields">${select("source", t("От нейрона / коннектора"), s.source, { ...Object.fromEntries([...this.nodes].map(([id, n]) => [id, `${n.label} · ${id}`])), ...Object.fromEntries([...this.groups].map(([id, g]) => [id, `◉ ${g.label} · ${id}`])) }, true)}${select("target", t("К нейрону / ганглию"), s.target, { ...Object.fromEntries([...this.nodes].map(([id, n]) => [id, `${n.label} · ${id}`])), ...Object.fromEntries([...this.groups].map(([id, g]) => [id, t("◉ {0} · все {1}", g.label, g.members.length)])) }, true)}${select("kind", t("Действие"), s.kind, { direct: t("Прямое воздействие"), mod_exc: t("Модуляция возбуждения · E"), mod_inh: t("Модуляция торможения · I") }, true)}${field("weight", t("Вес со знаком"), s.weight, 0.05, -10000, 10000)}${field("delay", t("Задержка, такты"), s.delay, 1, 1, 256)}</div><p class="help">${t("Для модулирующей связи + увеличивает чувствительность, − уменьшает. Мембранный потенциал напрямую не меняется.")}</p><button class="primary wide">${isNew ? t("Создать связь") : t("Сохранить связь")}</button>${!isNew ? `<button type="button" class="wide danger" id="delete-edge">${t("Удалить связь")}</button>` : ""}</form>`;
    if (isNew)
      content
        .querySelector<HTMLFormElement>("#synapse-form")!
        .addEventListener("input", () => {
          const data = new FormData(
            content.querySelector<HTMLFormElement>("#synapse-form")!,
          );
          this.draft = {
            ...s,
            source: String(data.get("source")),
            target: String(data.get("target")),
            kind: data.get("kind") as Synapse["kind"],
            weight: Number(data.get("weight")),
            delay: Number(data.get("delay")),
          };
          this.source = this.draft.source;
        });
    onForm(content, "synapse-form", (v) => {
      const net = structuredClone(this.api.project.topology);
      const edge = { ...s, ...v };
      if (isNew) net.synapses.push(edge);
      else net.synapses = net.synapses.map((x) => (x.id === s.id ? edge : x));
      this.selectedEdge = s.id;
      handle(
        this.commit(net).then(() => {
          this.source = undefined;
          this.draft = undefined;
          if (isNew) this.setTool("connect");
          else this.renderSide();
        }),
      );
    });
    content
      .querySelector<HTMLElement>("#delete-edge")
      ?.addEventListener("click", () => this.remove());
  }
  ganglionAt(p: Point, boundaryOnly = false) {
    return (
      this.connector(p) ??
      [...this.groups.values()].reverse().find((g) => {
        const d = Math.hypot(g.x - p.x, g.y - p.y);
        const header =
          p.x >= g.x - g.radius &&
          p.x <= g.x + g.radius &&
          p.y >= g.y - g.radius - 28 / this.view.zoom &&
          p.y <= g.y - g.radius;
        return (
          header ||
          (boundaryOnly
            ? Math.abs(d - g.radius) < 10 / this.view.zoom
            : d <= g.radius)
        );
      })
    );
  }
  projectionForm(content: HTMLElement) {
    const options = {
      "": t("Выберите ганглий"),
      ...Object.fromEntries(
        [...this.groups.values()].map((g) => [
          g.id,
          t("{0} · {1} нейронов", g.label, g.members.length),
        ]),
      ),
    };
    content.innerHTML = `<form id="projection-form" class="section"><h3>${t("Связи между ганглиями")}</h3><div class="fields">${select("source", t("Источник"), this.projectionSource ?? "", options, true)}${select("source_polarity", t("Нейроны-источники"), "any", { any: t("Любые"), exc: t("Только возбуждающие"), inh: t("Только тормозящие") }, true)}${select("target", t("Получатель"), this.projectionTarget ?? "", options, true)}${select("target_polarity", t("Целевые нейроны"), "any", { any: t("Любые"), exc: t("Только возбуждающие"), inh: t("Только тормозящие") }, true)}${select("kind", t("Тип связей"), "direct", { direct: t("Прямые · знак по полярности"), mod_exc: t("Модуляция возбуждения · E"), mod_inh: t("Модуляция торможения · I") }, true)}${field("density", t("Вероятность связи"), 0.1, "any", 0, 1)}${field("weight", t("Вес"), 0.5, "any", -10000, 10000)}${field("delay", t("Задержка, такты"), 1, 1, 1, 256)}${field("seed", "Seed", 42, 1, 0, 2147483647)}${field("max_distance", t("Макс. расстояние · 0 = без лимита"), 0, "any", 0, 300000)}</div><p class="help">${t("Связи направлены от выбранного типа нейронов первого ганглия к выбранному типу нейронов второго. Фильтры источников и получателей независимы. Нейроны со смешанной полярностью входят только в «Любые». Для прямых связей знак определяется полярностью источника, для mixed — знаком веса. Модуляция использует указанный знак. Существующие пары того же типа пропускаются.")}</p><button class="primary wide" ${this.groups.size < 2 ? "disabled" : ""}>${t("Сгенерировать связи")}</button><p class="help">${t("Выберите два круга на поле или укажите их здесь.")} ${this.groups.size < 2 ? t("Сначала создайте минимум два ганглия.") : ""}</p></form>`;
    for (const key of ["source", "target"])
      content.querySelector<HTMLSelectElement>(`[name="${key}"]`)!.onchange = (
        e,
      ) => {
        const value = (e.target as HTMLSelectElement).value;
        if (key === "source") this.projectionSource = value;
        else this.projectionTarget = value;
      };
    onForm(content, "projection-form", (v) => {
      const previous = structuredClone(this.api.project.topology);
      handle(
        this.api
          .command("connect_ganglia", { ...v, id: uid("projection") })
          .then((result) => {
            if (result.added_synapses) {
              this.undo.push(previous);
              if (this.undo.length > 20) this.undo.shift();
            }
            toast(t("Создано связей: {0}", result.added_synapses));
          }),
      );
    });
  }
  hit(p: Point) {
    const r = Math.max(13, 12 / this.view.zoom);
    return [...this.nodes.values()]
      .reverse()
      .find((n) => Math.hypot(n.x - p.x, n.y - p.y) < r);
  }
  connector(p: Point) {
    return [...this.groups.values()].find(
      (g) =>
        Math.hypot(g.x + g.radius + 28 - p.x, g.y - p.y) <
        Math.max(15, 15 / this.view.zoom),
    );
  }
  edgeHit(p: Point) {
    const threshold = 7 / this.view.zoom;
    return this.api.project.topology.synapses.find((s) => {
      const a = this.target(s.source),
        b = this.target(s.target);
      if (!a || !b) return false;
      const dx = b.x - a.x,
        dy = b.y - a.y,
        l = dx * dx + dy * dy;
      if (l === 0) return false;
      const t = Math.max(
        0,
        Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l),
      );
      return Math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy) < threshold;
    });
  }
  target(id: string): Point | undefined {
    const g = this.groups.get(id);
    return g ? { x: g.x + g.radius + 28, y: g.y } : this.nodes.get(id);
  }
  cancelFrameDrag() {
    const d = this.drag;
    if (!d?.frame) return;
    if (d.frame.revision === this.api.project.revision) {
      const frame = this.api.project.topology.groups.find(
        (f) => f.id === d.frame!.original.id,
      );
      if (frame) Object.assign(frame, d.frame.original);
      for (const [id, p] of d.positions) Object.assign(this.nodes.get(id)!, p);
      for (const [id, p] of d.ganglia ?? [])
        Object.assign(this.groups.get(id)!, p);
    }
    this.drag = undefined;
    this.view.canvas.style.cursor = "default";
  }
  frameHandleAt(p: Point) {
    const frame = this.api.project.topology.groups.find(
      (f) => f.id === this.selectedFrame,
    );
    if (!frame) return;
    const handle = frameHandles.find(
      ([, x, y]) =>
        Math.abs(p.x - frame.x - x * frame.w) <= 8 / this.view.zoom &&
        Math.abs(p.y - frame.y - y * frame.h) <= 8 / this.view.zoom,
    );
    if (handle) return { frame, handle: handle[0] };
  }
  frameAt(p: Point) {
    const margin = 6 / this.view.zoom;
    return [...this.api.project.topology.groups]
      .reverse()
      .find(
        (f) =>
          p.x >= f.x - margin &&
          p.x <= f.x + f.w + margin &&
          p.y >= f.y - margin &&
          p.y <= f.y + f.h + margin &&
          (p.y <= f.y + Math.min(f.h, 28 / this.view.zoom) ||
            p.y >= f.y + f.h - margin ||
            p.x <= f.x + margin ||
            p.x >= f.x + f.w - margin),
      );
  }
  beginFrameDrag(frame: Frame, handle?: FrameHandle) {
    const d = this.drag!;
    this.selected.clear();
    this.selectedEdge = undefined;
    this.selectedGanglion = undefined;
    this.selectedFrame = frame.id;
    d.frame = {
      original: { ...frame },
      handle,
      revision: this.api.project.revision,
    };
    if (!handle) {
      for (const n of this.nodes.values()) {
        if (
          n.x >= frame.x &&
          n.x <= frame.x + frame.w &&
          n.y >= frame.y &&
          n.y <= frame.y + frame.h
        )
          d.positions.set(n.id, { x: n.x, y: n.y });
      }
      // Keep a ganglion's circle and connector aligned when every member moves.
      d.ganglia = new Map();
      for (const g of this.groups.values()) {
        if (g.members.length && g.members.every((id) => d.positions.has(id)))
          d.ganglia.set(g.id, { x: g.x, y: g.y });
      }
    }
    this.view.canvas.style.cursor = handle ? frameCursors[handle] : "grabbing";
    this.tab = "inspect";
    this.renderSide();
  }
  down(e: PointerEvent) {
    if (e.button !== 0 && e.button !== 1) return;
    this.view.canvas.setPointerCapture(e.pointerId);
    const p = this.view.point(e),
      hit = this.hit(p),
      connector = this.connector(p);
    this.drag = {
      start: p,
      last: p,
      pan: this.tool === "pan" || e.button === 1,
      positions: new Map(),
      moved: false,
    };
    if (this.drag.pan) return;
    if (this.tool === "projection") {
      this.drag = undefined;
      const g = this.ganglionAt(p);
      if (g) {
        if (!this.projectionSource || this.projectionTarget) {
          this.projectionSource = g.id;
          this.projectionTarget = undefined;
        } else if (g.id !== this.projectionSource) this.projectionTarget = g.id;
        else toast(t("Выберите другой ганглий"));
        this.renderSide();
      }
      return;
    }
    if (this.tool === "neuron") {
      const net = structuredClone(this.api.project.topology),
        n = { ...neuronDefaults, ...p, id: uid("n") };
      net.neurons.push(n);
      this.selected = new Set([n.id]);
      this.selectedEdge = undefined;
      this.selectedGanglion = undefined;
      this.selectedFrame = undefined;
      this.tab = "inspect";
      handle(this.commit(net));
      this.drag = undefined;
      return;
    }
    if (this.tool === "connect") {
      this.drag = undefined;
      if (!this.source) {
        if (connector || hit) {
          const endpoint = connector ?? hit!;
          this.source = endpoint.id;
          toast(t("Источник: {0}. Выберите получателя.", endpoint.label));
        }
        return;
      }
      const target = connector?.id ?? hit?.id;
      if (target) {
        this.draft = undefined;
        this.tab = "inspect";
        this.selected.clear();
        this.selectedEdge = undefined;
        this.selectedGanglion = undefined;
        this.selectedFrame = undefined;
        this.renderSide();
        this.synapseForm(
          this.side.querySelector("#side-content")!,
          {
            id: uid("s"),
            source: this.source,
            target,
            kind: "direct",
            weight: this.nodes.get(this.source)?.polarity === "inh" ? -1 : 1,
            delay: 1,
          },
          true,
        );
      }
      return;
    }
    if (this.tool === "select") {
      const resize = this.frameHandleAt(p);
      const frame = resize?.frame ?? this.frameAt(p);
      if (frame) {
        this.beginFrameDrag(frame, resize?.handle);
        return;
      }
      this.selectedEdge = undefined;
      this.selectedGanglion = undefined;
      this.selectedFrame = undefined;
      const groupHandle = this.ganglionAt(p, true);
      if (hit && !groupHandle) {
        if (e.shiftKey) {
          if (this.selected.has(hit.id)) this.selected.delete(hit.id);
          else this.selected.add(hit.id);
        } else if (!this.selected.has(hit.id))
          this.selected = new Set([hit.id]);
        for (const id of this.selected) {
          const n = this.nodes.get(id)!;
          this.drag.positions.set(id, { x: n.x, y: n.y });
        }
      } else {
        this.selected.clear();
        const edge = this.edgeHit(p);
        if (groupHandle) this.selectedGanglion = groupHandle.id;
        else if (edge) this.selectedEdge = edge.id;
        else {
          const g = [...this.groups.values()].find(
            (g) => Math.hypot(g.x - p.x, g.y - p.y) < g.radius,
          );
          if (g) this.selectedGanglion = g.id;
          else {
            this.drag.pan = true;
          }
        }
      }
      if (this.selectedGanglion) {
        const g = this.groups.get(this.selectedGanglion)!;
        this.drag.group = { id: g.id, x: g.x, y: g.y };
        for (const id of g.members) {
          const n = this.nodes.get(id)!;
          this.drag.positions.set(id, { x: n.x, y: n.y });
        }
      }
      this.tab = "inspect";
      this.renderSide();
    }
  }
  move(e: PointerEvent) {
    this.cursor = this.view.point(e);
    if (!this.drag) {
      if (this.tool === "select") {
        const resize = this.frameHandleAt(this.cursor);
        this.view.canvas.style.cursor = resize
          ? frameCursors[resize.handle]
          : this.frameAt(this.cursor)
            ? "grab"
            : "default";
      }
      return;
    }
    const d = this.drag;
    if (
      !d.moved &&
      Math.hypot(this.cursor.x - d.start.x, this.cursor.y - d.start.y) *
        this.view.zoom <
        3
    )
      return;
    d.moved = true;
    if (d.pan) {
      this.view.x += e.movementX;
      this.view.y += e.movementY;
      return;
    }
    d.last = this.view.point(e);
    if (d.frame) {
      const f = this.api.project.topology.groups.find(
        (f) => f.id === d.frame!.original.id,
      )!;
      const original = d.frame.original;
      const dx = d.last.x - d.start.x,
        dy = d.last.y - d.start.y;
      const h = d.frame.handle;
      if (h) {
        // Anchor the opposite side and clamp rather than invert the rectangle.
        const min = 10;
        if (h.includes("w")) {
          f.w = Math.max(min, Math.min(100000, original.w - dx));
          f.x = original.x + original.w - f.w;
        }
        if (h.includes("e"))
          f.w = Math.max(min, Math.min(100000, original.w + dx));
        if (h.includes("n")) {
          f.h = Math.max(min, Math.min(100000, original.h - dy));
          f.y = original.y + original.h - f.h;
        }
        if (h.includes("s"))
          f.h = Math.max(min, Math.min(100000, original.h + dy));
      } else {
        f.x = original.x + dx;
        f.y = original.y + dy;
        for (const [id, p] of d.ganglia!) {
          const g = this.groups.get(id)!;
          g.x = p.x + dx;
          g.y = p.y + dy;
        }
      }
    }
    if (d.group) {
      const g = this.groups.get(d.group.id)!;
      g.x = d.group.x + d.last.x - d.start.x;
      g.y = d.group.y + d.last.y - d.start.y;
    }
    for (const [id, p] of d.positions) {
      const n = this.nodes.get(id)!;
      n.x = p.x + d.last.x - d.start.x;
      n.y = p.y + d.last.y - d.start.y;
    }
  }
  up() {
    const d = this.drag;
    this.drag = undefined;
    if (!d) return;
    if (d.frame) {
      this.view.canvas.style.cursor = "grab";
      if (!d.moved) return;
      const net = structuredClone(this.api.project.topology);
      const previous = structuredClone(net);
      previous.groups = previous.groups.map((f) =>
        f.id === d.frame!.original.id ? d.frame!.original : f,
      );
      for (const n of previous.neurons) {
        const p = d.positions.get(n.id);
        if (p) Object.assign(n, p);
      }
      for (const g of previous.ganglia) {
        const p = d.ganglia?.get(g.id);
        if (p) Object.assign(g, p);
      }
      handle(
        this.commit(net, previous).catch(async (error) => {
          await this.api.refresh();
          throw error;
        }),
      );
      return;
    }
    if (d.pan) {
      this.view.save();
      return;
    }
    if (this.tool === "ganglion") {
      this.tab = "build";
      this.renderSide();
      this.generator(
        this.side.querySelector("#side-content")!,
        d.start,
        Math.max(30, Math.hypot(d.last.x - d.start.x, d.last.y - d.start.y)),
      );
    }
    if (this.tool === "box") {
      this.selected = new Set(
        [...this.nodes.values()]
          .filter(
            (n) =>
              n.x >= Math.min(d.start.x, d.last.x) &&
              n.x <= Math.max(d.start.x, d.last.x) &&
              n.y >= Math.min(d.start.y, d.last.y) &&
              n.y <= Math.max(d.start.y, d.last.y),
          )
          .map((n) => n.id),
      );
      this.selectedEdge = undefined;
      this.selectedGanglion = undefined;
      this.selectedFrame = undefined;
      this.tab = "inspect";
      this.renderSide();
    }
    if (this.tool === "frame" && d.moved) {
      const net = structuredClone(this.api.project.topology);
      const frameId = uid("frame");
      net.groups.push({
        id: frameId,
        label: "Functional group",
        comment: "",
        color: "#657586",
        x: Math.min(d.start.x, d.last.x),
        y: Math.min(d.start.y, d.last.y),
        w: Math.max(10, Math.abs(d.start.x - d.last.x)),
        h: Math.max(10, Math.abs(d.start.y - d.last.y)),
      });
      this.selectedFrame = frameId;
      this.selected.clear();
      this.selectedEdge = undefined;
      this.selectedGanglion = undefined;
      this.tab = "inspect";
      this.setTool("select");
      handle(this.commit(net));
    }
    if (d.group && d.moved) {
      handle(
        this.api
          .command("move_ganglion", {
            id: d.group.id,
            dx: d.last.x - d.start.x,
            dy: d.last.y - d.start.y,
          })
          .catch(async (e) => {
            await this.api.refresh();
            throw e;
          }),
      );
      return;
    }
    if (d.positions.size && d.moved)
      handle(
        this.api.command("positions", {
          positions: [...d.positions].map(([id]) => {
            const n = this.nodes.get(id)!;
            return { id, x: n.x, y: n.y };
          }),
        }),
      );
  }
  color(n: Neuron) {
    return n.kind === "sensor"
      ? "#84bcca"
      : n.kind === "motor"
        ? "#e3ba7e"
        : n.polarity === "inh"
          ? "#d88a85"
          : "#c5d995";
  }
  updateActivity() {
    const s = this.api.state;
    if (!s) return;
    if (s.session !== this.frameSession) {
      this.counts.clear();
      this.flashes.clear();
      this.frameSession = s.session;
    }
    const now = performance.now();
    s.activity.ids.forEach((id, i) => {
      const count = s.activity.counts[i];
      if (count > (this.counts.get(id) ?? count)) this.flashes.set(id, now);
      this.counts.set(id, count);
    });
    const live = document.getElementById("neuron-live");
    if (live) {
      const i = s.activity.ids.indexOf([...this.selected][0]);
      live.textContent =
        i >= 0
          ? `V ${s.activity.v[i].toFixed(3)} · E ${s.activity.exc[i].toFixed(2)} · I ${s.activity.inh[i].toFixed(2)}`
          : t("Нейрон вне выборки телеметрии");
    }
  }
  private drawPreview(a: Point, b: Point) {
    const c = this.view.ctx,
      z = this.view.zoom;
    c.save();
    c.strokeStyle = "#f1d18a";
    c.fillStyle = "#f1d18a";
    c.lineWidth = 2 / z;
    c.setLineDash([8 / z, 5 / z]);
    c.beginPath();
    if (a.x === b.x && a.y === b.y) c.arc(a.x, a.y - 20, 20, 0, Math.PI * 2);
    else {
      c.moveTo(a.x, a.y);
      c.lineTo(b.x, b.y);
    }
    c.stroke();
    c.setLineDash([]);
    const angle = Math.atan2(b.y - a.y, b.x - a.x),
      x = b.x - Math.cos(angle) * 17,
      y = b.y - Math.sin(angle) * 17;
    c.beginPath();
    c.moveTo(x, y);
    c.lineTo(
      x - (Math.cos(angle - 0.5) * 10) / z,
      y - (Math.sin(angle - 0.5) * 10) / z,
    );
    c.lineTo(
      x - (Math.cos(angle + 0.5) * 10) / z,
      y - (Math.sin(angle + 0.5) * 10) / z,
    );
    c.closePath();
    c.fill();
    c.restore();
  }
  draw() {
    const v = this.view,
      c = v.ctx,
      net = this.api.project.topology;
    v.begin();
    v.grid();
    const now = performance.now();
    for (const f of net.groups) {
      const color =
        this.frameColor?.id === f.id ? this.frameColor.color : f.color;
      c.fillStyle = color;
      c.globalAlpha = 0.06;
      c.fillRect(f.x, f.y, f.w, f.h);
      c.globalAlpha = 1;
      c.strokeStyle = color;
      c.strokeRect(f.x, f.y, f.w, f.h);
      c.fillStyle = color;
      c.font = `${11 / v.zoom}px system-ui, sans-serif`;
      c.fillText(f.label, f.x + 10, f.y + 20 / v.zoom);
    }
    for (const g of net.ganglia) {
      c.beginPath();
      c.arc(g.x, g.y, g.radius, 0, Math.PI * 2);
      c.fillStyle = this.selectedGanglion === g.id ? "#c3d88913" : "#c3d88907";
      c.fill();
      c.strokeStyle = this.selectedGanglion === g.id ? "#d0e998" : "#657c5770";
      c.setLineDash([7 / v.zoom, 5 / v.zoom]);
      c.stroke();
      c.setLineDash([]);
      c.fillStyle = "#b9cda2";
      c.font = `${11 / v.zoom}px system-ui, sans-serif`;
      c.fillText(
        `${g.label} / ${g.members.length}`,
        g.x - g.radius * 0.65,
        g.y - g.radius - 12 / v.zoom,
      );
      const x = g.x + g.radius + 28;
      c.strokeStyle = "#aac27e";
      c.beginPath();
      c.moveTo(g.x + g.radius, g.y);
      c.lineTo(x, g.y);
      c.stroke();
      c.beginPath();
      c.moveTo(x, g.y - 10);
      c.lineTo(x + 10, g.y);
      c.lineTo(x, g.y + 10);
      c.lineTo(x - 10, g.y);
      c.closePath();
      c.fillStyle = "#354830";
      c.fill();
      c.stroke();
    }
    const edges = net.synapses;
    const stride = edges.length > 15000 ? Math.ceil(edges.length / 15000) : 1;
    for (let i = 0; i < edges.length; i += stride) {
      const s = edges[i],
        a = this.target(s.source),
        b = this.target(s.target);
      if (!a || !b) continue;
      if (!v.visible(a, 200) && !v.visible(b, 200)) continue;
      const active = now - (this.flashes.get(s.source) ?? -1000) < 170;
      const selected = s.id === this.selectedEdge;
      const color =
        s.kind === "mod_exc"
          ? "#bba8ed"
          : s.kind === "mod_inh"
            ? "#82bfd0"
            : s.weight < 0
              ? "#cf817c"
              : "#91ac73";
      c.strokeStyle = selected ? "#f0edc3" : color;
      c.globalAlpha = selected
        ? 1
        : active
          ? 0.8
          : net.synapses.length > 1500
            ? 0.13
            : 0.38;
      c.lineWidth = (selected ? 2 : 1) / v.zoom;
      c.setLineDash(s.kind === "direct" ? [] : [5 / v.zoom, 5 / v.zoom]);
      c.beginPath();
      c.moveTo(a.x, a.y);
      if (a === b) c.arc(a.x, a.y - 20, 18, 0.3, Math.PI * 2 - 0.3);
      else c.lineTo(b.x, b.y);
      c.stroke();
      c.setLineDash([]);
      if (v.zoom > 0.55 || selected) {
        const angle = Math.atan2(b.y - a.y, b.x - a.x),
          x = b.x - Math.cos(angle) * 17,
          y = b.y - Math.sin(angle) * 17;
        c.beginPath();
        c.moveTo(x, y);
        c.lineTo(
          x - (Math.cos(angle - 0.5) * 7) / v.zoom,
          y - (Math.sin(angle - 0.5) * 7) / v.zoom,
        );
        c.lineTo(
          x - (Math.cos(angle + 0.5) * 7) / v.zoom,
          y - (Math.sin(angle + 0.5) * 7) / v.zoom,
        );
        c.closePath();
        c.fillStyle = color;
        c.fill();
      }
    }
    c.globalAlpha = 1;
    c.lineWidth = 1.2 / v.zoom;
    for (const n of net.neurons) {
      if (!v.visible(n)) continue;
      const selected = this.selected.has(n.id);
      const active = now - (this.flashes.get(n.id) ?? -1000) < 140;
      const color = this.color(n);
      if (v.zoom < 0.05 && !selected && !active && n.kind === "inter") {
        c.fillStyle = color;
        c.fillRect(n.x, n.y, 1 / v.zoom, 1 / v.zoom);
        continue;
      }
      if (selected) circle(c, n.x, n.y, 19, "#d9eba219", "#e4f0be");
      if (active) circle(c, n.x, n.y, 22, "#d8edaa28");
      circle(
        c,
        n.x,
        n.y,
        n.kind === "inter" ? 9 : 12,
        active ? color : "#1b2924",
        color,
      );
      if (n.polarity === "inh") {
        c.strokeStyle = color;
        c.beginPath();
        c.moveTo(n.x - 4, n.y);
        c.lineTo(n.x + 4, n.y);
        c.stroke();
      } else if (n.kind === "motor") {
        circle(c, n.x, n.y, 4, color);
      } else if (n.kind === "sensor") {
        circle(c, n.x, n.y, 3, color);
      }
      if (v.zoom > 0.45 || selected || n.kind !== "inter") {
        c.fillStyle = selected ? "#eff3dc" : "#a8bba9";
        c.font = `${10 / v.zoom}px system-ui, sans-serif`;
        c.textAlign = "center";
        c.fillText(n.label, n.x, n.y + 24 / v.zoom);
        if (v.zoom > 0.75 && n.kind !== "inter") {
          const channels = Object.entries(this.api.project.bindings)
            .filter(([, id]) => id === n.id)
            .map(([k]) => k);
          if (channels.length) {
            c.font = `${8 / v.zoom}px ui-monospace`;
            c.fillStyle = "#748d82";
            c.fillText(channels.join(" · "), n.x, n.y + 37 / v.zoom);
          }
        }
        c.textAlign = "left";
      }
    }
    if (this.tool === "connect" && this.source) {
      const a = this.target(this.draft?.source ?? this.source);
      const b = this.draft ? this.target(this.draft.target) : this.cursor;
      if (a && b) {
        this.drawPreview(a, b);
        if (this.draft) circle(c, b.x, b.y, 19, "transparent", "#f1d18a");
      }
      document.getElementById("stage-hint")!.textContent = this.draft
        ? t(
            "Намечена связь: {0} → {1} · нажмите «Создать связь»",
            this.draft.source,
            this.draft.target,
          )
        : t("Выберите получателя связи");
      this.view.canvas.dataset.pendingTarget = this.draft?.target ?? "";
    } else this.view.canvas.dataset.pendingTarget = "";
    if (this.tool === "projection") {
      const a = this.groups.get(this.projectionSource ?? ""),
        b = this.groups.get(this.projectionTarget ?? "");
      if (a) circle(c, a.x, a.y, a.radius + 5, "transparent", "#f1d18a");
      if (b) circle(c, b.x, b.y, b.radius + 5, "transparent", "#f1d18a");
      if (a && (b || this.cursor)) this.drawPreview(a, b ?? this.cursor!);
    }
    if (this.source) {
      const n = this.target(this.source);
      if (n) circle(c, n.x, n.y, 23, "transparent", "#eee4ac");
    }
    if (this.drag && ["ganglion", "box", "frame"].includes(this.tool)) {
      const d = this.drag;
      c.strokeStyle = "#d6ed91";
      c.fillStyle = "#d6ed9112";
      if (this.tool === "ganglion") {
        c.beginPath();
        c.arc(
          d.start.x,
          d.start.y,
          Math.hypot(d.last.x - d.start.x, d.last.y - d.start.y),
          0,
          Math.PI * 2,
        );
        c.fill();
        c.stroke();
      } else {
        c.fillRect(
          d.start.x,
          d.start.y,
          d.last.x - d.start.x,
          d.last.y - d.start.y,
        );
        c.strokeRect(
          d.start.x,
          d.start.y,
          d.last.x - d.start.x,
          d.last.y - d.start.y,
        );
      }
    }
    // Draw handles above neurons and edges so every resize target stays visible.
    if (this.tool === "select") {
      const f = net.groups.find((f) => f.id === this.selectedFrame);
      if (f) {
        c.strokeStyle = "#d6ed91";
        c.setLineDash([4 / v.zoom, 4 / v.zoom]);
        c.strokeRect(
          f.x - 3 / v.zoom,
          f.y - 3 / v.zoom,
          f.w + 6 / v.zoom,
          f.h + 6 / v.zoom,
        );
        c.setLineDash([]);
        for (const [, x, y] of frameHandles)
          circle(
            c,
            f.x + x * f.w,
            f.y + y * f.h,
            4.5 / v.zoom,
            "#15221d",
            "#d6ed91",
          );
      }
    }
    document.getElementById("sampling")!.textContent =
      stride > 1
        ? t("Показана 1 из {0} связей", stride)
        : this.api.state?.activity.sampled
          ? t("Активность: первые 2 000 нейронов")
          : "";
  }
}
