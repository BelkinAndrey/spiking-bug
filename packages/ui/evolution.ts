import { Connection, download, escape } from "./api";
import { field, select, values } from "./forms";
import { t, translateServerMessage, type Message } from "./i18n";

type Fitness = {
  value: number;
  lifetime: number;
  lifetime_std: number;
};
type Size = { neurons: number; synapses: number; ganglia: number };
type Evaluation = {
  fitness: Fitness;
  summary: {
    survival_pct: number;
    metrics: Record<string, { mean: number; std: number }>;
  };
};
type Individual = {
  id: string;
  generation: number;
  search: Evaluation;
  validation?: Evaluation;
  size: Size;
};
type History = {
  generation: number;
  best: number;
  median: number;
  std: number;
  size: Size;
};
type Artifact = {
  id: string;
  label: string;
  run_id: string;
  size: Size;
  fitness?: Fitness;
  generation: number;
};
type Job = {
  id: string;
  status: string;
  phase: string;
  settings: Record<string, any>;
  generation: number;
  candidate: number;
  completed: number;
  rejected?: number;
  episode: number;
  episodes: number;
  episode_progress: number;
  elapsed_seconds: number;
  evaluations_per_second: number;
  history: History[];
  best?: Individual;
  baseline?: Individual;
  error?: string;
  stop_reason?: string;
};
type Snapshot = { job: Job | null; artifacts: Artifact[] };

const controls: [string, Message, number, number, number, number][] = [
  ["elite", "Элита", 2, 1, 1, 127],
  ["tournament", "Размер турнира", 3, 1, 1, 128],
  ["validation_attempts", "Проверочные эпизоды", 5, 1, 1, 100],
  ["search_seed", "Первый поисковый seed", 1000, 1, 0, 2147483547],
  ["validation_seed", "Первый проверочный seed", 100000, 1, 0, 2147483547],
  ["add_rate", "Вероятность добавления / блок", 0.35, 0.01, 0, 1],
  ["delete_rate", "Вероятность удаления / блок", 0.15, 0.01, 0, 1],
  ["change_rate", "Вероятность изменения / блок", 0.7, 0.01, 0, 1],
  ["scale", "Масштаб мутаций", 0.2, 0.01, 0.001, 5],
  ["fill_bias", "Стремление заполнить пустоты", 0.9, 0.05, 0, 1],
  ["max_neurons", "Лимит нейронов", 256, 1, 1, 100000],
  ["max_ganglia", "Лимит ганглиев", 8, 1, 0, 128],
  ["max_rules", "Лимит правил B + D", 64, 1, 1, 4096],
  ["max_synapses", "Лимит развёрнутых синапсов", 10000, 1, 0, 500000],
  ["max_pair_checks", "Бюджет проверки пар", 2000000, 1, 1, 10000000],
  ["memory_mb", "Память популяции, МиБ", 256, 1, 16, 4096],
  ["archive_size", "Размер автоматического архива", 12, 1, 1, 100],
];
const metrics: [string, Message][] = [
  ["duration", "Время жизни, с"],
  ["food", "Пища за попытку"],
  ["health", "Здоровье, %"],
  ["damage", "Урон, п.п."],
  ["distance", "Путь, ед."],
  ["blocked_pct", "Блокировка, %"],
  ["firing_hz", "Активность, Гц / нейрон"],
];

export function openEvolution(api: Connection) {
  if (document.querySelector("#evolution-dialog")) return;
  const dialog = document.createElement("dialog");
  dialog.id = "evolution-dialog";
  dialog.className = "trials-dialog evolution-dialog";
  dialog.setAttribute("aria-labelledby", "evolution-title");
  const checkbox = (key: string, label: Message, checked = true) =>
    `<label class="row"><input type="checkbox" name="${key}" ${checked ? "checked" : ""}>${t(label)}</label>`;
  dialog.innerHTML = `<div class="trial-heading"><h2 id="evolution-title">${t("Эволюция")}</h2><button id="evolution-close" aria-label="${t("Закрыть")}">×</button></div>
    <p class="help">${t("Поиск архитектуры в копии выбранной среды. Закрытие окна и обновление страницы не останавливают серверную задачу.")}</p>
    <p class="help">${t("Среда")}: ${escape(api.project.name)} · ${api.project.world.config.width} × ${api.project.world.config.height}</p>
    <form id="evolution-form"><fieldset disabled><div class="trial-settings">
      ${select("preset", t("Доступные инструменты"), "ganglia", { direct: t("1 · Прямые связи"), modulation: t("2 · Прямые + модуляция"), ganglia: t("3 · Прямые + модуляция + ганглии") })}
      ${select("mode", t("Начало поиска"), "fresh", { fresh: t("Независимый запуск с нуля"), current: t("Начать от текущей сети"), continue: t("Продолжить из генома открытого экземпляра") })}
      ${field("population", t("Популяция"), 12, 1, 2, 128)}${field("generations", t("Поколения (0 — без лимита)"), 20, 1, 0, 10000)}
      ${field("attempts", t("Поисковые эпизоды"), 3, 1, 1, 100)}${field("duration", t("Длительность попытки, с"), 30, 1, 1, 3600)}
      ${field("workers", t("Количество процессов"), 1, 1, 1, 64)}
      ${field("seed", t("Seed эволюции"), 42, 1, 0, 2147483647)}${field("neuron_fatigue_rate", t("Доп. усталость / нейрон / с"), api.project.world.config.neuron_fatigue_rate ?? 0, 0.0001, 0, 1)}
    </div><div class="evolution-tools">${checkbox("direct_exc", "Возбуждающие прямые связи")}${checkbox("direct_inh", "Тормозящие прямые связи")}${checkbox("mod_exc", "Модуляция возбуждения · E")}${checkbox("mod_inh", "Модуляция торможения · I")}${checkbox("randomize", "Заново размещать пищу и угрозы в каждой попытке")}</div>
    <p class="help">${t("Fitness = среднее время жизни. Число нейронов влияет на усталость, а не вычитается из оценки. Коэффициент общий с настройками среды и сохраняется при запуске эволюции.")}</p>
    <p class="help">${t("За секунду симуляции добавляется коэффициент × число всех нейронов, включая рецепторные и моторные. Например, 0.001 × 100 = 10% усталости/с до вычета восстановления. Действует и в покое; 0 отключает добавку.")}</p>
    <p class="help">${t("Старт от текущей сети сохраняет её нейроны, ганглии и связи. Каждая исходная связь занимает одно правило B; при необходимости увеличьте лимиты. Несовместимые инструменты или лимиты не позволят запустить поиск.")}</p>
    <details><summary>${t("Расширенные настройки")}</summary><div class="trial-settings">${controls.map(([key, label, value, step, min, max]) => field(key, t(label), value, step, min, max)).join("")}</div>
    <p class="help">${t("Заполнение пустот: 0 — обычные случайные мутации, 1 — всегда предпочитать свободные области RGB и подключение незадействованных нейронов. Сенсоры и моторы сохраняют свои координаты.")}</p>
    <p class="help">${t("Количество процессов задаёт число одновременно выполняемых испытаний на CPU. 1 — последовательно. При нескольких процессах дополнительно работает координатор. Проверочные seed не участвуют в отборе. Продолжение из экземпляра начинает новый поиск от его генома.")}</p></details>
    <button class="primary" id="evolution-start">${t("Запустить эволюцию")}</button></fieldset></form>
    <p id="evolution-error" class="trial-error" role="alert" hidden></p>
    <section id="evolution-progress" hidden><div class="trial-heading"><strong id="evolution-status" role="status"></strong><button id="evolution-cancel">${t("Остановить")}</button></div><progress id="evolution-bar" max="1" value="0" aria-label="${t("Прогресс эволюции")}"></progress><p id="evolution-timing" class="help"></p><p id="evolution-seeds" class="help"></p></section>
    <section id="evolution-results" hidden><h3>${t("Fitness по поколениям")}</h3><canvas id="evolution-fitness-chart" role="img" aria-label="${t("Лучшее и медианное fitness")}"></canvas><h3>${t("Размер сети по поколениям")}</h3><canvas id="evolution-size-chart" role="img" aria-label="${t("Нейроны, синапсы и ганглии")}"></canvas><div id="evolution-history" class="trial-table-wrap"></div><div id="evolution-metrics"></div></section>
    <section><div class="trial-heading"><h3>${t("Сохранённые экземпляры")}</h3><button id="evolution-clear" disabled>${t("Очистить архив")}</button></div><p class="help">${t("Лучший экземпляр и последние завершённые кандидаты сохраняются автоматически. Закреплённые экземпляры не вытесняются архивом. Открытие заменит активный документ.")}</p><p class="help">${t("Очистка удаляет все файлы архива, включая закреплённые экземпляры и историю запусков. Доступна после остановки эволюции.")}</p><div id="evolution-artifacts"></div></section>`;
  document.body.append(dialog);
  dialog.showModal();
  const find = <T extends HTMLElement = HTMLElement>(id: string) =>
    dialog.querySelector<T>("#" + id)!;
  const form = find<HTMLFormElement>("evolution-form");
  let snapshot: Snapshot = { job: null, artifacts: [] };
  let pending = false,
    ready = false,
    sequence = 0,
    settingsId = "";
  let timer: ReturnType<typeof setTimeout> | undefined;
  const active = () =>
    ["running", "cancelling"].includes(snapshot.job?.status ?? "");
  const error = (message: string) => {
    find("evolution-error").textContent = message;
    find("evolution-error").hidden = !message;
  };
  const controlsState = () => {
    form.querySelector("fieldset")!.disabled = !ready || pending || active();
    find<HTMLButtonElement>("evolution-cancel").disabled =
      pending || snapshot.job?.status === "cancelling";
    find<HTMLButtonElement>("evolution-clear").disabled =
      !ready || pending || active();
    const direct =
      (form.elements.namedItem("preset") as HTMLSelectElement).value ===
      "direct";
    for (const name of ["mod_exc", "mod_inh"])
      (form.elements.namedItem(name) as HTMLInputElement).disabled = direct;
  };
  form
    .querySelector('[name="preset"]')!
    .addEventListener("change", controlsState);
  async function request(path = "", data?: unknown) {
    const r = await fetch(
      "/api/evolution" + path,
      data === undefined
        ? {}
        : {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
          },
    );
    if (r.status === 404)
      throw new Error(t("Для эволюции перезапустите сервер приложения."));
    const result = await r.json();
    if (!r.ok) {
      if (r.status === 409) await api.refresh();
      throw new Error(translateServerMessage(result.error));
    }
    return result;
  }
  function chart(
    id: string,
    rows: History[],
    series: { label: string; color: string; value: (h: History) => number }[],
  ) {
    const canvas = find<HTMLCanvasElement>(id);
    const width = Math.max(280, canvas.clientWidth || 800),
      height = 210;
    const left = 52,
      right = width - 16,
      top = 30 + series.length * 16,
      bottom = height - 24;
    canvas.width = width * 2;
    canvas.height = height * 2;
    const ctx = canvas.getContext("2d")!;
    ctx.scale(2, 2);
    const ys = rows.flatMap((h) => series.map((s) => s.value(h)));
    const low = Math.min(0, ...ys),
      high = Math.max(1, ...ys);
    ctx.font = "12px system-ui";
    ctx.fillStyle = "#9eaaa5";
    ctx.fillText(high.toFixed(2), 4, top + 4);
    ctx.fillText(low.toFixed(2), 4, bottom);
    ctx.fillText("1", left, height - 4);
    ctx.fillText(
      String((rows.at(-1)?.generation ?? 0) + 1),
      right - 12,
      height - 4,
    );
    series.forEach((s, index) => {
      ctx.fillStyle = s.color;
      ctx.fillText(s.label, left, 16 + index * 16);
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      rows.forEach((h, i) => {
        const x = left + (i / Math.max(1, rows.length - 1)) * (right - left);
        const y = bottom - ((s.value(h) - low) / (high - low)) * (bottom - top);
        if (i) ctx.lineTo(x, y);
        else ctx.moveTo(x, y);
      });
      ctx.stroke();
      if (rows.length === 1) {
        ctx.beginPath();
        ctx.arc(
          left,
          bottom - ((s.value(rows[0]) - low) / (high - low)) * (bottom - top),
          3,
          0,
          Math.PI * 2,
        );
        ctx.fill();
      }
    });
  }
  function evaluation(label: string, result?: Evaluation | null) {
    if (!result)
      return `<h4>${label}</h4><p class="help">${t("Нет завершённой оценки")}</p>`;
    const f = result.fitness;
    return `<h4>${label}</h4><p>Fitness <strong>${f.value.toFixed(3)}</strong> · σ ${f.lifetime_std.toFixed(3)} ${t("с")}</p><div class="trial-metrics"><div><span>${t("Выживаемость")}</span><strong>${result.summary.survival_pct.toFixed(1)}%</strong></div>${metrics
      .map(([key, label]) => {
        const m = result.summary.metrics[key];
        return `<div><span>${t(label)}</span><strong>${m.mean.toFixed(2)} <small>± ${m.std.toFixed(2)}</small></strong></div>`;
      })
      .join("")}</div>`;
  }
  let artifactVersion = "",
    resultVersion = "";
  function render() {
    const job = snapshot.job;
    if (job && settingsId !== job.id) {
      for (const [key, value] of Object.entries({
        ...job.settings,
        neuron_fatigue_rate: active()
          ? (job.settings.neuron_fatigue_rate ?? api.project.world.config.neuron_fatigue_rate ?? 0)
          : (api.project.world.config.neuron_fatigue_rate ?? 0),
      })) {
        const control = form.elements.namedItem(key) as HTMLInputElement | null;
        if (control) {
          if (control.type === "checkbox") control.checked = Boolean(value);
          else control.value = String(value);
        }
      }
      settingsId = job.id;
    }
    controlsState();
    find("evolution-progress").hidden = !job;
    find("evolution-results").hidden = !job?.best && !job?.baseline;
    if (job) {
      const statuses: Record<string, string> = {
        running: t("Поиск выполняется"),
        cancelling: t("Остановка…"),
        cancelled: t("Поиск остановлен"),
        completed: t("Поиск завершён"),
        failed: t("Ошибка поиска"),
        interrupted: t("Сервер был перезапущен"),
      };
      const phases: Record<string, string> = {
        starting: t("Подготовка"),
        baseline: t("Исходная сеть"),
        baseline_validation: t("Проверка исходной сети"),
        search: t("Поиск"),
        validation: t("Проверка чемпиона"),
        done: "",
      };
      find("evolution-status").textContent =
        `${statuses[job.status] ?? job.status} · ${phases[job.phase] ?? job.phase}`;
      find("evolution-cancel").hidden = !active();
      const bar = find<HTMLProgressElement>("evolution-bar");
      bar.hidden = job.settings.generations === 0 && !active();
      if (job.settings.generations === 0) bar.removeAttribute("value");
      else
        bar.value =
          job.status === "completed"
            ? 1
            : (job.generation +
                (job.candidate -
                  1 +
                  (job.episode + job.episode_progress) / job.episodes) /
                  job.settings.population) /
              job.settings.generations;
      find("evolution-timing").textContent = t(
        "Поколение {0}/{1} · экземпляр {2}/{3} · эпизод {4}/{5} · {6} с · {7} оценок/с · отклонено {8}",
        job.generation + 1,
        job.settings.generations || "∞",
        job.candidate,
        job.settings.population,
        job.episode,
        job.episodes,
        job.elapsed_seconds.toFixed(1),
        job.evaluations_per_second.toFixed(2),
        job.rejected ?? 0,
      );
      find("evolution-seeds").textContent =
        `CPU · ${t("Количество процессов")}: ${job.settings.workers ?? 1} · seed ${job.settings.seed} · ${t("Поиск")}: ${job.settings.search_seed}…${job.settings.search_seed + job.settings.attempts - 1} · ${t("Проверка чемпиона")}: ${job.settings.validation_seed}…${job.settings.validation_seed + job.settings.validation_attempts - 1}`;
      if (job.error) error(translateServerMessage(job.error));
      const version = JSON.stringify([
        job.id,
        job.history,
        job.best,
        job.baseline,
      ]);
      if (version !== resultVersion) {
        resultVersion = version;
        chart("evolution-fitness-chart", job.history, [
          {
            label: t("Лучшее fitness"),
            color: "#bad881",
            value: (h) => h.best,
          },
          {
            label: t("Медианное fitness"),
            color: "#bba8ed",
            value: (h) => h.median,
          },
        ]);
        chart("evolution-size-chart", job.history, [
          {
            label: t("Нейроны"),
            color: "#bad881",
            value: (h) => h.size.neurons,
          },
          {
            label: t("Синапсы"),
            color: "#82bfd0",
            value: (h) => h.size.synapses,
          },
          {
            label: t("Ганглии"),
            color: "#bba8ed",
            value: (h) => h.size.ganglia,
          },
        ]);
        find("evolution-history").innerHTML =
          `<table><thead><tr><th>${t("Поколение")}</th><th>${t("Лучшее fitness")}</th><th>${t("Медианное fitness")}</th><th>σ</th><th>N / S / G</th></tr></thead><tbody>${job.history
            .slice(-20)
            .map(
              (h) =>
                `<tr><td>${h.generation + 1}</td><td>${h.best.toFixed(3)}</td><td>${h.median.toFixed(3)}</td><td>${h.std.toFixed(3)}</td><td>${h.size.neurons} / ${h.size.synapses} / ${h.size.ganglia}</td></tr>`,
            )
            .join("")}</tbody></table>`;
        find("evolution-metrics").innerHTML =
          evaluation(t("Чемпион · поисковая оценка"), job.best?.search) +
          evaluation(t("Чемпион · проверочная оценка"), job.best?.validation) +
          `<details><summary>${t("Исходная сеть")}</summary>${evaluation(t("Поиск"), job.baseline?.search)}${evaluation(t("Проверка исходной сети"), job.baseline?.validation)}</details>`;
      }
    }
    const version = JSON.stringify(snapshot.artifacts);
    if (version !== artifactVersion) {
      artifactVersion = version;
      find("evolution-artifacts").innerHTML =
        snapshot.artifacts
          .map(
            (a) =>
              `<div class="evolution-artifact"><div><strong>${escape(a.label)}</strong><small>${escape(a.run_id.slice(0, 8))} · g${a.generation + 1} · N ${a.size.neurons} / S ${a.size.synapses} / G ${a.size.ganglia} · fitness ${a.fitness?.value.toFixed(3) ?? "—"}</small></div><div class="button-row"><button data-open="${escape(a.id)}">${t("Открыть")}</button><button data-download="${escape(a.id)}">JSON</button><button data-pin="${escape(a.id)}">${t("Закрепить")}</button></div></div>`,
          )
          .join("") ||
        `<p class="help">${t("Пока нет сохранённых экземпляров")}</p>`;
    }
  }
  async function action(work: () => Promise<void>) {
    if (pending) return;
    pending = true;
    sequence++;
    error("");
    controlsState();
    try {
      await work();
    } catch (e) {
      error((e as Error).message);
    } finally {
      pending = false;
      controlsState();
    }
  }
  find("evolution-artifacts").onclick = (e) => {
    const button = (e.target as HTMLElement).closest<HTMLButtonElement>(
      "button",
    );
    if (!button) return;
    void action(async () => {
      const id =
        button.dataset.open ?? button.dataset.download ?? button.dataset.pin!;
      if (button.dataset.pin) {
        snapshot = await request("/save", { id });
        render();
        return;
      }
      const project = await request("/artifact/" + id);
      if (button.dataset.download)
        download(
          id.replace("/", "_") + ".json",
          JSON.stringify(project, null, 2),
        );
      else {
        await api.command("import", project);
        dialog.close();
      }
    });
  };
  form.onsubmit = (e) => {
    e.preventDefault();
    if (pending || active() || !ready) return;
    const data = values(form);
    for (const name of [
      "randomize",
      "direct_exc",
      "direct_inh",
      "mod_exc",
      "mod_inh",
    ])
      data[name] = (form.elements.namedItem(name) as HTMLInputElement).checked;
    void action(async () => {
      snapshot = await request("", {
        settings: data,
        revision: api.project.revision,
      });
      await api.refresh();
      render();
    });
  };
  find("evolution-cancel").onclick = () =>
    void action(async () => {
      if (snapshot.job) {
        snapshot = await request("/cancel", { id: snapshot.job.id });
        render();
      }
    });
  find("evolution-clear").onclick = () => {
    if (!ready || active()) return;
    void action(async () => {
      snapshot = await request("/clear", {});
      render();
    });
  };
  async function poll() {
    if (!dialog.open) return;
    try {
      if (!pending) {
        const version = sequence;
        const next = await request();
        if (version === sequence && !pending && dialog.open) {
          snapshot = next;
          ready = true;
          render();
        }
      }
    } catch (e) {
      error((e as Error).message);
    }
    if (dialog.open) timer = setTimeout(poll, 750);
  }
  const resize = new ResizeObserver(() => {
    resultVersion = "";
    if (dialog.open) render();
  });
  resize.observe(dialog);
  find("evolution-close").onclick = () => dialog.close();
  dialog.onclose = () => {
    clearTimeout(timer);
    resize.disconnect();
    sequence++;
    dialog.remove();
  };
  void poll();
}
