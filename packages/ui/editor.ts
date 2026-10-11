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
      this.drag = undefined;
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
  rebuild() {
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
    const xs = ns.map((n) => n.x),
      ys = ns.map((n) => n.y);
    this.view.fit(
      Math.min(...xs) - 70,
      Math.min(...ys) - 90,
      Math.max(...xs) - Math.min(...xs) + 200,
      Math.max(...ys) - Math.min(...ys) + 160,
    );
  }
  toolbar() {
    return [
      ["select", "↖", "Выбрать / переместить"],
      ["pan", "↔", "Панорама"],
      ["neuron", "⊕", "Создать нейрон"],
      ["connect", "↗", "Создать синапс"],
      ["ganglion", "◉", "Нарисовать ганглий"],
      ["projection", "⇢", "Связать ганглии"],
      ["box", "▣", "Выделить область"],
      ["frame", "▱", "Создать рамку"],
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
        select:
          "Перетаскивание — переместить · Shift — добавить к выбору · ⌘C / ⌘V",
        pan: "Перетаскивание — панорама · колесо — масштаб",
        neuron: "Щёлкните по полю, чтобы создать нейрон",
        connect: "Выберите источник, затем нейрон или коннектор ганглия",
        ganglion: "От центра потяните до края будущего ганглия",
        box: "Выделите прямоугольную область",
        frame: "Нарисуйте рамку вокруг функциональной группы",
        projection: "Выберите ганглий-источник, затем ганглий-получатель",
      } as Record<string, string>
    )[tool];
    if (tool === "projection") this.tab = "inspect";
    if (this.api.project) this.renderSide();
  }
  async commit(topology: Topology) {
    const previous = structuredClone(this.api.project.topology);
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
          .then(() => toast("Предыдущее изменение восстановлено")),
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
    toast(`Скопировано нейронов: ${this.clipboard.neurons.length}`);
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
    this.rebuild();
    this.side.innerHTML = `<div class="side-tabs">${[
      ["inspect", "Инспектор"],
      ["build", "Генератор"],
      ["list", "Нейроны"],
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
      if (this.nodes.has(this.draft.source) && this.target(this.draft.target)) {
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
      content.innerHTML = `<div class="section"><h3>Нервная система</h3><input id="neuron-search" class="search" placeholder="Поиск по ID или имени" aria-label="Поиск нейронов"><div class="list" id="neuron-list"></div><p class="help">Показаны первые 200 совпадений. Выбор нейрона открывает параметры и центрирует поле.</p></div>`;
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
      content.innerHTML = `<form id="frame-form" class="section"><h3>Визуальная рамка</h3><div class="fields">${input("label", "Название", frame.label, true)}${input("color", "Цвет", frame.color, true)}${field("x", "X", frame.x)}${field("y", "Y", frame.y)}${field("w", "Ширина", frame.w, "any", 1, 100000)}${field("h", "Высота", frame.h, "any", 1, 100000)}<label class="full">Комментарий<textarea name="comment">${escape(frame.comment)}</textarea></label></div><button class="primary wide">Сохранить рамку</button><button type="button" class="wide danger" id="delete-frame">Удалить только рамку</button><p class="help">Рамка — визуальная аннотация. Она не меняет связи и не создаёт коннектор.</p></form>`;
      onForm(content, "frame-form", (v) => {
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
      content.innerHTML = `<div class="section"><h3>Ганглий</h3><h2>${escape(g.label)}</h2><p class="mono subtle">${escape(g.id)}</p><div class="live-values">${g.members.length} нейронов · r = ${g.radius.toFixed(0)}</div><p class="help">Ромб справа — входной коннектор. Связь к нему доставляет один и тот же сигнал всем участникам ганглия. Коннектор сам не генерирует спайки.</p><button class="wide" id="select-members">Выделить все нейроны</button><button class="wide" id="rename-group">Переименовать</button><button class="wide danger" id="delete">Удалить ганглий и его нейроны</button></div>`;
      content.querySelector<HTMLElement>("#select-members")!.onclick = () => {
        this.selected = new Set(g.members);
        this.selectedGanglion = undefined;
        this.selectedFrame = undefined;
        this.renderSide();
      };
      content.querySelector<HTMLElement>("#rename-group")!.onclick = () => {
        const label = prompt("Название ганглия", g.label);
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
      content.innerHTML = `<form id="neuron-form"><div class="section"><div class="row spread"><h3>${this.selected.size > 1 ? `${this.selected.size} нейронов` : "Нейрон"}</h3><span class="pill">LIF</span></div><p class="mono small subtle">${escape(n.id)}</p><div class="live-values" id="neuron-live">V — · E — · I —</div><div class="fields">${this.selected.size === 1 ? input("label", "Название", n.label, true) : ""}${field("threshold", "Порог", n.threshold, 0.05, -10000, 10000)}${field("leak", "Утечка / такт", n.leak, 0.01, 0, 1)}${field("refractory", "Рефрактерность, такты", n.refractory, 1, 0, 10000)}${field("bias", "Постоянный ток", n.bias, 0.01, -100, 100)}${field("noise_std", "Шум · σ / такт", n.noise_std, 0.01, 0, 100)}${field("v_min", "Нижняя граница V", n.v_min, 0.1, -10000, 0)}${select("reset_mode", "После спайка", n.reset_mode, { retain: "Сохранить потенциал", reset: "Сбросить потенциал в 0" }, true)}${select("polarity", "Полярность исходящих связей", n.polarity, { mixed: "Любой знак", exc: "Только возбуждающие", inh: "Только тормозящие" }, true)}</div><p class="help">Утечка и входящие токи действуют постоянно. Рефрактерный период запрещает только спайк. 1 такт = 10 мс.</p></div><div class="section"><h3>Модуляция чувствительности</h3><div class="fields">${field("mod_tau_exc", "Возврат E · τ, с", n.mod_tau_exc, 0.1, 0.01, 3600)}${field("mod_tau_inh", "Возврат I · τ, с", n.mod_tau_inh, 0.1, 0.01, 3600)}${field("mod_gain_exc", "Отклик E", n.mod_gain_exc, 0.1, 0, 100)}${field("mod_gain_inh", "Отклик I", n.mod_gain_inh, 0.1, 0, 100)}</div><p class="help">E — возбуждение, I — торможение. Коэффициенты возвращаются к 1 экспоненциально и ограничены диапазоном 0…10.</p><button class="primary wide">Применить ${this.selected.size > 1 ? "ко всем выбранным" : "параметры"}</button></div></form><div class="section"><h3>Связь с окружением</h3>${bound.length ? bound.map(([c, id]) => `<p class="help">${labels[c]} → <span class="mono">${escape(id)}</span></p>`).join("") : '<p class="help">Не назначен ни одному каналу. Назначения доступны во вкладке «Нейроны» окружения.</p>'}<div class="button-row"><button id="inject">Импульс +2</button><button id="connect">Связать ↗</button></div><div class="button-row"><button id="copy">Копировать</button><button class="danger" id="delete">Удалить</button></div></div>`;
      const related = this.api.project.topology.synapses.filter(
        (s) => this.selected.has(s.source) || this.selected.has(s.target),
      );
      content.insertAdjacentHTML(
        "beforeend",
        `<div class="section"><h3>Связи · ${related.length}</h3><div class="list">${related
          .slice(0, 200)
          .map(
            (s) =>
              `<button data-edge="${escape(s.id)}"><span>${escape(s.source)} → ${escape(s.target)}<br><small>${s.kind} · w ${s.weight} · ${s.delay * 10} ms</small></span></button>`,
          )
          .join(
            "",
          )}</div>${related.length > 200 ? '<p class="help">Показаны первые 200 связей выбранных нейронов.</p>' : ""}</div>`,
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
            .then(() => toast("Импульс подан на следующий такт")),
        );
      content.querySelector<HTMLElement>("#connect")!.onclick = () => {
        this.setTool("connect");
        this.source = n.id;
        toast("Выберите нейрон-получатель или коннектор");
      };
      content.querySelector<HTMLElement>("#copy")!.onclick = () => this.copy();
      content.querySelector<HTMLElement>("#delete")!.onclick = () =>
        this.remove();
      return;
    }
    content.innerHTML = `<div class="section"><h3>Инспектор</h3><p class="empty">Выберите нейрон, синапс или ганглий, чтобы увидеть параметры.</p><div class="button-row"><button id="new-neuron">＋ Нейрон</button><button id="new-ganglion">◉ Ганглий</button></div></div><div class="section"><h3>Три вида связей</h3><p class="help"><span style="color:#bad881">━━</span> Прямая: положительный вес возбуждает, отрицательный тормозит.</p><p class="help"><span style="color:#bba8ed">┄┄</span> Модуляция E: изменяет чувствительность к возбуждению.</p><p class="help"><span style="color:#82bfd0">┄┄</span> Модуляция I: изменяет чувствительность к торможению.</p></div><div class="section"><h3>Быстрые действия</h3><p class="help">⌘ / Ctrl + C, V — копировать и вставить<br>⌘ / Ctrl + Z — отменить изменение сети<br>Delete — удалить выбранное<br>Shift + щелчок — множественный выбор<br>Средняя кнопка — панорама<br>Колесо — масштаб под курсором</p><button class="wide" id="undo">Отменить изменение сети</button></div>`;
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
    content.innerHTML = `<form id="ganglion-form"><div class="section"><h3>Создать ганглий</h3><div class="fields">${input("label", "Название", "Ganglion", true)}${field("count", "Число нейронов", 40, 1, 1, 2000)}${field("radius", "Радиус области", Math.round(radius), 1, 30, 5000)}${field("x", "Центр X", Math.round(p.x))}${field("y", "Центр Y", Math.round(p.y))}${field("density", "Вероятность связи", 0.08, 0.01, 0, 1)}${field("max_distance", "Макс. расстояние · 0 = без лимита", 0, "any", 0, 300000)}${field("excitatory", "Доля возбуждающих", 0.8, 0.05, 0, 1)}${select("mode", "Как распределить знаки", "neurons", { neurons: "Возбуждающие / тормозящие нейроны", synapses: "Случайный знак каждой связи" }, true)}${field("weight", "Модуль веса", 0.5, 0.05, 0, 100)}${field("delay", "Задержка, такты", 2, 1, 1, 256)}${field("seed", "Seed генерации", 42, 1, 0, 2147483647)}</div><p class="help">Нейроны равномерно распределены по площади круга. Плотность — вероятность связи среди пар в пределах максимального расстояния; самосвязи исключены. 0 — без ограничения дальности.</p></div><div class="section"><h3>Параметры новых нейронов</h3><div class="fields">${field("threshold", "Порог", 1, 0.05, 0.001, 10000)}${field("leak", "Утечка / такт", 0.08, 0.01, 0, 1)}${field("refractory", "Рефрактерность", 2, 1, 0, 10000)}${field("bias", "Постоянный ток", 0, 0.01, -100, 100)}${select("reset_mode", "После спайка", "retain", { retain: "Сохранить потенциал", reset: "Сбросить в 0" }, true)}</div><button class="primary wide">Сгенерировать ганглий</button><p class="help">Коннектор справа от круга передаёт любой выбранный тип воздействия всем нейронам внутри.</p></div></form>`;
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
            toast("Ганглий создан");
          }),
      );
    });
  }
  synapseForm(content: HTMLElement, s: Synapse, isNew = false) {
    if (isNew) this.draft = s;
    content.innerHTML = `<form id="synapse-form" class="section"><h3>${isNew ? "Новая связь" : "Синапс"}</h3><div class="fields">${select("source", "От нейрона", s.source, Object.fromEntries([...this.nodes].map(([id, n]) => [id, `${n.label} · ${id}`])), true)}${select("target", "К нейрону / ганглию", s.target, { ...Object.fromEntries([...this.nodes].map(([id, n]) => [id, `${n.label} · ${id}`])), ...Object.fromEntries([...this.groups].map(([id, g]) => [id, `◉ ${g.label} · все ${g.members.length}`])) }, true)}${select("kind", "Действие", s.kind, { direct: "Прямое воздействие", mod_exc: "Модуляция возбуждения · E", mod_inh: "Модуляция торможения · I" }, true)}${field("weight", "Вес со знаком", s.weight, 0.05, -10000, 10000)}${field("delay", "Задержка, такты", s.delay, 1, 1, 256)}</div><p class="help">Для модулирующей связи + увеличивает чувствительность, − уменьшает. Мембранный потенциал напрямую не меняется.</p><button class="primary wide">${isNew ? "Создать связь" : "Сохранить связь"}</button>${!isNew ? '<button type="button" class="wide danger" id="delete-edge">Удалить связь</button>' : ""}</form>`;
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
      "": "Выберите ганглий",
      ...Object.fromEntries(
        [...this.groups.values()].map((g) => [
          g.id,
          `${g.label} · ${g.members.length} нейронов`,
        ]),
      ),
    };
    content.innerHTML = `<form id="projection-form" class="section"><h3>Связи между ганглиями</h3><div class="fields">${select("source", "Источник", this.projectionSource ?? "", options, true)}${select("target", "Получатель", this.projectionTarget ?? "", options, true)}${select("kind", "Тип связей", "direct", { direct: "Прямые · знак по полярности", mod_exc: "Модуляция возбуждения · E", mod_inh: "Модуляция торможения · I" }, true)}${field("density", "Вероятность связи", 0.1, "any", 0, 1)}${field("weight", "Вес", 0.5, "any", -10000, 10000)}${field("delay", "Задержка, такты", 1, 1, 1, 256)}${field("seed", "Seed", 42, 1, 0, 2147483647)}${field("max_distance", "Макс. расстояние · 0 = без лимита", 0, "any", 0, 300000)}</div><p class="help">Связи направлены от нейронов первого ганглия к нейронам второго. Для прямых связей знак определяется полярностью источника, для mixed — знаком веса. Модуляция использует указанный знак. Существующие пары того же типа пропускаются.</p><button class="primary wide" ${this.groups.size < 2 ? "disabled" : ""}>Сгенерировать связи</button><p class="help">Выберите два круга на поле или укажите их здесь. ${this.groups.size < 2 ? "Сначала создайте минимум два ганглия." : ""}</p></form>`;
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
            toast(`Создано связей: ${result.added_synapses}`);
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
      const a = this.nodes.get(s.source),
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
        else toast("Выберите другой ганглий");
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
        if (hit) {
          this.source = hit.id;
          toast(`Источник: ${hit.label}. Выберите получателя.`);
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
            const f = [...this.api.project.topology.groups]
              .reverse()
              .find(
                (f) =>
                  p.x >= f.x &&
                  p.x <= f.x + f.w &&
                  p.y >= f.y &&
                  p.y <= f.y + f.h &&
                  (p.y - f.y < 28 / this.view.zoom ||
                    f.y + f.h - p.y < 10 / this.view.zoom ||
                    p.x - f.x < 10 / this.view.zoom ||
                    f.x + f.w - p.x < 10 / this.view.zoom),
              );
            if (f) this.selectedFrame = f.id;
            else this.drag.pan = true;
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
    if (!this.drag) return;
    const d = this.drag;
    d.moved = true;
    if (d.pan) {
      this.view.x += e.movementX;
      this.view.y += e.movementY;
      return;
    }
    d.last = this.view.point(e);
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
          : "Нейрон вне выборки телеметрии";
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
      c.fillStyle = "#69827b08";
      c.fillRect(f.x, f.y, f.w, f.h);
      c.strokeStyle = this.selectedFrame === f.id ? "#d6ed91" : f.color;
      c.strokeRect(f.x, f.y, f.w, f.h);
      c.fillStyle = "#90a496";
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
        a = this.nodes.get(s.source),
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
      const a = this.nodes.get(this.draft?.source ?? this.source);
      const b = this.draft ? this.target(this.draft.target) : this.cursor;
      if (a && b) {
        this.drawPreview(a, b);
        if (this.draft) circle(c, b.x, b.y, 19, "transparent", "#f1d18a");
      }
      document.getElementById("stage-hint")!.textContent = this.draft
        ? `Намечена связь: ${this.draft.source} → ${this.draft.target} · нажмите «Создать связь»`
        : "Выберите получателя связи";
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
      const n = this.nodes.get(this.source);
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
    document.getElementById("sampling")!.textContent =
      stride > 1
        ? `Показана 1 из ${stride} связей`
        : this.api.state?.activity.sampled
          ? "Активность: первые 2 000 нейронов"
          : "";
  }
}
