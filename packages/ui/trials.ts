import { Connection, download } from "./api";
import { t, translateServerMessage } from "./i18n";
import { field, values } from "./forms";

type TrialRow = {
  attempt: number;
  seed: number;
  duration: number;
  survived: boolean;
  food: number;
  food_per_minute: number;
  health: number;
  damage: number;
  distance: number;
  blocked_pct: number;
  firing_hz: number;
};
type Metric = { mean: number; std: number; min: number; max: number };
type TrialJob = {
  id: string;
  status: "running" | "cancelling" | "completed" | "cancelled" | "failed";
  settings: {
    attempts: number;
    duration: number;
    seed: number;
    randomize: boolean;
  };
  project_name: string;
  revision: number;
  device: string;
  completed: number;
  current_seconds: number;
  progress: number;
  elapsed_seconds: number;
  simulated_seconds: number;
  speedup: number;
  rows: TrialRow[];
  summary: { survival_pct: number; metrics: Record<string, Metric> } | null;
  error: string | null;
};

export function openTrials(api: Connection) {
  if (document.querySelector("#trials-dialog")) return;
  const dialog = document.createElement("dialog");
  dialog.id = "trials-dialog";
  dialog.className = "trials-dialog";
  dialog.setAttribute("aria-labelledby", "trials-title");
  dialog.innerHTML = `<div class="trial-heading"><h2 id="trials-title">${t("Испытание нейронной сети")}</h2><button type="button" id="trials-close" aria-label="${t("Закрыть")}">×</button></div>
    <p class="help">${t("Копия текущей сети и среды. Каждая попытка начинается с точки старта, полного здоровья и сброшенной активности сети. Завершение — при нулевом здоровье или по времени.")}</p>
    <form id="trials-form"><fieldset><div class="trial-settings">
      ${field("attempts", t("Количество попыток"), 30, 1, 1, 1000)}
      ${field("duration", t("Длительность попытки, с"), 120, 1, 1, 3600)}
      ${field("seed", t("Начальный seed"), api.project.world.config.seed, 1, 0, 2147483647)}
      </div><label class="row trial-randomize"><input type="checkbox" name="randomize">${t("Заново размещать пищу и угрозы в каждой попытке")}</label>
      <p class="help">${t("Стены, зоны пищи и настройки среды сохраняются. Без перемешивания сохраняется текущая расстановка объектов. Seed увеличивается на 1; при отсутствии случайности попытки могут совпадать.")}</p>
      <button type="submit" class="primary" id="trials-start">${t("Запустить испытание")}</button></fieldset></form>
    <p class="help">${t("Расчёт без отрисовки и ограничения темпа, с шагом 10 мс. Открытый эксперимент продолжает работать независимо.")}</p>
    <p id="trials-error" class="trial-error" role="alert" hidden></p>
    <section id="trials-progress" hidden><div class="trial-progress-label"><strong id="trials-status" role="status"></strong><span id="trials-count"></span></div>
      <progress id="trials-bar" max="1" value="0" aria-label="${t("Прогресс испытания")}"></progress>
      <p id="trials-timing" class="help"></p><p id="trials-source" class="help"></p>
      <button type="button" id="trials-cancel">${t("Остановить испытание")}</button></section>
    <section id="trials-results" hidden><div class="trial-heading"><h3>${t("Результаты завершённых попыток")}</h3><div class="button-row"><button type="button" id="trials-json">JSON</button><button type="button" id="trials-csv">CSV</button></div></div>
      <p class="help">${t("Выживаемость — доля попыток без обнуления здоровья. Метрики: среднее ± стандартное отклонение. Урон учитывает угрозы и усталость; блокировка — долю команд перемещения без сдвига.")}</p>
      <div id="trials-metrics" class="trial-metrics"></div>
      <div class="trial-table-wrap"><table><thead><tr><th>№ / seed</th><th>${t("Исход")}</th><th>${t("Время, с")}</th><th>${t("Пища")}</th><th>${t("Здоровье, %")}</th><th>${t("Путь, ед.")}</th></tr></thead><tbody id="trials-rows"></tbody></table></div></section>
      <p class="help">${t("Окно можно закрыть: испытание продолжится. Последний результат доступен до следующего запуска или перезапуска сервера.")}</p>`;
  document.body.append(dialog);
  dialog.showModal();
  const find = <T extends HTMLElement = HTMLElement>(id: string) =>
    dialog.querySelector<T>("#" + id)!;
  let job: TrialJob | null = null;
  let pending = false;
  let generation = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let resultVersion = "";
  let settingsId = "";
  const active = () =>
    job?.status === "running" || job?.status === "cancelling";
  const error = (message: string) => {
    find("trials-error").textContent = message;
    find("trials-error").hidden = !message;
  };
  const refreshControls = () => {
    find("trials-form").querySelector("fieldset")!.disabled =
      pending || active();
    find<HTMLButtonElement>("trials-cancel").disabled =
      pending || job?.status === "cancelling";
  };
  const request = async (
    path = "",
    data?: unknown,
  ): Promise<TrialJob | null> => {
    const response = await fetch(
      "/api/trials" + path,
      data === undefined
        ? {}
        : {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
          },
    );
    if (response.status === 404)
      throw new Error(
        t("Для режима испытаний перезапустите сервер приложения."),
      );
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 409) await api.refresh();
      throw new Error(translateServerMessage(result.error));
    }
    return result;
  };
  const render = () => {
    refreshControls();
    if (!job) {
      find("trials-progress").hidden = true;
      find("trials-results").hidden = true;
      resultVersion = "";
      settingsId = "";
      return;
    }
    if (settingsId !== job.id) {
      for (const name of ["attempts", "duration", "seed"] as const)
        dialog.querySelector<HTMLInputElement>(`[name="${name}"]`)!.value =
          String(job.settings[name]);
      dialog.querySelector<HTMLInputElement>('[name="randomize"]')!.checked =
        job.settings.randomize;
      settingsId = job.id;
    }
    find("trials-progress").hidden = false;
    const status = {
      running: t("Испытание выполняется"),
      cancelling: t("Остановка…"),
      completed: t("Испытание завершено"),
      cancelled: t("Испытание остановлено"),
      failed: t("Ошибка испытания"),
    }[job.status];
    find("trials-status").textContent = status;
    find("trials-count").textContent =
      `${job.completed} / ${job.settings.attempts}`;
    find<HTMLProgressElement>("trials-bar").value = job.progress;
    find("trials-timing").textContent = t(
      "Прошло: {0} с · Время модели: {1} с · Ускорение: {2}×",
      job.elapsed_seconds.toFixed(2),
      job.simulated_seconds.toFixed(1),
      job.speedup.toFixed(1),
    );
    find("trials-source").textContent = t(
      "Снимок: {0} · Ревизия {1} · {2}",
      job.project_name,
      job.revision,
      job.device,
    );
    find("trials-cancel").hidden = !active();
    if (job.error) error(translateServerMessage(job.error));
    const version = `${job.id}:${job.completed}`;
    if (version === resultVersion) return;
    resultVersion = version;
    find("trials-results").hidden = !job.summary;
    if (!job.summary) return;
    const metrics = [
      ["duration", t("Время жизни, с")],
      ["food", t("Пища за попытку")],
      ["food_per_minute", t("Пища / мин")],
      ["health", t("Здоровье, %")],
      ["damage", t("Урон, п.п.")],
      ["distance", t("Путь, ед.")],
      ["blocked_pct", t("Блокировка, %")],
      ["firing_hz", t("Активность, Гц / нейрон")],
    ];
    find("trials-metrics").innerHTML =
      `<div><span>${t("Выживаемость")}</span><strong>${job.summary.survival_pct.toFixed(1)}%</strong></div>` +
      metrics
        .map(([key, label]) => {
          const m = job!.summary!.metrics[key];
          return `<div><span>${label}</span><strong>${m.mean.toFixed(2)} <small>± ${m.std.toFixed(2)}</small></strong><small>${m.min.toFixed(2)} – ${m.max.toFixed(2)}</small></div>`;
        })
        .join("");
    find("trials-rows").innerHTML = job.rows
      .map(
        (r) =>
          `<tr><td>${r.attempt} / ${r.seed}</td><td>${r.survived ? t("Лимит времени") : t("Нет здоровья")}</td><td>${r.duration.toFixed(2)}</td><td>${r.food}</td><td>${r.health.toFixed(1)}</td><td>${r.distance.toFixed(1)}</td></tr>`,
      )
      .join("");
  };
  const poll = async () => {
    if (!dialog.open) return;
    try {
      if (!pending) {
        const version = generation;
        const next = await request();
        if (generation === version && !pending) {
          job = next;
          error("");
          render();
        }
      }
    } catch (e) {
      error((e as Error).message);
    }
    if (dialog.open) timer = setTimeout(poll, 500);
  };
  find<HTMLFormElement>("trials-form").onsubmit = async (event) => {
    event.preventDefault();
    if (pending || active()) return;
    const form = find<HTMLFormElement>("trials-form");
    const data = values(form);
    data.randomize =
      form.querySelector<HTMLInputElement>('[name="randomize"]')!.checked;
    generation++;
    pending = true;
    error("");
    refreshControls();
    try {
      job = await request("", {
        revision: api.project.revision,
        settings: data,
      });
      render();
    } catch (e) {
      error((e as Error).message);
    } finally {
      pending = false;
      refreshControls();
    }
  };
  find("trials-cancel").onclick = async () => {
    if (!job || pending) return;
    generation++;
    pending = true;
    refreshControls();
    try {
      job = await request("/cancel", { id: job.id });
      render();
    } catch (e) {
      error((e as Error).message);
    } finally {
      pending = false;
      refreshControls();
    }
  };
  find("trials-json").onclick = () => {
    if (job) download("trials.json", JSON.stringify(job, null, 2));
  };
  find("trials-csv").onclick = () => {
    if (!job?.rows.length) return;
    const keys = Object.keys(job.rows[0]) as (keyof TrialRow)[];
    download(
      "trials.csv",
      keys.join(",") +
        "\n" +
        job.rows.map((r) => keys.map((k) => r[k]).join(",")).join("\n"),
      "text/csv",
    );
  };
  find("trials-close").onclick = () => dialog.close();
  dialog.onclose = () => {
    clearTimeout(timer);
    dialog.remove();
  };
  void poll();
}
