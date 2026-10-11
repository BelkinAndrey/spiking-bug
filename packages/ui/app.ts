import "./style.css";
import { Connection, download, escape, handle, toast } from "./api";
import { Viewport } from "./canvas";
import { EditorView } from "./editor";
import { EnvironmentView } from "./environment";
import type { Mode } from "./types";

const logo = `<svg viewBox="0 0 32 36" fill="none" stroke="currentColor" stroke-width="1.4"><ellipse cx="16" cy="21" rx="7" ry="10"/><path d="M16 11v20M10 15 4 11M9 21H2M10 26 4 31M22 15l6-4M23 21h7M22 26l6 5M12 8l-3-5M20 8l3-5"/><circle cx="16" cy="9" r="4"/></svg>`;
export async function start(mode: Mode) {
  const isEnv = mode === "environment";
  const app = document.getElementById("app")!;
  app.innerHTML = `<header class="topbar"><a class="brand" href="/"><span class="logo">${logo}</span> SPIKING BUG</a><nav class="topnav" aria-label="Приложения"><a href="http://127.0.0.1:5173" class="${isEnv ? "active" : ""}" ${isEnv ? "" : 'target="_blank" rel="noopener"'}>Окружение <span class="subtle">&nbsp;01</span></a><a href="http://127.0.0.1:5174" class="${!isEnv ? "active" : ""}" ${!isEnv ? "" : 'target="_blank" rel="noopener"'}>Коннектом <span class="subtle">&nbsp;02</span></a></nav><div class="topright"><span class="projectname" id="projectname"></span><span class="status offline" id="connection">Подключение</span><button id="help" aria-label="Справка">?</button></div></header>
  <main class="workspace"><div class="heading"><div><div class="eyebrow">${isEnv ? "Embodied intelligence" : "Spiking neural architecture"} / Lab 01</div><h1>${isEnv ? "Живая среда" : "Редактор коннектома"}</h1><p>${isEnv ? "Создавайте мир. Наблюдайте, как нервная система управляет поведением." : "От отдельного импульса — к целой нервной системе."}</p></div><div class="heading-actions"><button id="import">↥ Импорт</button><button id="export">↧ Экспорт</button><button id="save">Сохранить</button></div></div>
  <div class="layout"><div class="main-column"><div class="stage"><canvas id="scene" tabindex="0" aria-label="${isEnv ? "Арена жука. Инструменты построения слева, настройки мира справа." : "Схема нейронной сети. Доступный список нейронов во вкладке Нейроны справа."}"></canvas><div class="stage-head"><strong>${isEnv ? "FIELD / 01" : "CONNECTOME / 01"}</strong><span id="scene-meta">${isEnv ? "2 400 × 1 600 units" : "LIF · Δt 10 ms"}</span></div><span class="stage-badge" id="run-badge">PAUSED</span><div class="tools" id="tools" aria-label="Инструменты"></div><div class="stage-foot"><div class="legend">${isEnv ? '<span style="--color:#d3e7a3">Жук</span><span style="--color:#c3dc83">Пища</span><span style="--color:#d77e68">Угроза</span>' : '<span style="--color:#84bcca">Сенсоры</span><span style="--color:#c5d995">Интернейроны</span><span style="--color:#e3ba7e">Моторы</span>'}</div><span id="stage-hint"></span><span class="warning" id="sampling"></span></div><div class="camera-tools"><button id="zoom-out" aria-label="Уменьшить масштаб">−</button><button id="fit" title="Вписать всё" aria-label="Вписать всё">⊡</button><button id="zoom-in" aria-label="Увеличить масштаб">＋</button></div></div>
  ${isEnv ? '<div class="metrics"><div class="metric"><label>ЗДОРОВЬЕ</label><strong id="health">100</strong><small>%</small><div class="bar"><i id="health-bar" style="width:100%"></i></div></div><div class="metric"><label>ПОТРЕБЛЕНО ПИЩИ</label><strong id="eaten">0</strong><small>порций</small><div class="bar"><i style="width:0"></i></div></div><div class="metric"><label>ГОЛОД / УСТАЛОСТЬ</label><strong id="hunger">0 / 0</strong><small>%</small><div class="bar"><i id="hunger-bar" style="width:0"></i></div></div></div>' : ""}
  <div class="chart-wrap"><div class="chart-head"><span>Активность</span><select id="chart-group" aria-label="Группа графика"><option value="all">Вся сеть</option></select><span class="value mono" id="rate">0.0 Hz / нейрон</span><button id="csv" style="min-height:24px;padding:2px 7px;font-size:10px" title="Экспорт измерений">CSV ↧</button></div><canvas id="chart" role="img" aria-label="Средняя частота спайков за последние 30 секунд моделируемого времени"></canvas></div>
  <div class="transport"><button class="primary" id="play">▶ Запустить</button><button id="step" title="Один такт 10 мс">▹ Такт</button><button id="reset" title="Сбросить активность сети и вернуть жука на старт">↺ Сброс</button><span class="label">Темп</span><select id="speed" aria-label="Темп симуляции"><option value="0.1">0.1×</option><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option><option value="5">5×</option></select><span class="time mono" id="time">00:00.00</span></div></div><aside class="sidebar" id="sidebar" aria-label="Настройки"></aside></div>
  <footer class="footer"><span id="stats">Ожидание сервера…</span><span id="performance"></span><span class="right" id="version">NUMPY / CPU &nbsp;·&nbsp; FIXED STEP 10 ms &nbsp;·&nbsp; v0.1</span></footer></main><div role="status" id="toast"></div><input class="file-input" id="file" type="file" accept=".json,application/json">`;
  const api = new Connection();
  const view = new Viewport(
    document.getElementById("scene") as HTMLCanvasElement,
    mode,
  );
  const panel = isEnv
    ? new EnvironmentView(api, view, document.getElementById("sidebar")!)
    : new EditorView(api, view, document.getElementById("sidebar")!);
  document.getElementById("tools")!.innerHTML = panel
    .toolbar()
    .map(
      ([tool, icon, title]) =>
        `<button data-tool="${tool}" title="${title}" aria-label="${title}">${icon}</button>`,
    )
    .join("");
  document
    .querySelectorAll<HTMLElement>("[data-tool]")
    .forEach((b) => (b.onclick = () => panel.setTool(b.dataset.tool!)));
  panel.setTool(isEnv ? "pan" : "select");
  document.getElementById("zoom-out")!.onclick = () => view.scale(0.8);
  document.getElementById("zoom-in")!.onclick = () => view.scale(1.25);
  document.getElementById("fit")!.onclick = () => panel.fit();
  document.getElementById("play")!.onclick = () =>
    handle(
      api.command(
        "control",
        { mode: api.state?.running ? "pause" : "play" },
        false,
      ),
    );
  document.getElementById("step")!.onclick = () =>
    handle(api.command("control", { mode: "step" }, false));
  document.getElementById("reset")!.onclick = () =>
    handle(api.command("control", { mode: "reset" }, false));
  document.getElementById("speed")!.onchange = (e) =>
    handle(
      api.command(
        "speed",
        { value: Number((e.target as HTMLSelectElement).value) },
        false,
      ),
    );
  document.getElementById("save")!.onclick = () =>
    handle(
      api.command("save").then(() => toast("Эксперимент сохранён на сервере")),
    );
  document.getElementById("export")!.onclick = () =>
    handle(
      fetch("/api/export")
        .then((r) => {
          if (!r.ok) throw new Error("Экспорт не выполнен");
          return r.text();
        })
        .then((s) => download("spiking-bug-experiment.json", s)),
    );
  document.getElementById("import")!.onclick = () =>
    document.getElementById("file")!.click();
  document.getElementById("file")!.onchange = (e) => {
    const el = e.target as HTMLInputElement,
      file = el.files?.[0];
    if (!file) return;
    handle(
      file
        .text()
        .then((s) => api.command("import", JSON.parse(s)))
        .then(() => {
          panel.fit();
          toast("Эксперимент импортирован; симуляция на паузе");
        }),
    );
    el.value = "";
  };
  document.getElementById("csv")!.onclick = () => {
    const rows = api.state?.history ?? [];
    const groups = ["all", ...api.project.topology.ganglia.map((g) => g.id)];
    download(
      "spike-rates.csv",
      "time_s," +
        groups.map((g) => "mean_hz_" + g).join(",") +
        "\n" +
        rows
          .map((r) => [r.t, ...groups.map((g) => r.rates[g] ?? "")].join(","))
          .join("\n"),
      "text/csv",
    );
  };
  document.getElementById("help")!.onclick = () => {
    const d = document.createElement("dialog");
    d.innerHTML = `<h2>Одна нервная система. Два окна.</h2><p>Окружение и коннектом подключены к одному серверу. Запуск, пауза, нейроны и назначения каналов общие. Эксперимент сохраняется после правок; «Сохранить» также фиксирует текущие объекты мира.</p><p>Потенциал интегрируется и утекает каждый такт, включая рефрактерный период. Этот период блокирует только спайк. По умолчанию потенциал после спайка сохраняется.</p><p>Прямые связи меняют потенциал. Модулирующие связи изменяют коэффициент чувствительности к возбуждению или торможению. Коэффициенты возвращаются к 1.</p><p>График: спайки за 100 мс / число нейронов / 0.1 с. Ось времени — время модели. Окно до 30 с; экспорт CSV содержит те же измерения.</p><p>Это исследовательский симулятор без автоматического обучения весов. Поведение задаётся построенной сетью.</p><button class="primary wide" id="close-help" style="margin-top:18px">Понятно</button>`;
    document.body.append(d);
    d.querySelector<HTMLElement>("#close-help")!.onclick = () => d.close();
    d.onclose = () => d.remove();
    d.showModal();
  };
  api.addEventListener("project", () => {
    panel.renderSide();
    document.getElementById("projectname")!.textContent = api.project.name;
    const select = document.getElementById("chart-group") as HTMLSelectElement,
      value = select.value;
    select.innerHTML =
      '<option value="all">Вся сеть</option>' +
      api.project.topology.ganglia
        .map(
          (g) => `<option value="${escape(g.id)}">${escape(g.label)}</option>`,
        )
        .join("");
    if ([...select.options].some((o) => o.value === value))
      select.value = value;
  });
  let lastError = "";
  api.addEventListener("state", () => {
    const s = api.state;
    if (!s) return;
    if (panel instanceof EditorView) panel.updateActivity();
    document.getElementById("play")!.textContent = s.running
      ? "Ⅱ Пауза"
      : "▶ Запустить";
    (document.getElementById("step") as HTMLButtonElement).disabled = s.running;
    document.getElementById("run-badge")!.textContent = s.running
      ? "RUNNING"
      : "PAUSED";
    document.getElementById("time")!.textContent = `${Math.floor(s.t / 60)
      .toString()
      .padStart(2, "0")}:${(s.t % 60).toFixed(2).padStart(5, "0")}`;
    (document.getElementById("speed") as HTMLSelectElement).value = String(
      s.speed,
    );
    document.getElementById("stats")!.textContent =
      `${s.stats.neurons.toLocaleString()} нейронов · ${s.stats.synapses.toLocaleString()} связей`;
    document.getElementById("performance")!.textContent =
      `${s.stats.step_ms.toFixed(2)} ms / такт · ${s.stats.memory_mb} MB${s.stats.overruns ? " · отставаний: " + s.stats.overruns : ""}`;
    if (isEnv) {
      const a = s.world.agent;
      document.getElementById("health")!.textContent = (a.health * 100).toFixed(
        0,
      );
      document.getElementById("health-bar")!.style.width = a.health * 100 + "%";
      document.getElementById("eaten")!.textContent = String(a.eaten);
      document.getElementById("hunger")!.textContent =
        `${(a.hunger * 100).toFixed(0)} / ${(a.fatigue * 100).toFixed(0)}`;
      document.getElementById("hunger-bar")!.style.width = a.hunger * 100 + "%";
      document.getElementById("scene-meta")!.textContent =
        `${s.world.config.width.toLocaleString()} × ${s.world.config.height.toLocaleString()} units`;
    }
    if (s.error && s.error !== lastError) {
      toast(s.error);
      lastError = s.error;
    }
    drawChart(api);
  });
  const motors: Record<string, boolean> = {};
  let motorTimer: ReturnType<typeof setInterval> | undefined;
  function sendMotors() {
    handle(api.command("manual", motors, false));
  }
  function stopMotors() {
    for (const k in motors) delete motors[k];
    clearInterval(motorTimer);
    motorTimer = undefined;
    if (api.project) sendMotors();
  }
  if (isEnv) {
    document.addEventListener("keydown", (e) => {
      if ((e.target as HTMLElement).closest("input,select,textarea,dialog"))
        return;
      const channel = (
        {
          KeyW: "forward",
          KeyS: "backward",
          KeyA: "left",
          KeyD: "right",
        } as Record<string, string>
      )[e.code];
      if (channel) {
        e.preventDefault();
        motors[channel] = true;
        if (!motorTimer) {
          sendMotors();
          motorTimer = setInterval(sendMotors, 120);
        }
      }
    });
    document.addEventListener("keyup", (e) => {
      const channel = (
        {
          KeyW: "forward",
          KeyS: "backward",
          KeyA: "left",
          KeyD: "right",
        } as Record<string, string>
      )[e.code];
      if (channel) {
        delete motors[channel];
        sendMotors();
        if (!Object.keys(motors).length) stopMotors();
      }
    });
    window.addEventListener("blur", stopMotors);
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stopMotors();
    });
  }
  document.getElementById("chart-group")!.onchange = () => drawChart(api);
  try {
    await api.init();
    requestAnimationFrame(() => {
      view.resize();
      if (!localStorage.getItem("spiking-bug.camera." + mode)) panel.fit();
    });
  } catch (e) {
    toast("Не удалось подключиться к серверу. Запустите ./run.sh");
    document.getElementById("sidebar")!.innerHTML =
      '<div class="section"><h2>Сервер недоступен</h2><p class="help">Запустите ./run.sh и перезагрузите страницу.</p><button onclick="location.reload()">Повторить</button></div>';
    return;
  }
  let lastDraw = 0;
  function frame(now: number) {
    if (!document.hidden && now - lastDraw > 32) {
      panel.draw();
      lastDraw = now;
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  setInterval(() => {
    const live = api.online && Date.now() - api.lastFrame < 2500;
    const el = document.getElementById("connection")!;
    el.textContent = live ? "Синхронизировано" : "Связь потеряна";
    el.classList.toggle("offline", !live);
    document.getElementById("run-badge")!.style.opacity = live ? "1" : ".4";
  }, 500);
}

function drawChart(api: Connection) {
  const canvas = document.getElementById("chart") as HTMLCanvasElement,
    c = canvas.getContext("2d")!,
    r = canvas.getBoundingClientRect(),
    dpr = Math.min(2, devicePixelRatio);
  canvas.width = r.width * dpr;
  canvas.height = r.height * dpr;
  c.scale(dpr, dpr);
  const w = r.width,
    h = r.height,
    key = (document.getElementById("chart-group") as HTMLSelectElement).value;
  const rows = api.state?.history ?? [],
    max = Math.max(1, ...rows.map((s) => s.rates[key] ?? 0)) * 1.1;
  const right = rows.at(-1)?.t ?? 0,
    left = Math.max(0, right - 30),
    span = Math.max(1, right - left);
  c.font = "9px ui-monospace";
  c.strokeStyle = "#304035";
  c.fillStyle = "#83998a";
  for (let i = 0; i < 3; i++) {
    const y = 12 + ((h - 30) * i) / 2;
    c.beginPath();
    c.moveTo(32, y);
    c.lineTo(w, y);
    c.stroke();
    c.fillText((max * (1 - i / 2)).toFixed(max < 10 ? 1 : 0), 0, y + 3);
  }
  c.fillText(left.toFixed(1) + " s", 32, h - 1);
  c.fillText(right.toFixed(1) + " s", Math.max(40, w - 45), h - 1);
  c.beginPath();
  rows.forEach((s, i) => {
    const x = 32 + ((w - 35) * (s.t - left)) / span,
      y = 12 + (h - 30) * (1 - (s.rates[key] ?? 0) / max);
    if (i === 0) c.moveTo(x, y);
    else c.lineTo(x, y);
  });
  c.strokeStyle = "#d0e797";
  c.lineWidth = 1.5;
  c.stroke();
  document.getElementById("rate")!.textContent = rows.length
    ? `${(rows.at(-1)?.rates[key] ?? 0).toFixed(1)} Hz / нейрон`
    : "Нет измерений";
}
