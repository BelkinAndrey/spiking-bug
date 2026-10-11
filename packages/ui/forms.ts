import { escape } from "./api";
export const field = (
  key: string,
  label: string,
  value: unknown,
  step: number | string = "any",
  min?: number,
  max?: number,
) =>
  `<label>${label}<input name="${key}" type="number" value="${escape(value)}" step="${typeof step === "number" && step < 1 ? "any" : step}" ${min !== undefined ? `min="${min}"` : ""} ${max !== undefined ? `max="${max}"` : ""} required></label>`;
export const input = (
  key: string,
  label: string,
  value: unknown,
  full = false,
) =>
  `<label class="${full ? "full" : ""}">${label}<input name="${key}" value="${escape(value)}" required></label>`;
export const select = (
  key: string,
  label: string,
  value: string,
  options: Record<string, string>,
  full = false,
) =>
  `<label class="${full ? "full" : ""}">${label}<select name="${key}">${Object.entries(
    options,
  )
    .map(
      ([k, v]) =>
        `<option value="${escape(k)}" ${k === value ? "selected" : ""}>${escape(v)}</option>`,
    )
    .join("")}</select></label>`;
export function values(form: HTMLFormElement): Record<string, any> {
  return Object.fromEntries(
    [...new FormData(form)].map(([k, v]) => [
      k,
      form.querySelector<HTMLInputElement>(`[name="${k}"]`)?.type === "number"
        ? Number(v)
        : v,
    ]),
  );
}
export function onForm(
  root: HTMLElement,
  id: string,
  fn: (v: Record<string, any>) => void,
) {
  root
    .querySelector<HTMLFormElement>("#" + id)
    ?.addEventListener("submit", (e) => {
      e.preventDefault();
      fn(values(e.currentTarget as HTMLFormElement));
    });
}
