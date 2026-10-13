import { t, translateServerMessage } from "./i18n";
import type { Project, State } from "./types";
export class Connection extends EventTarget {
  project!: Project;
  state?: State;
  online = false;
  lastFrame = 0;
  private source?: EventSource;
  private refreshing?: Promise<void>;
  async init() {
    await this.refresh();
    this.source = new EventSource("/api/events");
    this.source.onmessage = (e) => {
      this.state = JSON.parse(e.data);
      this.online = true;
      this.lastFrame = Date.now();
      this.dispatchEvent(new Event("state"));
      if (this.state!.revision !== this.project.revision)
        void this.refresh().catch(() => {});
    };
    this.source.onerror = () => {
      this.online = false;
      this.dispatchEvent(new Event("state"));
    };
  }
  async refresh() {
    if (this.refreshing) return this.refreshing;
    this.refreshing = (async () => {
      const r = await fetch("/api/project");
      if (!r.ok) throw new Error(t("Сервер недоступен"));
      this.project = await r.json();
      this.dispatchEvent(new Event("project"));
    })().finally(() => {
      this.refreshing = undefined;
    });
    return this.refreshing;
  }
  async command(action: string, data: unknown = {}, refresh = true) {
    const r = await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, data, revision: this.project.revision }),
    });
    const result = await r.json();
    if (!r.ok) {
      if (r.status === 409) await this.refresh();
      throw new Error(
        translateServerMessage(result.error || t("Ошибка запроса")),
      );
    }
    if (refresh) await this.refresh();
    return result;
  }
}
export function escape(s: unknown) {
  return String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ]!,
  );
}
export function uid(prefix: string) {
  return `${prefix}_${crypto.randomUUID().slice(0, 8)}`;
}
export function download(
  name: string,
  content: string,
  type = "application/json",
) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function toast(message: string) {
  const el = document.getElementById("toast")!;
  el.textContent = translateServerMessage(message);
  el.classList.add("show");
  clearTimeout(Number(el.dataset.timer));
  el.dataset.timer = String(
    setTimeout(() => el.classList.remove("show"), 5500),
  );
}
export function handle(p: Promise<unknown>) {
  void p.catch((e) => toast(e.message));
}
