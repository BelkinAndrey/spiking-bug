import { Connection, escape, handle, toast } from "./api";
import { Viewport, circle, type Point } from "./canvas";
import { field, select, onForm } from "./forms";
import { labels, type WorldObject } from "./types";

export class EnvironmentView {
  tool = "pan";
  tab = "world";
  sensors = true;
  follow = false;
  selected?: string;
  private drag?: { start: Point; last: Point; screen: Point };
  constructor(
    public api: Connection,
    public view: Viewport,
    public side: HTMLElement,
  ) {
    view.canvas.addEventListener("pointerdown", (e) => this.down(e));
    view.canvas.addEventListener("pointermove", (e) => this.move(e));
    view.canvas.addEventListener("pointerup", (e) => this.up(e));
    view.canvas.addEventListener("pointercancel", () => {
      this.drag = undefined;
    });
  }
  fit() {
    const c = this.api.project.world.config;
    this.view.fit(0, 0, c.width, c.height);
  }
  toolbar() {
    return [
      ["pan", "↔", "Панорама"],
      ["food", "●", "Добавить пищу"],
      ["obstacle", "▧", "Нарисовать препятствие"],
      ["threat", "◈", "Добавить угрозу"],
      ["zone", "▦", "Зона появления пищи"],
      ["spawn", "⌖", "Переместить жука"],
      ["erase", "⌫", "Удалить объект"],
    ];
  }
  setTool(tool: string) {
    this.tool = tool;
    this.view.canvas.style.cursor = tool === "pan" ? "grab" : "crosshair";
    document
      .querySelectorAll("[data-tool]")
      .forEach((b) =>
        b.classList.toggle("active", (b as HTMLElement).dataset.tool === tool),
      );
    document.getElementById("stage-hint")!.textContent = (
      {
        pan: "Перетаскивание — панорама · колесо — масштаб",
        food: "Щёлкните по арене, чтобы добавить пищу",
        obstacle: "Потяните по диагонали, чтобы построить стену",
        threat: "Щёлкните по арене, чтобы добавить угрозу",
        zone: "Нарисуйте прямоугольную область появления пищи",
        spawn: "Щёлкните в свободном месте для переноса жука",
        erase: "Щёлкните по объекту, чтобы удалить его",
      } as Record<string, string>
    )[tool];
  }
  renderSide() {
    const p = this.api.project,
      c = p.world.config;
    this.side.innerHTML = `<div class="side-tabs">${[
      ["world", "Мир"],
      ["agent", "Жук"],
      ["bridge", "Нейроны"],
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
          this.renderSide();
        }),
    );
    const content = this.side.querySelector<HTMLElement>("#side-content")!;
    if (this.tab === "world") {
      content.innerHTML = `<form id="world-form"><div class="section"><div class="row spread"><h3>Арена</h3><span class="pill">2D · BUG</span></div><div class="fields">${field("width", "Ширина", c.width, 100, 400, 12000)}${field("height", "Высота", c.height, 100, 400, 12000)}${field("seed", "Seed мира", c.seed, 1, 0, 2147483647)}</div></div>
      <div class="section"><h3>Пища</h3><div class="fields">${field("food_target", "Целевое количество", c.food_target, 1, 0, 500)}${field("food_interval", "Интервал появления, с", c.food_interval, 0.1, 0.01, 60)}</div><p class="help">Новые порции появляются до целевого количества. Инструмент ▦ ограничивает появление выбранными зонами.</p></div>
      <div class="section"><h3>Угрозы</h3><div class="fields">${select("threat_mode", "Поведение", c.threat_mode, { pursuit: "Преследование", static: "Статичные" }, true)}${field("threat_target", "Количество", c.threat_target, 1, 0, 100)}${field("threat_radius", "Радиус обзора", c.threat_radius, 10, 20, 2000)}${field("threat_speed_ratio", "Скорость / скорость жука", c.threat_speed_ratio, 0.01, 0.05, 0.95)}${field("chase_duration", "Интерес, с", c.chase_duration, 0.5, 0.1, 120)}${field("cooldown", "Отдых после погони, с", c.cooldown, 0.5, 0.1, 120)}${field("threat_lifetime", "Время жизни, с", c.threat_lifetime, 1, 1, 3600)}</div><p class="help">Угроза видит жука в пределах радиуса, если между ними нет стены. Теряет интерес при потере видимости или по таймеру.</p><button class="primary wide" type="submit">Применить настройки</button></div></form>
      <form id="maze-form" class="section"><h3>Генератор лабиринта</h3><div class="fields">${field("cols", "Столбцы", 12, 1, 2, 40)}${field("rows", "Строки", 8, 1, 2, 40)}${field("seed", "Seed лабиринта", 42, 1, 0, 2147483647)}</div><p class="help">Создаёт связный лабиринт и переносит жука ко входу. Заменяет текущие объекты и зоны.</p><button class="wide">Сгенерировать лабиринт</button><button type="button" class="wide" id="clear-walls">Убрать все стены</button></form>
      <div class="section"><h3>Сценарий мира</h3><p class="help">JSON-описание объектов и зон; можно создать своим скриптом и импортировать целый эксперимент.</p><button id="scenario" class="wide">Редактировать JSON мира</button></div>`;
      onForm(content, "world-form", (v) =>
        handle(
          this.api
            .command("world_config", v)
            .then(() => toast("Настройки мира сохранены")),
        ),
      );
      onForm(content, "maze-form", (v) =>
        handle(
          this.api.command("maze", v).then(() => {
            this.fit();
            toast("Лабиринт создан");
          }),
        ),
      );
      content.querySelector<HTMLElement>("#clear-walls")!.onclick = () =>
        handle(this.api.command("clear", { kind: "obstacle" }));
      content.querySelector<HTMLElement>("#scenario")!.onclick = () =>
        this.scenario();
    } else if (this.tab === "agent") {
      content.innerHTML = `<div class="section"><h3>Наблюдение</h3><label class="row"><input type="checkbox" id="show-sensors" ${this.sensors ? "checked" : ""}> Показывать сенсоры и обзор угроз</label><div class="spacer"></div><label class="row"><input type="checkbox" id="follow" ${this.follow ? "checked" : ""}> Следовать за жуком</label><p class="help">W / A / S / D подают ток на назначенные моторные нейроны, пока клавиши удерживаются.</p><div class="button-row"><button data-motor="left">↶ A</button><button data-motor="forward">↑ W</button><button data-motor="right">D ↷</button><button data-motor="backward">↓ S</button></div></div>
      <form id="agent-form" class="section"><h3>Тело и восприятие</h3><div class="fields">${field("speed", "Скорость движения", c.speed, 10, 10, 400)}${field("turn_speed", "Поворот, рад/с", c.turn_speed, 0.1, 0.1, 10)}${field("sensor_range", "Дальность сенсоров", c.sensor_range, 10, 20, 2000)}${field("lidar_range", "Дальность лидара", c.lidar_range, 10, 20, 2000)}${field("hunger_rate", "Рост голода / с", c.hunger_rate, 0.001, 0, 1)}${field("fatigue_gain", "Усталость / спайк", c.fatigue_gain, 0.001, 0, 1)}${field("fatigue_decay", "Восстановление / с", c.fatigue_decay, 0.01, 0, 1)}</div><button class="primary wide">Применить параметры</button></form><div class="section"><h3>Сенсорные токи · 0…1</h3><div id="sensor-values" class="spark-table"></div></div>`;
      content.querySelector<HTMLInputElement>("#show-sensors")!.onchange = (
        e,
      ) => (this.sensors = (e.target as HTMLInputElement).checked);
      content.querySelector<HTMLInputElement>("#follow")!.onchange = (e) =>
        (this.follow = (e.target as HTMLInputElement).checked);
      onForm(content, "agent-form", (v) =>
        handle(this.api.command("world_config", v)),
      );
      content.querySelectorAll<HTMLElement>("[data-motor]").forEach((b) => {
        let timer: ReturnType<typeof setInterval> | undefined;
        const stop = () => {
          clearInterval(timer);
          handle(this.api.command("manual", {}, false));
        };
        b.onpointerdown = (e) => {
          b.setPointerCapture(e.pointerId);
          const send = () =>
            handle(
              this.api.command("manual", { [b.dataset.motor!]: true }, false),
            );
          send();
          timer = setInterval(send, 120);
        };
        b.onpointerup = stop;
        b.onpointercancel = stop;
        b.onlostpointercapture = stop;
      });
    } else {
      content.innerHTML = `<form id="bindings-form" class="section"><h3>Мост окружение ↔ сеть</h3><p class="help" style="margin-bottom:16px">Выберите ID нейрона для каждого канала. Назначения общие для обоих интерфейсов. Один нейрон может получать несколько сенсорных токов.</p>${Object.entries(
        labels,
      )
        .map(
          ([id, label]) =>
            `<div class="binding"><label for="b-${id}">${label}</label><select id="b-${id}" name="${id}"><option value="">Не назначен</option>${p.topology.neurons.map((n) => `<option value="${escape(n.id)}" ${p.bindings[id] === n.id ? "selected" : ""}>${escape(n.id)}</option>`).join("")}</select></div>`,
        )
        .join(
          "",
        )}<button class="primary wide">Сохранить назначения</button></form>`;
      onForm(content, "bindings-form", (v) =>
        handle(
          this.api
            .command("bindings", v)
            .then(() => toast("Назначения обновлены в обоих клиентах")),
        ),
      );
    }
  }
  scenario() {
    const d = document.createElement("dialog");
    d.innerHTML = `<h2>Сценарий мира</h2><p>Объекты, зоны, точка старта и настройки. Применение остановит и перезапустит эксперимент.</p><textarea aria-label="JSON мира"></textarea><div class="button-row"><button id="cancel">Отмена</button><button id="apply" class="primary">Применить</button></div>`;
    document.body.append(d);
    d.querySelector("textarea")!.value = JSON.stringify(
      this.api.project.world,
      null,
      2,
    );
    d.querySelector<HTMLElement>("#cancel")!.onclick = () => d.close();
    d.querySelector<HTMLElement>("#apply")!.onclick = () => {
      try {
        const world = JSON.parse(d.querySelector("textarea")!.value);
        handle(
          this.api
            .command("import", { ...this.api.project, world })
            .then(() => {
              d.close();
              this.fit();
            }),
        );
      } catch (e) {
        toast((e as Error).message);
      }
    };
    d.onclose = () => d.remove();
    d.showModal();
  }
  down(e: PointerEvent) {
    if (e.button !== 0 && e.button !== 1) return;
    this.view.canvas.setPointerCapture(e.pointerId);
    const p = this.view.point(e);
    this.drag = { start: p, last: p, screen: { x: e.clientX, y: e.clientY } };
    if (e.button === 1 || e.shiftKey) this.drag.screen.x = NaN;
  }
  move(e: PointerEvent) {
    if (!this.drag) return;
    const d = this.drag;
    const pan = this.tool === "pan" || Number.isNaN(d.screen.x);
    if (pan) {
      this.follow = false;
      this.view.x += e.movementX;
      this.view.y += e.movementY;
    } else d.last = this.view.point(e);
  }
  up(e: PointerEvent) {
    if (!this.drag) return;
    const d = this.drag;
    this.drag = undefined;
    if (this.tool === "pan" || Number.isNaN(d.screen.x)) {
      this.view.save();
      return;
    }
    const p = this.view.point(e);
    const bounds = {
      x: Math.min(d.start.x, p.x),
      y: Math.min(d.start.y, p.y),
      w: Math.abs(p.x - d.start.x),
      h: Math.abs(p.y - d.start.y),
    };
    if (this.tool === "obstacle" || this.tool === "zone") {
      if (bounds.w < 4 || bounds.h < 4) return;
      handle(
        this.api.command(this.tool === "zone" ? "zone" : "place", {
          ...bounds,
          kind: "obstacle",
        }),
      );
    } else if (this.tool === "spawn") handle(this.api.command("spawn", p));
    else if (this.tool === "erase") {
      const w = this.api.state?.world;
      const hit = [...(w?.objects ?? []), ...(w?.zones ?? [])]
        .reverse()
        .find((o) =>
          "w" in o && o.w && o.h
            ? p.x >= o.x && p.x <= o.x + o.w && p.y >= o.y && p.y <= o.y + o.h
            : Math.hypot(p.x - o.x, p.y - o.y) < 22,
        );
      if (hit) handle(this.api.command("remove", { id: hit.id }));
    } else handle(this.api.command("place", { kind: this.tool, ...p }));
  }
  draw() {
    const state = this.api.state;
    if (!state) return;
    const w = state.world,
      c = this.view.ctx,
      v = this.view,
      agent = w.agent,
      config = w.config;
    if (this.follow) {
      v.x = v.width / 2 - agent.x * v.zoom;
      v.y = v.height / 2 - agent.y * v.zoom;
    }
    v.begin();
    v.grid();
    c.fillStyle = "#172621";
    c.fillRect(0, 0, config.width, config.height);
    c.strokeStyle = "#3d5443";
    c.lineWidth = 2 / v.zoom;
    c.strokeRect(0, 0, config.width, config.height);
    c.strokeStyle = "#20382b";
    c.lineWidth = 1 / v.zoom;
    for (let x = 100; x < config.width; x += 100) {
      c.beginPath();
      c.moveTo(x, 0);
      c.lineTo(x, config.height);
      c.stroke();
    }
    for (let y = 100; y < config.height; y += 100) {
      c.beginPath();
      c.moveTo(0, y);
      c.lineTo(config.width, y);
      c.stroke();
    }
    for (const z of w.zones) {
      c.fillStyle = "#b7d7800c";
      c.fillRect(z.x, z.y, z.w, z.h);
      c.setLineDash([8 / v.zoom, 7 / v.zoom]);
      c.strokeStyle = "#b7d78065";
      c.strokeRect(z.x, z.y, z.w, z.h);
      c.setLineDash([]);
      c.fillStyle = "#9bad7a";
      c.font = `${10 / v.zoom}px ui-monospace`;
      c.fillText("FOOD ZONE", z.x + 8 / v.zoom, z.y + 17 / v.zoom);
    }
    for (const o of w.objects) {
      if (o.kind === "obstacle") {
        c.fillStyle = "#394740";
        c.fillRect(o.x, o.y, o.w!, o.h!);
        c.strokeStyle = "#607467";
        c.strokeRect(o.x, o.y, o.w!, o.h!);
      } else if (o.kind === "food") {
        if (!v.visible(o)) continue;
        circle(c, o.x, o.y, 7, "#c3dc83");
        circle(c, o.x - 1.5, o.y - 1.5, 2, "#e6f7b6");
      } else this.threat(c, o, config.threat_radius);
    }
    if (this.sensors) {
      c.save();
      c.translate(agent.x, agent.y);
      c.rotate(agent.heading);
      for (const [a, b] of [
        [(-Math.PI * 2) / 3, 0.035],
        [-0.035, (Math.PI * 2) / 3],
      ]) {
        c.beginPath();
        c.moveTo(0, 0);
        c.arc(0, 0, Math.min(config.sensor_range, 180), a, b);
        c.closePath();
        c.fillStyle = "#d2e98907";
        c.fill();
        c.strokeStyle = "#c9e58618";
        c.stroke();
      }
      for (let i = 0; i < 5; i++) {
        const a = (((i - 2) * Math.PI) / 180) * 25,
          d = w.lidar[i];
        c.beginPath();
        c.moveTo(0, 0);
        c.lineTo(Math.cos(a) * d, Math.sin(a) * d);
        c.strokeStyle = "#8bc9d485";
        c.lineWidth = 1 / v.zoom;
        c.stroke();
        circle(c, Math.cos(a) * d, Math.sin(a) * d, 2.5 / v.zoom, "#87bdc5");
      }
      c.restore();
    }
    c.save();
    c.translate(agent.x, agent.y);
    c.rotate(agent.heading);
    c.strokeStyle = "#c9d7b2";
    c.lineWidth = 2 / v.zoom;
    for (const sign of [-1, 1])
      for (let i = 0; i < 3; i++) {
        c.beginPath();
        c.moveTo((i - 1) * 7, sign * 7);
        c.lineTo((i - 1) * 13 - 4, sign * 17);
        c.lineTo((i - 1) * 16 - 8, sign * 21);
        c.stroke();
      }
    c.beginPath();
    c.ellipse(-3, 0, 15, 10, 0, 0, Math.PI * 2);
    c.fillStyle = agent.health > 0 ? "#d5e6ad" : "#887269";
    c.fill();
    c.strokeStyle = "#7e9b64";
    c.stroke();
    c.beginPath();
    c.moveTo(-15, 0);
    c.lineTo(7, 0);
    c.stroke();
    circle(c, 12, 0, 6, "#a6c185");
    for (const sign of [-1, 1]) {
      c.beginPath();
      c.moveTo(14, sign * 3);
      c.lineTo(25, sign * 11);
      c.stroke();
    }
    c.restore();
    const screen = v.screen(agent);
    c.save();
    c.setTransform(
      Math.min(2, devicePixelRatio),
      0,
      0,
      Math.min(2, devicePixelRatio),
      0,
      0,
    );
    c.fillStyle = "#c5d2bc";
    c.font = "10px ui-monospace";
    c.fillText("BUG / 01", screen.x + 20, screen.y - 17);
    c.restore();
    if (this.drag && ["obstacle", "zone"].includes(this.tool)) {
      const d = this.drag;
      c.fillStyle = "#d2ea9025";
      c.strokeStyle = "#d2ea90";
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
    const sensors = document.getElementById("sensor-values");
    if (sensors)
      sensors.innerHTML = Object.entries(w.sensors)
        .map(
          ([k, val]) =>
            `<span>${labels[k]}</span><span class="mono">${val.toFixed(3)}</span>`,
        )
        .join("");
  }
  threat(c: CanvasRenderingContext2D, o: WorldObject, r: number) {
    if (this.sensors) {
      c.beginPath();
      c.arc(o.x, o.y, r, 0, Math.PI * 2);
      c.fillStyle = o.state === "chasing" ? "#e9837311" : "#e9837305";
      c.fill();
      c.setLineDash([5 / this.view.zoom, 7 / this.view.zoom]);
      c.strokeStyle = "#dd87732a";
      c.stroke();
      c.setLineDash([]);
    }
    circle(
      c,
      o.x,
      o.y,
      16,
      o.state === "chasing" ? "#d77e68" : "#9a6657",
      "#ecac91",
    );
    c.strokeStyle = "#f4c9b3";
    c.beginPath();
    c.moveTo(o.x - 5, o.y - 5);
    c.lineTo(o.x + 5, o.y + 5);
    c.moveTo(o.x + 5, o.y - 5);
    c.lineTo(o.x - 5, o.y + 5);
    c.stroke();
    if (this.view.zoom > 0.35) {
      c.fillStyle = "#c58c78";
      c.font = `${9 / this.view.zoom}px ui-monospace`;
      c.fillText(
        o.mode === "static"
          ? "STATIC"
          : o.state === "chasing"
            ? "CHASE"
            : o.state === "rest"
              ? "REST"
              : "IDLE",
        o.x + 22,
        o.y + 3,
      );
    }
  }
}
