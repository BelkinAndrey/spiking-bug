import {
  t,
  language,
  locale,
  changeLanguage,
  languageLink,
  translateServerMessage,
} from "./i18n";
import "./style.css";
import { Connection, download, escape, handle, toast } from "./api";
import { Viewport } from "./canvas";
import { EditorView } from "./editor";
import { EnvironmentView } from "./environment";
import { openTrials } from "./trials";
import { openEvolution } from "./evolution";
import {
  actionButton,
  updateAction,
  installActionTooltips,
} from "./action-icons";
import type { Mode, ComputeDevices } from "./types";

const logo = `<svg viewBox="0 0 32 36" fill="none" stroke="currentColor" stroke-width="1.4"><ellipse cx="16" cy="21" rx="7" ry="10"/><path d="M16 11v20M10 15 4 11M9 21H2M10 26 4 31M22 15l6-4M23 21h7M22 26l6 5M12 8l-3-5M20 8l3-5"/><circle cx="16" cy="9" r="4"/></svg>`;
export async function start(mode: Mode) {
  const isEnv = mode === "environment";
  document.title = `Spiking Bug · ${isEnv ? t("Окружение") : t("Коннектом")}`;
  const app = document.getElementById("app")!;
  app.innerHTML = `<header class="topbar"><a class="brand" href="/"><span class="logo">${logo}</span> SPIKING BUG</a><nav class="topnav" aria-label="${t("Приложения")}"><a href="${languageLink("http://127.0.0.1:5173")}" class="${isEnv ? "active" : ""}" ${isEnv ? "" : 'target="_blank" rel="noopener"'}>${t("Окружение")} <span class="subtle">&nbsp;01</span></a><a href="${languageLink("http://127.0.0.1:5174")}" class="${!isEnv ? "active" : ""}" ${!isEnv ? "" : 'target="_blank" rel="noopener"'}>${t("Коннектом")} <span class="subtle">&nbsp;02</span></a></nav><div class="topright"><span class="projectname" id="projectname"></span><span class="status offline" id="connection">${t("Подключение")}</span><select id="language" class="language-select" aria-label="${t("Язык")}" title="${t("Язык")}"><option value="en" lang="en">ENG</option><option value="ru" lang="ru">RU</option></select>${actionButton("help", "help", t("Справка"))}</div></header>
  <main class="workspace"><div class="heading"><div><div class="eyebrow">${isEnv ? t("Интеллект в среде") : t("Импульсная нейронная архитектура")} / ${t("Лаборатория 01")}</div><h1>${isEnv ? t("Живая среда") : t("Редактор коннектома")}</h1><p>${isEnv ? t("Создавайте мир. Наблюдайте, как нервная система управляет поведением.") : t("От отдельного импульса — к целой нервной системе.")}</p></div><div class="heading-actions">${!isEnv ? actionButton("new-document", "new", t("Новый документ")) + actionButton("arrange-graph", "layout", t("Разложить граф"), t("Рецепторы слева, моторы справа; остальные нейроны размещаются по связям. Можно отменить через Ctrl / ⌘ + Z."), "disabled") : ""}${actionButton("evolution", "evolution", t("Эволюция"))}${actionButton("trials", "trials", t("Испытание"))}${actionButton("import", "import", t("Импорт"))}${actionButton("export", "export", t("Экспорт"))}${actionButton("save", "save", t("Сохранить"))}${actionButton("toggle-chart", "chartOff", t("Скрыть график"), undefined, 'aria-pressed="false"')}</div></div>
  <div class="layout"><div class="main-column"><div class="stage"><canvas id="scene" tabindex="0" aria-label="${isEnv ? t("Арена жука. Инструменты построения слева, настройки мира справа.") : t("Схема нейронной сети. Доступный список нейронов во вкладке Нейроны справа.")}"></canvas><div class="stage-head"><strong>${isEnv ? t("ПОЛЕ / 01") : t("КОННЕКТОМ / 01")}</strong><span id="scene-meta">${isEnv ? `2 400 × 1 600 ${t("ед.")}` : "LIF · Δt 10 ms"}</span></div><span class="stage-badge" id="run-badge">${t("ПАУЗА")}</span>${isEnv ? `<div id="health-warning" class="health-warning" role="status" hidden><strong>${t("Нет здоровья")}</strong><span>${t("Движение продолжается")}</span></div>` : ""}<div class="tools" id="tools" aria-label="${t("Инструменты")}"></div><div class="stage-foot"><div class="legend">${isEnv ? `<span style="--color:#d3e7a3">${t("Жук")}</span><span style="--color:#c3dc83">${t("Пища")}</span><span style="--color:#d77e68">${t("Угроза")}</span>` : `<span style="--color:#84bcca">${t("Сенсоры")}</span><span style="--color:#c5d995">${t("Интернейроны")}</span><span style="--color:#e3ba7e">${t("Моторы")}</span>`}</div><span id="stage-hint"></span><span class="warning" id="sampling"></span></div><div class="camera-tools"><button id="fullscreen" aria-label="${t("Полноэкранный режим")}" title="${t("Полноэкранный режим")}">⛶</button><button id="toggle-inspector" title="${t("Показать или скрыть инспектор")}" aria-label="${t("Скрыть инспектор")}">☷</button><button id="zoom-out" aria-label="${t("Уменьшить масштаб")}">−</button><button id="fit" title="${t("Вписать всё")}" aria-label="${t("Вписать всё")}">⊡</button><button id="zoom-in" aria-label="${t("Увеличить масштаб")}">＋</button></div></div>
  ${isEnv ? `<div class="metrics"><div class="metric"><label>${t("ЗДОРОВЬЕ")}</label><strong id="health">100</strong><small>%</small><div class="bar"><i id="health-bar" style="width:100%"></i></div></div><div class="metric"><label>${t("ПОТРЕБЛЕНО ПИЩИ")}</label><strong id="eaten">0</strong><small>${t("порций")}</small><div class="bar"><i style="width:0"></i></div></div><div class="metric"><label>${t("ГОЛОД / УСТАЛОСТЬ")}</label><strong id="hunger">0 / 0</strong><small>%</small><div class="bar"><i id="hunger-bar" style="width:0"></i></div></div></div>` : ""}
  <div class="chart-wrap"><div class="chart-head"><span>${t("Активность")}</span><select id="chart-group" aria-label="${t("Группа графика")}"><option value="all">${t("Вся сеть")}</option></select><span class="value mono" id="rate">${t("0.0 Hz / нейрон")}</span><button id="csv" style="min-height:24px;padding:2px 7px;font-size:10px" title="${t("Экспорт измерений")}">CSV ↧</button></div><canvas id="chart" role="img" aria-label="${t("Средняя частота спайков за последние 30 секунд моделируемого времени")}"></canvas></div>
  <div class="transport"><button class="primary" id="play">${t("▶ Запустить")}</button><button id="step" title="${t("Один такт 10 мс")}">${t("▹ Такт")}</button><button id="reset" title="${t("Сбросить активность сети и вернуть жука на старт")}">${t("↺ Сброс")}</button><span class="label">${t("Темп")}</span><select id="speed" aria-label="${t("Темп симуляции")}"><option value="0.1">0.1×</option><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option><option value="5">5×</option></select><label class="label" for="compute-device">${t("Расчёт")}</label><select id="compute-device" aria-label="${t("Устройство расчёта")}" disabled><option value="cpu">CPU · NumPy</option></select><span class="time mono" id="time">00:00.00</span><span id="compute-notice" role="status" hidden></span></div></div><aside class="sidebar" id="sidebar" aria-label="${t("Настройки")}"></aside></div>
  <footer class="footer"><span id="stats">${t("Ожидание сервера…")}</span><span id="performance"></span><span class="right" id="version">${t("ФИКСИРОВАННЫЙ ШАГ 10 мс")} &nbsp;·&nbsp; v0.1</span></footer></main><div role="status" id="toast"></div><input class="file-input" id="file" type="file" accept=".json,application/json">`;
  installActionTooltips(app);
  const languageSelect = document.getElementById(
    "language",
  ) as HTMLSelectElement;
  languageSelect.value = language;
  languageSelect.onchange = () => changeLanguage(languageSelect.value);
  const api = new Connection();
  const computeSelect = document.getElementById(
    "compute-device",
  ) as HTMLSelectElement;
  const computeNotice = document.getElementById("compute-notice")!;
  let switchingDevice = false;
  let capabilities: ComputeDevices | undefined;
  const updateDevice = () => {
    if (switchingDevice) return;
    const device =
      api.state?.compute?.device ?? api.project?.compute?.device ?? "cpu";
    computeSelect.value = device;
    computeSelect.disabled = !capabilities || !api.online;
    computeNotice.textContent = translateServerMessage(
      api.state?.compute?.notice ?? "",
    );
    computeNotice.hidden = !computeNotice.textContent;
    computeSelect.title =
      t(
        "Устройство расчёта нейросети. Среда остаётся на CPU. GPU не всегда быстрее: сравните ms / такт.\n",
      ) +
      (capabilities?.devices
        .filter((d) => !d.available)
        .map((d) => `${d.label}: ${translateServerMessage(d.reason ?? "")}`)
        .join("\n") ?? "");
  };
  computeSelect.onchange = () => {
    const device = computeSelect.value;
    switchingDevice = true;
    computeSelect.disabled = true;
    computeNotice.textContent = t("Перенос состояния…");
    computeNotice.hidden = false;
    handle(
      api
        .command("compute", { device })
        .then(() => {
          // Acknowledge the selected device before the next SSE frame arrives.
          if (api.state) api.state.compute = { device, notice: "" };
          toast(t("Устройство изменено. Состояние сети сохранено."));
        })
        .finally(() => {
          switchingDevice = false;
          updateDevice();
        }),
    );
  };
  async function loadDevices() {
    const response = await fetch("/api/devices");
    if (!response.ok)
      throw new Error(
        t("Не удалось получить устройства; перезапустите сервер"),
      );
    capabilities = (await response.json()) as ComputeDevices;
    computeSelect.innerHTML = capabilities.devices
      .map(
        (d) =>
          `<option value="${escape(d.id)}" ${d.available ? "" : "disabled"}>${escape(d.label)}${d.available ? "" : t(" · недоступен")}</option>`,
      )
      .join("");
    updateDevice();
  }

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
  const layout = document.querySelector<HTMLElement>(".layout")!;
  const chart = document.querySelector<HTMLElement>(".chart-wrap")!;
  const toggle = document.getElementById("toggle-chart")!;
  let hideChart = localStorage.getItem("spiking-bug.hide-chart") === "true";
  const applyChart = () => {
    chart.hidden = hideChart;
    updateAction(
      toggle,
      hideChart ? "chart" : "chartOff",
      hideChart ? t("Показать график") : t("Скрыть график"),
    );
    toggle.setAttribute("aria-pressed", String(hideChart));
  };
  applyChart();
  toggle.onclick = () => {
    hideChart = !hideChart;
    localStorage.setItem("spiking-bug.hide-chart", String(hideChart));
    applyChart();
  };
  const full = document.getElementById("fullscreen")!;
  const updateFull = (enabled: boolean) => {
    layout.classList.toggle("editor-fullscreen", enabled);
    full.setAttribute(
      "aria-label",
      enabled ? t("Выйти из полноэкранного режима") : t("Полноэкранный режим"),
    );
    full.title = enabled
      ? t("Выйти из полноэкранного режима (Esc)")
      : t("Полноэкранный режим");
  };
  full.onclick = async () => {
    if (layout.classList.contains("editor-fullscreen")) {
      if (document.fullscreenElement) await document.exitFullscreen();
      updateFull(false);
    } else {
      updateFull(true);
      try {
        await layout.requestFullscreen();
      } catch {
        /* Embedded browsers may deny native fullscreen; fixed viewport still works. */
      }
    }
  };
  document.addEventListener("fullscreenchange", () => {
    updateFull(document.fullscreenElement === layout);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !document.fullscreenElement) updateFull(false);
  });
  document.getElementById("toggle-inspector")!.onclick = () => {
    const hidden = layout.classList.toggle("inspector-hidden");
    document
      .getElementById("toggle-inspector")!
      .setAttribute(
        "aria-label",
        hidden ? t("Показать инспектор") : t("Скрыть инспектор"),
      );
  };

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
      api
        .command("save")
        .then(() => toast(t("Эксперимент сохранён на сервере"))),
    );
  if (panel instanceof EditorView) {
    const arrange = document.getElementById(
      "arrange-graph",
    ) as HTMLButtonElement;
    let arranging = false;
    const updateArrange = () => {
      arrange.disabled = arranging || !api.project?.topology.neurons.length;
    };
    api.addEventListener("project", updateArrange);
    arrange.onclick = () => {
      if (arranging || !api.project) return;
      arranging = true;
      updateAction(arrange, "loading", t("Раскладываем…"));
      arrange.setAttribute("aria-busy", "true");
      updateArrange();
      handle(
        panel.arrange().finally(() => {
          arranging = false;
          updateAction(
            arrange,
            "layout",
            t("Разложить граф"),
            t(
              "Рецепторы слева, моторы справа; остальные нейроны размещаются по связям. Можно отменить через Ctrl / ⌘ + Z.",
            ),
          );
          arrange.removeAttribute("aria-busy");
          updateArrange();
        }),
      );
    };
    const newDocument = document.getElementById(
      "new-document",
    ) as HTMLButtonElement;
    newDocument.onclick = () => {
      if (
        !confirm(
          t(
            "Создать новую нервную систему? Текущая сеть будет заменена стартовой схемой. Чтобы сохранить её отдельно, сначала нажмите «Экспорт». Арена и её настройки сохранятся.",
          ),
        )
      )
        return;
      newDocument.disabled = true;
      handle(
        api
          .command("new_document")
          .then(() => {
            panel.resetDocument();
            toast(
              t(
                "Новый документ: базовая нервная система связана с окружением жука",
              ),
            );
          })
          .finally(() => {
            newDocument.disabled = false;
          }),
      );
    };
  }
  document.getElementById("export")!.onclick = () =>
    handle(
      fetch("/api/export")
        .then((r) => {
          if (!r.ok) throw new Error(t("Экспорт не выполнен"));
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
          toast(t("Эксперимент импортирован; симуляция на паузе"));
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
  document.getElementById("evolution")!.onclick = () => openEvolution(api);
  document.getElementById("trials")!.onclick = () => openTrials(api);
  document.getElementById("help")!.onclick = () => {
    const d = document.createElement("dialog");
    d.innerHTML = `<h2>${t("Одна нервная система. Два окна.")}</h2><p>${t("Окружение и коннектом подключены к одному серверу. Запуск, пауза, нейроны и назначения каналов общие. Эксперимент сохраняется после правок; «Сохранить» также фиксирует текущие объекты мира.")}</p><p>${t("Потенциал интегрируется и утекает каждый такт, включая рефрактерный период. Этот период блокирует только спайк. По умолчанию потенциал после спайка сохраняется.")}</p><p>${t("Прямые связи меняют потенциал. Модулирующие связи изменяют коэффициент чувствительности к возбуждению или торможению. Коэффициенты возвращаются к 1.")}</p><p>${t("График: спайки за 100 мс / число нейронов / 0.1 с. Ось времени — время модели. Окно до 30 с; экспорт CSV содержит те же измерения.")}</p><p>${t("Это исследовательский симулятор без автоматического обучения весов. Поведение задаётся построенной сетью.")}</p><button class="primary wide" id="close-help" style="margin-top:18px">${t("Понятно")}</button>`;
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
      `<option value="all">${t("Вся сеть")}</option>` +
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
    updateDevice();
    document.getElementById("version")!.textContent =
      `${s.stats.backend} · Δt 10 ms`;
    if (panel instanceof EditorView) panel.updateActivity();
    document.getElementById("play")!.textContent = s.running
      ? t("Ⅱ Пауза")
      : t("▶ Запустить");
    (document.getElementById("step") as HTMLButtonElement).disabled = s.running;
    document.getElementById("run-badge")!.textContent = s.running
      ? t("ЗАПУЩЕНО")
      : t("ПАУЗА");
    document.getElementById("time")!.textContent = `${Math.floor(s.t / 60)
      .toString()
      .padStart(2, "0")}:${(s.t % 60).toFixed(2).padStart(5, "0")}`;
    (document.getElementById("speed") as HTMLSelectElement).value = String(
      s.speed,
    );
    document.getElementById("stats")!.textContent = t(
      "{0} нейронов · {1} связей",
      s.stats.neurons.toLocaleString(locale),
      s.stats.synapses.toLocaleString(locale),
    );
    document.getElementById("performance")!.textContent = t(
      "{0} ms / такт · {1} MB{2}",
      s.stats.step_ms.toFixed(2),
      s.stats.memory_mb,
      s.stats.overruns ? t(" · отставаний: ") + s.stats.overruns : "",
    );
    if (isEnv) {
      const a = s.world.agent;
      document.getElementById("health-warning")!.hidden = a.health > 0;
      document.getElementById("health")!.textContent = (a.health * 100).toFixed(
        0,
      );
      document.getElementById("health-bar")!.style.width = a.health * 100 + "%";
      document.getElementById("eaten")!.textContent = String(a.eaten);
      document.getElementById("hunger")!.textContent =
        `${(a.hunger * 100).toFixed(0)} / ${(a.fatigue * 100).toFixed(0)}`;
      document.getElementById("hunger-bar")!.style.width = a.hunger * 100 + "%";
      document.getElementById("scene-meta")!.textContent =
        `${s.world.config.width.toLocaleString(locale)} × ${s.world.config.height.toLocaleString(locale)} ${t("ед.")}`;
    }
    if (s.error && s.error !== lastError) {
      toast(s.error);
      lastError = s.error;
    }
    drawChart(api);
  });
  const motors: Record<string, boolean> = {};
  const heldKeys = new Map<string, string>();
  let motorTimer: ReturnType<typeof setInterval> | undefined;
  function sendMotors() {
    handle(api.command("manual", motors, false));
  }
  function stopMotors() {
    heldKeys.clear();
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
          ArrowUp: "forward",
          ArrowDown: "backward",
          ArrowLeft: "left",
          ArrowRight: "right",
        } as Record<string, string>
      )[e.code];
      if (channel && api.project && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        heldKeys.set(e.code, channel);
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
          ArrowUp: "forward",
          ArrowDown: "backward",
          ArrowLeft: "left",
          ArrowRight: "right",
        } as Record<string, string>
      )[e.code];
      if (channel && heldKeys.has(e.code)) {
        heldKeys.delete(e.code);
        if (![...heldKeys.values()].includes(channel)) delete motors[channel];
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
    handle(loadDevices());
    requestAnimationFrame(() => {
      view.resize();
      if (!localStorage.getItem("spiking-bug.camera." + mode)) panel.fit();
    });
  } catch (e) {
    toast(t("Не удалось подключиться к серверу. Запустите ./run.sh"));
    document.getElementById("sidebar")!.innerHTML =
      `<div class="section"><h2>${t("Сервер недоступен")}</h2><p class="help">${t("Запустите ./run.sh и перезагрузите страницу.")}</p><button onclick="location.reload()">${t("Повторить")}</button></div>`;
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
    el.textContent = live ? t("Синхронизировано") : t("Связь потеряна");
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
  c.fillText(left.toFixed(1) + " " + t("с"), 32, h - 1);
  c.fillText(right.toFixed(1) + " " + t("с"), Math.max(40, w - 45), h - 1);
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
    ? t("{0} Hz / нейрон", (rows.at(-1)?.rates[key] ?? 0).toFixed(1))
    : t("Нет измерений");
}
